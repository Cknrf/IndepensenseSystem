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

**`ollama-warmup.service` runs a script from the repo**, by absolute path:
`deploy/systemd/ollama-warmup.sh`. Nothing to copy — but the repo has to
stay at `/home/cknrf/Desktop/thesis/IndepensenseSystem`, and if it moves,
that path in the unit moves with it.

The script exists so the model name is read from `config.NLU_MODEL`
rather than written into the unit. It used to be hardcoded as
`qwen3:1.7b` in two places while `config.py` switched between that and
`qwen3:4b`, so flipping `NLU_LARGE_MODEL` would have left the unit
waiting for a model nobody pulled and then pinning the wrong one.

### Emergency SMS needs one more file

Unit files alone do not get SMS working. ModemManager refuses
`--messaging-create-sms` from a non-interactive session unless a polkit
rule allows it, and the failure is quiet — the backend alert still
succeeds, so only the text goes missing:

```bash
sudo cp ../polkit/50-indepensense-modemmanager.rules /etc/polkit-1/rules.d/
sudo systemctl restart polkit
```

The username in that rule must match `User=` in `indepensense.service`.
Full explanation in `docs/sim7600.md`.

For dev work you may prefer to leave `indepensense.service` disabled and
run the app by hand (`python -m indepensense.app`) so you can iterate.
Enable it once you're ready to demo boot-to-wearable.

### Audio needs one extra step — read this before demoing

The wearable talks through **PipeWire, which is a per-user session
service**. Running the app by hand works because a login shell already has
`XDG_RUNTIME_DIR` pointing at the session. A systemd *system* service does
not, so without the two steps below the wearable boots, reads every sensor,
classifies every command — **and says nothing at all**. It is a silent
failure, and by far the easiest way to lose a demo.

`indepensense.service` already sets the variable. The other half is making
sure the session it points at exists without anybody logging in:

```bash
sudo loginctl enable-linger cknrf
```

Verify after a reboot, with no keyboard attached and nobody logged in:

```bash
ls /run/user/1000/pipewire-0          # the socket must exist
journalctl -u indepensense | grep -i "could not set sink volume"
```

An empty grep and an audible greeting mean it is working. If the greeting
is silent, this is the first thing to check — before suspecting the audio
device, the Piper voices, or the code.

### Audio needs a second extra step: stop PipeWire suspending the output

```bash
mkdir -p ~/.config/wireplumber/wireplumber.conf.d
cp ../pipewire/51-no-suspend.conf ~/.config/wireplumber/wireplumber.conf.d/
systemctl --user restart wireplumber
```

WirePlumber suspends the audio node after a few seconds idle, and the
resume swallows roughly the first **0.7-0.9 seconds** of whatever plays
next. Speech mostly survives that — it runs for seconds, so it loses its
opening and context covers the gap. The short non-speech cues do not
survive it at all: the PTT press chime, the stop cue, the busy cue and
the waiting blip are each shorter than the window, so they vanish
completely.

That is a silent failure of the entire acknowledgement vocabulary for a
user who cannot see the device, and no amount of buffering in the
application fixes it — see the measurements in the config file itself.

Verify: `python -m indepensense.voice.tests.manual.cue_test` and listen.
Every cue must be audible, including the ones after a long pause.

### Powering off by voice

The `system.shutdown` intent runs `sudo systemctl poweroff`, and the
service account has no password. One narrow rule grants exactly that
one command and nothing else:

```bash
echo "cknrf ALL=(root) NOPASSWD: /usr/bin/systemctl poweroff" \
  | sudo tee /etc/sudoers.d/indepensense-poweroff
sudo chmod 0440 /etc/sudoers.d/indepensense-poweroff
sudo visudo -c -f /etc/sudoers.d/indepensense-poweroff   # must say "parsed OK"
```

Always check with `visudo -c` before trusting it — a malformed file in
`/etc/sudoers.d/` can lock `sudo` out entirely. Without this rule the
wearable asks for confirmation, hears it, and then says it could not
turn itself off, which is the intended failure rather than a silent one.

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
