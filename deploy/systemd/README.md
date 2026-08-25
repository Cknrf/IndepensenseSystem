# systemd services

Auto-start GraphHopper, Photon, and the Ollama warmup on the Raspberry
Pi so the wearable's backend comes up automatically on boot — no more
"three SSH sessions to launch the system."

The `indepensense.service` unit is the wearable's own long-running
runtime (main loop, fall detection, voice pipeline, telemetry, etc.).
It depends on the other three so systemd starts them in the right order.

Ollama itself ships with its own systemd service (installed by the
official Ollama installer). The `ollama-warmup.service` here pre-loads
the NLU model on boot so the first user command doesn't pay the 25-40 s
cold-load cost.

## Install

Copy all four unit files into systemd's directory, enable them at boot,
and start them now:

```bash
cd ~/Desktop/thesis/IndepensenseSystem/deploy/systemd

sudo cp graphhopper.service    /etc/systemd/system/
sudo cp photon.service         /etc/systemd/system/
sudo cp ollama-warmup.service  /etc/systemd/system/
sudo cp indepensense.service   /etc/systemd/system/

sudo systemctl daemon-reload
sudo systemctl enable graphhopper.service photon.service ollama-warmup.service indepensense.service
sudo systemctl start  graphhopper.service photon.service ollama-warmup.service indepensense.service
```

For dev work you may prefer to leave `indepensense.service` disabled and
run the app by hand (`python -m indepensense.app`) so you can iterate.
Enable it once you're ready to demo boot-to-wearable.

## Verify

Check status:

```bash
sudo systemctl status graphhopper photon ollama-warmup
```

- **graphhopper** — should read `Active: active (running)` within ~5 s.
- **photon** — same, but takes ~30-60 s to open its OpenSearch index.
- **ollama-warmup** — `oneshot` service, expected state is `Active: active (exited)` — this is normal for oneshot units. Its job is to fire once at boot, load the model, and exit. Check the model is actually loaded with `ollama ps`.
- **indepensense** — `Active: active (running)`. Full startup takes ~30-60 s (Whisper + Piper model loading + Ollama warmup); watch the log for `Ready. Running fall-detection loop.`

Follow logs in real time:

```bash
sudo journalctl -u graphhopper -f
sudo journalctl -u photon -f
sudo journalctl -u indepensense -f
```

Smoke-test the endpoints:

```bash
curl -s 'http://127.0.0.1:8989/route?point=14.5995,120.9842&point=14.6010,120.9860&profile=foot&points_encoded=false' | head -c 200
curl -s 'http://127.0.0.1:2322/api?q=Manila&limit=1' | head -c 200
```

## Change something later

If the JAR filename changes (new GraphHopper or Photon release):

```bash
sudo systemctl stop graphhopper
# edit /etc/systemd/system/graphhopper.service — update the JAR filename
sudo systemctl daemon-reload
sudo systemctl start graphhopper
```

## Secrets

Two separate things, both read at startup and never logged.

### 1. Device credential — `/etc/indepensense/device.key`

Authenticates this unit to the backend. Every `/raspberry/*` request sends
it as `Authorization: Bearer <uuid>.<secret>`, and the backend derives
which device is calling from it. One line, no trailing content:

```
08b7e9b6-d601-446a-b708-7dafc65e4cc2.wpBVy5n_tMgSiW_WQ0yZTl1DAgCOvl-sQjRo8AYx5Qo
```

**Permissions — read this before copying the provisioning instructions.**
The credential is documented as root-owned mode 0600, but the service runs
as `User=cknrf`. A root-owned 0600 file is readable by root *only*, so the
service cannot read it and every request becomes a 401. Give the file to
the account the service actually runs as:

```bash
sudo install -d -m 0755 /etc/indepensense
sudo chown cknrf:cknrf /etc/indepensense/device.key
sudo chmod 0600 /etc/indepensense/device.key
```

Still 0600 — readable only by its owner — but the owner is now the service
user. Verify:

```bash
sudo -u cknrf cat /etc/indepensense/device.key >/dev/null && echo readable
```

A missing, unreadable or malformed credential is **not fatal**. The
wearable logs why and runs without the dashboard: fall detection, obstacle
warnings, navigation, voice and emergency SMS all still work. Only
heartbeats and HTTP alerts are lost, and SMS is the channel that matters
when data is unavailable anyway.

### 2. Cloud LLM key — `.env` at the project root

```bash
cd /home/cknrf/Desktop/thesis/IndepensenseSystem
cp .env.example .env
nano .env                      # paste INDEPENSENSE_CLOUD_API_KEY
chmod 600 .env
sudo systemctl restart indepensense
```

**No `EnvironmentFile=` is needed in the unit** — `config.py` resolves the
path from its own location, so it works the same under systemd as it does
in a manual test over SSH.

`.env` is gitignored and must stay that way. A missing or empty key is a
supported configuration: the wearable answers unknown utterances locally
and logs that the cloud fallback is unconfigured once at startup.

### Verify both

```bash
python -m indepensense.intents.tests.manual.cloud_probe      # LLM key
python -m indepensense.telemetry.tests.manual.send_alert_test  # device credential
```

Or straight against the backend:

```bash
curl -s https://<host>/raspberry/guardians \
  -H "Authorization: Bearer $(cat /etc/indepensense/device.key)"
```

401 means a credential problem, and it will not fix itself — the unit
needs re-provisioning or un-revoking. The runtime treats 401 as a
persistent fault and backs off to 15-minute retries rather than hammering
the backend; look for `credential_rejected` in the logs.

### HTTPS is required

`BACKEND_URL` must be `https://`. The credential is a password travelling
in a header on every request, and over plaintext every hop in between can
read it — so the runtime refuses to start rather than leaking it quietly.
Only `http://localhost` is exempt, because that traffic never reaches a
network. Private and VPN addresses are **not** exempt.

## Assumptions

The unit files assume:

- User is `cknrf` and the JARs live at `/home/cknrf/graphhopper/` and
  `/home/cknrf/photon/`. Change `User=` and `WorkingDirectory=` if your
  install differs.
- Java 21 is installed and the default `java` on `PATH` is `/usr/bin/java`.
- GraphHopper 11.0 (`graphhopper-web-11.0.jar`) and Photon 1.2.0
  (`photon-1.2.0.jar`) — update the JAR filenames if you upgrade.
- Both services can run concurrently on the same Pi 5 (~4 GB combined
  heap on an 8 GB machine).
- `indepensense.service` runs as the same user that owns `.env`, or it
  cannot read the key.

## Uninstall

If you ever want to stop auto-starting these:

```bash
sudo systemctl disable graphhopper photon
sudo systemctl stop    graphhopper photon
sudo rm /etc/systemd/system/graphhopper.service /etc/systemd/system/photon.service
sudo systemctl daemon-reload
```
