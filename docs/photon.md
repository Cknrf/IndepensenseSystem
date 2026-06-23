# Photon — local geocoding engine

Photon is a self-hosted geocoding service. Given a string like `"SM Lipa"`, it
returns the matching coordinates (forward geocoding). Given coordinates, it
returns the nearest place name (reverse geocoding). IndepenSense uses it to
translate user-named destinations into coordinates that GraphHopper can route
to.

## Status reference

| Item | Value |
|---|---|
| Versions used | Photon 1.2.0 (OpenSearch backend), Java 21 |
| Data source | Photon JSONL dump (Philippines, ~830k places) |
| Install location | `~/photon/` (outside the project repo) |
| Service port | 2322 |
| Import time | ~5 min on Pi 5 (8 GB) with `-Xmx4g` |
| Steady-state heap | 2 GB |

## Why these choices

- **OpenSearch backend, not ElasticSearch.** The legacy ES-backed Photon
  distributions and their `.tar.bz2` dumps are deprecated. Komoot has moved to
  OpenSearch with a modern JSONL.zst dump format.
- **Stream the dump through `zstd` directly into the importer.** Avoids
  writing a ~15 GB intermediate JSONL file to SD card. The `-` at the end of
  `-import-file -` tells Photon to read from stdin.
- **Heap split: 4 GB for import, 2 GB for runtime.** Photon's hot data lives
  in the OS page cache (memory-mapped index files), not the JVM heap. Keeping
  the runtime heap small gives the OS more room to cache the index — which is
  what actually makes queries fast.
- **`bind_host: 127.0.0.1`.** Same reasoning as GraphHopper — Photon has no
  authentication. Switch to `0.0.0.0` only when needed.

## Prerequisites

```bash
sudo apt update
sudo apt install -y openjdk-21-jre-headless zstd
java -version    # confirm "21.x.x"
zstd --version
```

Free disk: at least 25 GB (compressed dump ~2 GB, extracted index ~15-20 GB,
plus breathing room).

## Install

```bash
mkdir -p ~/photon
cd ~/photon

# Prebuilt Photon JAR (OpenSearch variant). Verify current URL on GitHub.
wget https://github.com/komoot/photon/releases/download/1.2.0/photon-1.2.0.jar
```

Browse https://github.com/komoot/photon/releases for the current version.

## Build the index

```bash
cd ~/photon

# 1. Download the Philippines JSONL.zst dump (~2 GB)
wget https://download1.graphhopper.com/public/extracts/by-country-code/ph/photon-dump-philippines-1.0-latest.jsonl.zst

# 2. Stream decompress directly into Photon's importer
zstd --stdout -d photon-dump-philippines-1.0-latest.jsonl.zst \
  | java -Xmx4g -jar photon-1.2.0.jar import -import-file -
```

The importer takes ~5 min and creates a `photon_data/` directory.

## Cleanup

```bash
rm photon-dump-philippines-1.0-latest.jsonl.zst   # reclaim ~2 GB
ls -lh photon_data/                                # confirm the index exists
```

You can also `apt remove zstd` once the import is done — it is only needed for
import, not for runtime.

## First run

```bash
cd ~/photon
java -Xmx2g -jar photon-1.2.0.jar
```

Wait for the line confirming it is listening on port `2322`. First startup
takes ~30-60 s as Photon opens the index and warms caches.

## Verify

Forward geocoding (place → coordinates):

```bash
curl 'http://localhost:2322/api?q=Manila&limit=3'
curl 'http://localhost:2322/api?q=Lipa+City&limit=3'
```

Reverse geocoding (coordinates → place):

```bash
curl 'http://localhost:2322/reverse?lat=14.5995&lon=120.9842'
```

Both return GeoJSON `FeatureCollection`s.

## End-to-end pipeline check

With both Photon (2322) and GraphHopper (8989) running:

```bash
# 1. Place name -> coordinates
curl 'http://localhost:2322/api?q=SM+Lipa&limit=1'
# (read lat/lon from the response)

# 2. Coordinates -> route
curl 'http://localhost:8989/route?point=<lat1>,<lon1>&point=<lat2>,<lon2>&profile=foot&points_encoded=false'
```

If both succeed, the geocode → route pipeline is operational.

## Updating the index

Re-download the latest JSONL.zst dump and re-run the import. The new
`photon_data/` replaces the old atomically. Stop Photon before import; restart
after.
