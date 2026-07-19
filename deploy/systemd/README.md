# systemd services

Auto-start GraphHopper and Photon on the Raspberry Pi so the wearable's
routing + geocoding backend comes up automatically on boot — no more
"three SSH sessions to launch the system."

Ollama already ships with its own systemd service (installed by the
official Ollama installer). We add one companion unit that pre-loads the
NLU model on boot so the first user command doesn't pay the 25-40 s
cold-load cost: `ollama-warmup.service`.

## Install

Copy the two unit files into systemd's directory, enable them at boot,
and start them now:

```bash
cd ~/Desktop/thesis/IndepensenseSystem/deploy/systemd

sudo cp graphhopper.service    /etc/systemd/system/
sudo cp photon.service         /etc/systemd/system/
sudo cp ollama-warmup.service  /etc/systemd/system/

sudo systemctl daemon-reload
sudo systemctl enable graphhopper.service photon.service ollama-warmup.service
sudo systemctl start  graphhopper.service photon.service ollama-warmup.service
```

## Verify

Check status:

```bash
sudo systemctl status graphhopper photon ollama-warmup
```

- **graphhopper** — should read `Active: active (running)` within ~5 s.
- **photon** — same, but takes ~30-60 s to open its OpenSearch index.
- **ollama-warmup** — `oneshot` service, expected state is `Active: active (exited)` — this is normal for oneshot units. Its job is to fire once at boot, load the model, and exit. Check the model is actually loaded with `ollama ps`.

Follow logs in real time:

```bash
sudo journalctl -u graphhopper -f
sudo journalctl -u photon -f
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

## Uninstall

If you ever want to stop auto-starting these:

```bash
sudo systemctl disable graphhopper photon
sudo systemctl stop    graphhopper photon
sudo rm /etc/systemd/system/graphhopper.service /etc/systemd/system/photon.service
sudo systemctl daemon-reload
```
