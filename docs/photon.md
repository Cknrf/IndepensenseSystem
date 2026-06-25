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

- **OpenSearch backend, not ElasticSearch.** Legacy ElasticSearch-backed
  Photon distributions and their `.tar.bz2` dumps are deprecated. Modern
  Photon uses OpenSearch fed by a compressed JSONL dump.
- **Stream the dump through `zstd` directly into the importer.** Avoids
  writing an uncompressed JSONL file (multi-GB) to SD card. The trailing `-`
  in `-import-file -` tells Photon to read from stdin.
- **Heap split: 4 GB for import, 2 GB for runtime.** Photon's hot data lives
  in the OS page cache (memory-mapped index files), not the JVM heap.
  Keeping the runtime heap small gives the OS more room to cache the index —
  which is what makes queries fast.
- **`-listen-ip 0.0.0.0`.** Same reasoning as GraphHopper — listens on all
  interfaces so other devices on the network can call the API. Switch to
  `127.0.0.1` if only the Pi itself needs to query.

## Prerequisites

```bash
sudo apt update
sudo apt install -y openjdk-21-jre-headless zstd
java -version    # confirm "21.x.x"
zstd --version
```

Free disk: at least 5 GB (compressed dump ~83 MB, index `photon_data/`
~1.5 GB, plus breathing room).

## Install

```bash
mkdir -p ~/photon
cd ~/photon

# Prebuilt Photon JAR (OpenSearch variant)
wget https://github.com/komoot/photon/releases/download/1.2.0/photon-1.2.0.jar
```

Browse https://github.com/komoot/photon/releases for the current version.

## Build the index

```bash
cd ~/photon

# 1. Philippines JSONL.zst dump (~83 MB)
wget https://download1.graphhopper.com/public/asia/philippines/photon-dump-philippines-1.0-latest.jsonl.zst

# 2. Decompress and pipe directly into Photon's importer
zstd --stdout -d photon-dump-philippines-1.0-latest.jsonl.zst \
  | java -Xmx4g -jar photon-1.2.0.jar import -import-file -
```

The importer creates a `photon_data/` directory containing the OpenSearch index.

## Cleanup

```bash
rm photon-dump-philippines-1.0-latest.jsonl.zst   # reclaim ~83 MB
sudo apt purge -y zstd && sudo apt autoremove -y  # only needed for import
```

## First run

```bash
cd ~/photon
java -Xmx2g -jar photon-1.2.0.jar serve -listen-ip 0.0.0.0
```

The `serve` subcommand and `-listen-ip` flag are required in Photon 1.2.0 —
without them the process exits at startup.

## Verify

Forward geocoding (place → coordinates):

```bash
curl 'http://127.0.0.1:2322/api?q=Manila&limit=1'
curl 'http://127.0.0.1:2322/api?q=Lipa+City&limit=1'
```

Reverse geocoding (coordinates → place):

```bash
curl 'http://127.0.0.1:2322/reverse?lat=14.5995&lon=120.9842'
```

Both return GeoJSON `FeatureCollection` responses.

## End-to-end pipeline check

With both Photon (2322) and GraphHopper (8989) running:

```bash
# 1. Place name -> coordinates
curl 'http://127.0.0.1:2322/api?q=SM+Lipa&limit=1'
# (read lat/lon from the response)

# 2. Coordinates -> route
curl 'http://127.0.0.1:8989/route?point=13.9317,121.1670&point=13.9410,121.1620&profile=foot&points_encoded=false'
```

If both return valid JSON, the geocode → route pipeline is operational.

## Updating the index

```bash
cd ~/photon
rm -rf photon_data/
# Re-download the latest .jsonl.zst and re-run the import pipeline.
```
