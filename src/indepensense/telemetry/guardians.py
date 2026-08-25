"""The guardian contact list, fetched from the backend and cached to disk.

Emergency SMS needs phone numbers, and the device knows only its own
credential. The backend derives the device from the bearer token and
resolves it to the people who should be told:

    Device --OneToOne--> AssistedUser <--ManyToMany--> Guardian

Note the direction. `AssistedUser.device` is a non-nullable one-to-one, so
the device cannot ask "who are my guardians" in one hop — the backend has
to walk the chain. That is why this is a purpose-built endpoint rather
than a generic query.

Why a disk cache
----------------

The device needs these numbers exactly when it has no data connection,
which is also exactly when it cannot fetch them. Fetching lazily at
emergency time would fail in the only situation the feature exists for.
So we fetch once at startup while the network is likely up, and persist,
and let a failed fetch fall back to the last known list. A device that
boots in a dead spot still knows who to text.

The accepted cost: a guardian added while the device is running is
invisible to it until restart. See `config.GUARDIAN_CACHE_PATH`.

Backend contract
----------------

    GET /raspberry/guardians
    Authorization: Bearer <uuid>.<secret>

    200 -> {"guardians": [
              {"name": "Maria Cruz",
               "contactNumber": "+639171234567",
               "role": "parent"}
            ]}
    400 -> authenticated, but no assisted user linked to this device yet.
           Normal on a freshly provisioned unit; retry later.
    401 -> credential missing, wrong or revoked. Will not fix itself.

There is no device id in the path. It used to be
`/raspberry/guardians/<deviceID>`, which meant any caller could ask for
any device's guardian phone numbers by guessing a UUID. Identity now
comes from the token, and the path carries nothing.
"""
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path

from indepensense.credential import DeviceCredential
from indepensense.net import require_https

_GUARDIANS_PATH = "/raspberry/guardians"


@dataclass(frozen=True)
class GuardianContact:
    name: str
    contact_number: str
    role: str = ""


def normalise_number(raw: str, default_country_code: str) -> str | None:
    """Coerce a stored number into the E.164 form the modem requires.

    `Guardian.contactNumber` in the backend is a plain string column with
    no format constraint, so it holds whatever the guardian typed into
    the web form — "0917 123 4567", "+63 917-123-4567", "(0917)1234567".
    The modem needs "+639171234567" and silently fails on anything else,
    so the boundary between the two is here.

    Rules, in order:
      - strip everything that isn't a digit or a leading '+'
      - already '+'-prefixed          -> keep as is
      - leading '0' (local trunk code) -> replace with '+<country>'
      - bare national number          -> prefix '+<country>'

    Returns None when the result cannot be a real number, so a malformed
    row is skipped rather than becoming a failed send at 2 a.m.

    The proper fix is validating on input in the web app; this is the
    defensive half, and it cannot rescue a genuinely wrong number.
    """
    if not raw:
        return None

    text = raw.strip()
    has_plus = text.startswith("+")
    digits = re.sub(r"\D", "", text)
    if not digits:
        return None

    if has_plus:
        candidate = f"+{digits}"
    elif digits.startswith("0"):
        candidate = f"+{default_country_code}{digits.lstrip('0')}"
    elif digits.startswith(default_country_code):
        candidate = f"+{digits}"
    else:
        candidate = f"+{default_country_code}{digits}"

    # E.164 allows at most 15 digits; anything under ~8 cannot be a real
    # mobile number and is far more likely a truncated or placeholder row.
    body = candidate[1:]
    if not 8 <= len(body) <= 15:
        return None
    return candidate


class GuardianDirectory:
    """Holds the guardian list, backed by the backend and a disk cache.

    Construction is cheap and never does I/O beyond reading the cache, so
    it is safe to build during startup before the network is known to
    work. Call `refresh()` to try the backend.
    """

    def __init__(
        self,
        base_url: str,
        credential: DeviceCredential | None,
        cache_path: Path,
        timeout_s: float = 10.0,
        default_country_code: str = "63",
    ):
        """`credential` may be None — an unprovisioned unit still loads any
        cached list from disk, so SMS keeps working on numbers fetched
        before the credential became invalid. `refresh()` then always
        fails, which is honest.

        Raises if `base_url` is not https and a credential is present, for
        the same reason as `NestJSTelemetryClient`.
        """
        if credential is not None:
            require_https(base_url, "BACKEND_URL")
        self._base_url = base_url.rstrip("/")
        self._credential = credential
        self._cache_path = cache_path
        self._timeout_s = timeout_s
        self._default_country_code = default_country_code
        self._contacts: list[GuardianContact] = self._load_cache()

    # ------------------------------------------------------------------ API

    def contacts(self) -> list[GuardianContact]:
        """Every known guardian, freshest available."""
        return list(self._contacts)

    def sms_numbers(self) -> list[str]:
        """Normalised, de-duplicated numbers ready to hand to the modem.

        Order is preserved so behaviour is deterministic and testable.
        Unusable numbers are dropped with a warning rather than attempted.
        """
        seen: set[str] = set()
        numbers: list[str] = []
        for contact in self._contacts:
            number = normalise_number(contact.contact_number, self._default_country_code)
            if number is None:
                print(
                    f"[guardians] skipping unusable number for {contact.name!r}: "
                    f"{contact.contact_number!r}",
                    file=sys.stderr,
                )
                continue
            if number in seen:
                continue
            seen.add(number)
            numbers.append(number)
        return numbers

    def refresh(self) -> bool:
        """Fetch from the backend and update the cache.

        Returns True when the list was refreshed. On any failure the
        in-memory list is left untouched — a backend hiccup must not
        erase a perfectly good cached list.
        """
        fetched = self._fetch()
        if fetched is None:
            print(
                f"[guardians] refresh failed; keeping {len(self._contacts)} "
                f"cached contact(s)",
                file=sys.stderr,
            )
            return False
        self._contacts = fetched
        self._write_cache(fetched)
        print(f"[guardians] refreshed: {len(fetched)} contact(s)", flush=True)
        return True

    # -------------------------------------------------------------- internals

    def _fetch(self) -> list[GuardianContact] | None:
        """GET the list. None on any failure. Mirrors `nestjs_client._post`.

        Unlike the telemetry client this does not raise on 401. There is
        no retry queue behind it — `refresh()` is called once at startup —
        so there is no loop to protect from hammering. A distinct log line
        is enough.
        """
        import requests  # lazy: keeps the module importable off-device

        if self._credential is None:
            print(
                "[guardians] no device credential — cannot fetch. Using "
                "whatever is cached on disk.",
                file=sys.stderr,
            )
            return None

        url = f"{self._base_url}{_GUARDIANS_PATH}"
        try:
            response = requests.get(
                url,
                headers={"Authorization": self._credential.authorization_header()},
                timeout=self._timeout_s,
            )
        except requests.RequestException as exc:
            print(f"[guardians] GET network error: {exc}", file=sys.stderr)
            return None

        if response.status_code == 401:
            print(
                f"[guardians] backend rejected the device credential "
                f"(device {self._credential.device_id}). This will not fix "
                f"itself — the unit needs re-provisioning or un-revoking.",
                file=sys.stderr,
            )
            return None

        if not response.ok:
            preview = response.text[:200] if response.text else "(empty)"
            print(
                f"[guardians] GET returned {response.status_code}: {preview}",
                file=sys.stderr,
            )
            return None

        try:
            return _parse_guardians(response.json())
        except (ValueError, TypeError, KeyError) as exc:
            print(f"[guardians] malformed response: {exc}", file=sys.stderr)
            return None

    def _load_cache(self) -> list[GuardianContact]:
        if not self._cache_path.exists():
            return []
        try:
            raw = json.loads(self._cache_path.read_text())
            return _parse_guardians(raw)
        except (OSError, ValueError, TypeError, KeyError) as exc:
            # A corrupt cache is not worth crashing startup over. Losing
            # it degrades SMS until the next successful refresh, which is
            # strictly better than a device that will not boot.
            print(f"[guardians] unreadable cache ({exc}); ignoring", file=sys.stderr)
            return []

    def _write_cache(self, contacts: list[GuardianContact]) -> None:
        payload = {
            "guardians": [
                {
                    "name": c.name,
                    "contactNumber": c.contact_number,
                    "role": c.role,
                }
                for c in contacts
            ]
        }
        try:
            self._cache_path.parent.mkdir(parents=True, exist_ok=True)
            self._cache_path.write_text(json.dumps(payload, indent=2))
        except OSError as exc:
            print(f"[guardians] could not write cache: {exc}", file=sys.stderr)


def _parse_guardians(payload: dict) -> list[GuardianContact]:
    """Turn the backend/cache JSON into contacts.

    Rows without a contact number are dropped — they cannot be texted, so
    carrying them would only produce failures later.
    """
    rows = payload["guardians"]
    if not isinstance(rows, list):
        raise TypeError("'guardians' must be a list")

    contacts = []
    for row in rows:
        number = (row.get("contactNumber") or "").strip()
        if not number:
            continue
        contacts.append(
            GuardianContact(
                name=(row.get("name") or "").strip(),
                contact_number=number,
                role=(row.get("role") or "").strip(),
            )
        )
    return contacts
