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
| OSM source | Geofabrik Philippines extract |
| Install location | `~/graphhopper/` (outside the project repo — too large to commit) |
| Service port | 8989 |
| First-import time | ~3 min on Pi 5 (8 GB) with `-Xmx6g` |
| Steady-state heap | 2 GB |
| Query latency (post-CH) | ~10 ms |

## Why these choices

- **Prebuilt JAR, not built from source.** Building GraphHopper from source on a
  Pi 5 takes ~1 hour and bloats the SD card with a Maven cache. The prebuilt
  JAR from GitHub Releases is the same artifact.
- **`foot` profile.** This is a walking wearable. Foot routing uses pedestrian
  paths and avoids motorways.
- **Contraction Hierarchies (`profiles_ch`).** Pre-computes shortest-path
  shortcuts during import. Adds time to import; reduces query latency from
  ~seconds to ~milliseconds. Right tradeoff for a real-time wearable.
- **`bind_host: 127.0.0.1`.** GraphHopper has no authentication. Localhost-only
  prevents anyone on the Wi-Fi from querying or DoS-ing the engine. Switch to
  `0.0.0.0` only when a concrete cross-device use case appears.
- **Heap split: 6 GB for import, 2 GB for runtime.** The 6 GB heap is only
  needed during the one-time graph build. After `graph-cache/` exists,
  subsequent runs memory-map it and need very little heap.

## Prerequisites

```bash
sudo apt update
sudo apt install -y openjdk-21-jre-headless
java -version    # confirm "21.x.x"
```

Free disk: at least 6 GB (JAR ~80 MB, PBF ~500 MB, graph-cache a few GB, plus
breathing room).

## Install

```bash
mkdir -p ~/graphhopper
cd ~/graphhopper

# 1. Prebuilt GraphHopper web JAR
wget https://github.com/graphhopper/graphhopper/releases/download/11.0/graphhopper-web-11.0.jar

# 2. Philippines OSM extract (~500 MB)
wget https://download.geofabrik.de/asia/philippines-latest.osm.pbf
```

For newer GraphHopper releases see https://github.com/graphhopper/graphhopper/releases.

## Configure

Create `~/graphhopper/config.yml`:

```yaml
graphhopper:
  datareader.file: "philippines-latest.osm.pbf"
  graph.location: graph-cache

  # Pedestrian profile (GH 9+ uses custom_model_files, not the legacy
  # `vehicle: foot` syntax which is rejected as of GH 11)
  profiles:
    - name: foot
      custom_model_files: [foot.json]

  profiles_ch:
    - profile: foot

  # Skip non-walkable roads at import — required as of GH 11
  import.osm.ignored_highways: motorway,trunk

  # Encoded values needed for the foot profile
  graph.encoded_values: foot_access,foot_priority,foot_average_speed

server:
  application_connectors:
    - type: http
      port: 8989
      bind_host: 127.0.0.1
  admin_connectors:
    - type: http
      port: 8990
      bind_host: 127.0.0.1
```

## First run — builds the graph cache

```bash
cd ~/graphhopper
java -Xmx6g -Xms2g -jar graphhopper-web-11.0.jar server config.yml
```

Wait for `Started GraphHopperApplication`. **Do not Ctrl-C until that line
appears** — a partial `graph-cache/` is corrupt and must be deleted before
retrying.

## Verify

In a second SSH session, while the server runs:

```bash
curl 'http://localhost:8989/route?point=14.5995,120.9842&point=14.6042,120.9822&profile=foot&points_encoded=false'
```

Expected: JSON containing `"paths": [...]` with turn-by-turn instructions and
street names. Sub-100 ms response.

## Subsequent runs (after the graph cache exists)

```bash
cd ~/graphhopper
java -Xmx2g -jar graphhopper-web-11.0.jar server config.yml
```

Smaller heap is fine — the graph cache is memory-mapped, not loaded.

## Refreshing the map data

OSM updates continuously. To pull a newer Philippines extract:

```bash
cd ~/graphhopper
rm -rf graph-cache
wget -O philippines-latest.osm.pbf https://download.geofabrik.de/asia/philippines-latest.osm.pbf
# Re-run the first-run command — it rebuilds graph-cache from the new PBF.
```
