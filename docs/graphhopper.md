# GraphHopper — local routing engine

GraphHopper is a self-hosted routing service. Given two coordinates and a
profile (e.g. `foot`), it returns a turn-by-turn walking path with street
names. IndepenSense uses it for **offline** navigation on the Raspberry Pi 5,
so the wearable works without internet connectivity.

Routing runs against an OpenStreetMap extract — Philippines for this thesis.
After the one-time graph-cache build, queries return in ~10 ms.

## Status reference

| Item | Value |
|---|---|
| Versions used | GraphHopper 11.0, Java 21 |
| OSM source | Geofabrik Philippines extract (~350 MB) |
| Install location | `~/graphhopper/` (outside the project repo — too large to commit) |
| Service port | 8989 |
| First-import time | ~2.5 min on Pi 5 (8 GB) with `-Xmx6g -Xms2g` |
| Steady-state heap | 2 GB |
| Query latency (post-CH) | ~10 ms |

## Why these choices

- **Prebuilt JAR, not built from source.** Building GraphHopper from source on
  a Pi 5 takes ~1 hour and bloats the SD card with a Maven cache. The
  prebuilt JAR from GitHub Releases is the identical artifact.
- **`foot` profile.** This is a walking wearable. Foot routing uses
  pedestrian paths and avoids motorways.
- **Contraction Hierarchies (`profiles_ch`).** Pre-computes shortest-path
  shortcuts during import. Adds time to import; reduces query latency from
  ~seconds to ~milliseconds. Right tradeoff for a real-time wearable.
- **`bind_host: 0.0.0.0`.** Listens on all network interfaces so other
  devices on the local network (guardian phone, development laptop) can hit
  the API. If only localhost access is needed, switch to `127.0.0.1` —
  GraphHopper has no authentication, so the broader binding should match an
  actual use case.
- **Heap split: 6 GB for import, 2 GB for runtime.** The 6 GB heap is only
  needed during the one-time graph build. After `graph-cache/` exists,
  subsequent runs memory-map it and need very little heap.

## Prerequisites

```bash
sudo apt update
sudo apt install -y openjdk-21-jre-headless
java -version    # confirm "21.x.x"
```

Free disk: at least 5 GB (JAR ~80 MB, PBF ~350 MB, graph-cache a few GB, plus
breathing room).

## Install

```bash
mkdir -p ~/graphhopper
cd ~/graphhopper

# 1. Prebuilt GraphHopper web JAR
wget https://github.com/graphhopper/graphhopper/releases/download/11.0/graphhopper-web-11.0.jar

# 2. Philippines OSM extract (~350 MB)
wget https://download.geofabrik.de/asia/philippines-latest.osm.pbf
```

For newer GraphHopper releases see https://github.com/graphhopper/graphhopper/releases.

## Configure

Create `~/graphhopper/config.yml`:

```yaml
graphhopper:
  datareader.file: "philippines-latest.osm.pbf"
  graph.location: graph-cache

  # Skip non-walkable motorized highways at import — required as of GH 11.
  #
  # `trunk` and `trunk_link` are NOT in this list, and that is specific to
  # where this device is used. GraphHopper's own examples exclude trunk,
  # which is reasonable in Europe where trunk roads are near-motorways.
  # In the Philippines the same tag sits on ordinary national highways
  # that people walk along, with shoulders and shops fronting them.
  #
  # Measured, from 13.937387,121.118698 to the Jollibee 1.3 km away:
  #
  #   trunk excluded : 3.5 km, 41 min, start snapped 230 m off-position
  #   trunk admitted : 1.6 km, 19 min, start snapped   7 m off-position
  #   reference (OSRM, same two points) : 1.4 km, 19 min
  #
  # The remaining 200 m against the reference is the engine, not a fault:
  # OSRM and GraphHopper weight surfaces and crossings differently and
  # run on different data vintages. The walking time matches exactly.
  #
  # 1200 m of that 1400 m reference route runs along President Jose P.
  # Laurel Highway — tagged `trunk`, therefore absent from the graph
  # entirely. That is also why the start snapped 230 m away: the nearest
  # way to the user was the highway, and it was not there to snap to. The
  # wearable announced a walk 2.5x longer than the real one.
  #
  # Pedestrian safety is handled by tags, not by road class: the foot
  # profile still honours `foot=no` and `foot_access`, so segments
  # genuinely barred to pedestrians stay excluded. A blanket class
  # exclusion cannot make that distinction, and the detour it forces has
  # its own cost — more road crossings and longer exposure.
  #
  # `motorway` and `motorway_link` stay excluded. The STAR Tollway really
  # does bar pedestrians.
  import.osm.ignored_highways: "motorway,motorway_link"

  # Encoded values required for the foot profile's internal schema
  graph.encoded_values: "foot_access, hike_rating, foot_priority, country, road_class, foot_road_access, mtb_rating, foot_average_speed"

  # Pedestrian profile (GH 9+ uses custom_model_files, the legacy
  # `vehicle: foot` syntax is rejected as of GH 11)
  profiles:
    - name: foot
      custom_model_files: [foot.json]

  profiles_ch:
    - profile: foot

server:
  application_connectors:
    - type: http
      port: 8989
      bind_host: 0.0.0.0
  admin_connectors:
    - type: http
      port: 8990
      bind_host: 0.0.0.0
```

## The foot model adds one rule to GraphHopper's default

`deploy/graphhopper/service_roads.json` is the whole of it:

```json
{ "priority": [ { "if": "road_class == SERVICE", "multiply_by": "0.6" } ] }
```

It is **layered on** the bundled foot model rather than replacing it.
`custom_model_files` takes a list and merges them in order, which is the
same pattern the bundled model's own header documents
(`[foot.json, foot_elevation.json]`). So upstream improvements to
`foot.json` still arrive on a GraphHopper upgrade, and the diff that is
ours stays one line.

Copying the stock model into a local `foot.json` was tried first and
GraphHopper refuses it outright:

```
Custom model file name 'foot.json' is already used for built-in
profiles. Use another name
```

A good refusal — it is the same shadowing ambiguity that makes
request-level merging confusing (see the trap at the end of this
section).

### Why

Short frontage-road stubs run parallel to Philippine national highways
and connect at nearly every junction. Under the stock weighting the
router took whichever of the two was a few metres shorter between each
pair of junctions, so a 1.6 km walk weaved across the highway eight
times:

```
    74 m  President Jose P. Laurel Highway
    18 m  (unnamed)     Turn left     <- hop off
    59 m  (unnamed)
    19 m  (unnamed)     Turn right    <- hop back
   247 m  President Jose P. Laurel Highway
```

Each weave is a road crossing, announced to someone who cannot see it,
and it bought nothing: the walker was already on the highway for 70% of
the distance. Seventeen spoken instructions for 1.6 km is its own
failure — Google and OSRM say four.

### What it is worth

One route, against two independent references:

| model | distance | instructions |
|---|---|---|
| `trunk` excluded at import | 3.5 km, start snapped 230 m off | — |
| profile as GraphHopper ships it | 1.57 km | 17 |
| **+ `service` x 0.6** | **1.44 km** | **5** |
| Google Maps | 1.4 km | ~4 |
| OSRM (fossgis_osrm_foot) | 1.4 km | ~4 |

Ten destinations around Lipa, to check it was not tuned to one journey
(`routing/tests/manual/model_compare.py`):

```
10 routes: distance -0.48 km total, instructions -57 total
No route got meaningfully worse.
```

Distance fell slightly, so the straighter routes are not being bought
with extra walking.

### Installing it

```bash
mkdir -p ~/graphhopper/custom_models
cp ~/Desktop/thesis/IndepensenseSystem/deploy/graphhopper/service_roads.json \
   ~/graphhopper/custom_models/
```

and in `config.yml`, under `graphhopper:`:

```yaml
  custom_models.directory: custom_models
```

with the profile listing both files, built-in first:

```yaml
  profiles:
    - name: foot
      custom_model_files: [foot.json, service_roads.json]
```

`foot.json` still resolves from inside the JAR; `service_roads.json`
comes from the directory above and is merged on top.

**This needs a graph rebuild.** The weighting is baked into the
contraction-hierarchy preparation, so editing the model changes nothing
until the cache is rebuilt. Follow the section below.

### A trap worth knowing

A custom model sent **in a request** is *merged* with the profile's
model, not substituted for it. Sending what looks like a copy of the
stock model therefore applies `foot_priority` twice, and sending a model
with a rule *removed* does not remove it. Both produce plausible numbers
and wrong conclusions — the finding above took two false starts for
exactly that reason. For request-level experiments send only the delta,
and use an empty model as the baseline.

## Changing `ignored_highways` means rebuilding the graph

The exclusion list is applied **at import**, so editing it has no effect
until the cache is rebuilt — the old graph simply keeps serving routes
that omit the roads you just re-admitted.

```bash
sudo systemctl stop graphhopper
cd ~/graphhopper
rm -rf graph-cache/
java -Xmx6g -Xms2g -jar graphhopper-web-11.0.jar server config.yml
# Wait for the LAST line: `Started Server@... @NNNNNms`.
#
# Not "Starting GraphHopperApplication" — GH 11 prints that at the very
# beginning, and an earlier version of this document said to wait for
# "Started GraphHopperApplication", which never appears at all. Ctrl-C on
# the "Starting" line discards the build.
#
# The reliable marker is the server answering:
#     curl -s localhost:8989/health
sudo systemctl start graphhopper
```

The one-off import needs the 6 GB heap; the service runs at 2 GB because
that is enough once `graph-cache/` exists. Verify with the same two
points the measurement above used:

```bash
python -m indepensense.routing.tests.manual.geocode_probe \
    "Jollibee" --from 13.937387,121.118698 --nearest --route
```

Expect roughly 1.4 km and a start snap under 50 m. A snap still in the
hundreds of metres means the road network near that point is missing for
some other reason, and the reference link the probe prints is the way to
tell.

## First run — builds the graph cache

```bash
cd ~/graphhopper
java -Xmx6g -Xms2g -jar graphhopper-web-11.0.jar server config.yml
```

Wait for the **last** line, `Started Server@... @NNNNNms`. **Do not Ctrl-C
before it appears** — a partial `graph-cache/` is corrupt. If interrupted,
delete it (`rm -rf graph-cache`) before retrying.

Do not wait for "Started GraphHopperApplication": GH 11 logs
`Starting GraphHopperApplication` at the top of the run and never logs a
matching "Started". Stopping on the "Starting" line throws the build away.

## Verify

In a second SSH session, while the server runs:

```bash
curl 'http://127.0.0.1:8989/route?point=14.5995,120.9842&point=14.6010,120.9860&profile=foot&points_encoded=false'
```

Expected: JSON containing `"paths": [...]` with LineString coordinates,
distance, and turn-by-turn instructions including street names.

## Subsequent runs (after the graph cache exists)

```bash
cd ~/graphhopper
java -Xmx2g -jar graphhopper-web-11.0.jar server config.yml
```

Smaller heap is sufficient — the graph-cache is memory-mapped by the kernel,
not loaded into the JVM heap.

## Auto-start on boot (systemd)

Once you have a working setup, you don't want to SSH in and launch the JAR
by hand every reboot. A systemd unit file lives in
`deploy/systemd/graphhopper.service`. Install with:

```bash
cd ~/Desktop/thesis/IndepensenseSystem/deploy/systemd
sudo cp graphhopper.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now graphhopper.service
sudo systemctl status graphhopper.service
```

See `deploy/systemd/README.md` for the full install steps (both this service
and Photon at once), verification commands, and uninstall.

## Refreshing the map data

OSM updates continuously. To pull a newer Philippines extract:

```bash
cd ~/graphhopper
rm -rf graph-cache
wget -O philippines-latest.osm.pbf https://download.geofabrik.de/asia/philippines-latest.osm.pbf
# Re-run the first-run command — it rebuilds graph-cache from the new PBF.
```
