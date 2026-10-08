#!/usr/bin/env bash
#
# Rebuild the GraphHopper graph after a routing-model or import change.
#
# The manual procedure is four steps with a trap in the middle: the
# import runs in the foreground and has to be interrupted at exactly the
# right log line. Stop too early and the cache is half-written and
# unusable; wait for the wrong string and you wait forever, because
# GraphHopper 11 logs "Starting GraphHopperApplication" at the top of the
# run and never logs a matching "Started". This watches for the real
# marker and handles the rest.
#
#     bash deploy/graphhopper/rebuild.sh
#
# Takes about three minutes. Safe to re-run.
set -euo pipefail

GH_DIR="${GH_DIR:-$HOME/graphhopper}"
JAR="${JAR:-graphhopper-web-11.0.jar}"
# The import needs a 6 GB heap; the service runs at 2 GB because that is
# enough once graph-cache/ exists. Running the import at 2 GB thrashes.
IMPORT_HEAP="${IMPORT_HEAP:-6g}"
TIMEOUT_S="${TIMEOUT_S:-900}"
LOG="$(mktemp -t graphhopper-import.XXXXXX.log)"

say() { printf '\n==> %s\n' "$1"; }
die() { printf '\nERROR: %s\n' "$1" >&2; exit 1; }

cd "$GH_DIR" || die "no $GH_DIR"
[ -f "$JAR" ] || die "no $JAR in $GH_DIR"
[ -f config.yml ] || die "no config.yml in $GH_DIR"

say "Config"
grep -nE "custom_model|ignored_highways" config.yml || true
# Every file the profile lists must exist, or the import dies a minute in
# with a FileNotFoundException. Cheaper to catch it now.
for f in $(grep -oE '[A-Za-z0-9_]+\.json' config.yml | sort -u); do
    case "$f" in
        foot.json|car.json|bike.json|hike.json|mtb.json|racingbike.json| \
        truck.json|bus.json|motorcycle.json|cargo_bike.json|curvature.json| \
        avoid_turns.json|foot_elevation.json|bike_elevation.json| \
        bike_tc.json|car4wd.json|car_avoid_private_etc.json| \
        bike_avoid_private_etc.json)
            continue ;;                     # ships inside the jar
    esac
    [ -f "custom_models/$f" ] || die "config.yml lists $f but custom_models/$f is missing"
    printf '    custom_models/%s:\n' "$f"
    sed 's/^/      /' "custom_models/$f"
done

say "Stopping services"
sudo systemctl stop indepensense graphhopper ollama || true

say "Removing the old graph"
rm -rf graph-cache/

say "Importing — about 3 minutes, log: $LOG"
java "-Xmx$IMPORT_HEAP" -Xms2g -jar "$JAR" server config.yml > "$LOG" 2>&1 &
JAVA_PID=$!

# "Started Server@" is the last line of a successful run. Watching for it
# is what replaces the human with a finger on Ctrl-C.
deadline=$(( SECONDS + TIMEOUT_S ))
until grep -q "Started Server@" "$LOG" 2>/dev/null; do
    kill -0 "$JAVA_PID" 2>/dev/null || {
        tail -25 "$LOG" >&2
        die "the import exited before finishing — see above and $LOG"
    }
    [ "$SECONDS" -lt "$deadline" ] || {
        kill "$JAVA_PID" 2>/dev/null || true
        die "import still running after ${TIMEOUT_S}s — see $LOG"
    }
    sleep 3
done

# Shortcut count is the cheap proof the weighting actually changed: a
# different custom model produces a different contraction hierarchy.
grep -oE "new shortcuts: [0-9,]+" "$LOG" | tail -1 || true

say "Import finished, stopping the foreground server"
kill "$JAVA_PID" 2>/dev/null || true
wait "$JAVA_PID" 2>/dev/null || true

say "Starting services"
sudo systemctl start ollama graphhopper indepensense
for _ in $(seq 1 30); do
    curl -fsS localhost:8989/health >/dev/null 2>&1 && break
    sleep 2
done
curl -fsS localhost:8989/health >/dev/null 2>&1 \
    || die "graphhopper did not come back — journalctl -u graphhopper -n 40"

say "Verifying: origin -> the Jollibee 1.3 km away"
curl -s "http://127.0.0.1:8989/route?point=13.937387,121.118698&point=13.92921,121.11071&profile=foot&instructions=true&points_encoded=false" \
  | python3 -c "
import sys, json
p = json.load(sys.stdin)['paths'][0]
print(f\"    {p['distance']/1000:.2f} km, {p['time']/60000:.0f} min, \"
      f\"{len(p['instructions'])} instructions\")
print('    expected roughly 1.44 km / 5 instructions')"

say "Done. Full import log kept at $LOG"
