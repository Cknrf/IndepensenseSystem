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

The runtime reads its API keys from a `.env` at the project root, loaded by
`config.py` on import. **No `EnvironmentFile=` is needed in the unit** —
`config.py` resolves the path from its own location, so it works the same
under systemd as it does when you run a manual test over SSH.

```bash
cd /home/cknrf/Desktop/thesis/IndepensenseSystem
cp .env.example .env
nano .env                      # paste INDEPENSENSE_CLOUD_API_KEY
chmod 600 .env                 # readable only by the service user
sudo systemctl restart indepensense
```

`.env` is gitignored and must stay that way. A missing or empty key is a
supported configuration: the wearable answers unknown utterances locally
and logs that the cloud fallback is unconfigured once at startup.

Verify the key was picked up:

```bash
python -m indepensense.intents.tests.manual.cloud_probe
```

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
