#!/usr/bin/env bash
# End-to-end check of the digital pit: twins in Ditto, live telemetry, the stand and a what-if scenario.
set -uo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck disable=SC1091
set -a; . "$ROOT/deploy/compose/.env"; set +a
DITTO="http://127.0.0.1:${DITTO_PORT:-8080}"
STAND="http://127.0.0.1:${PIT_PORT:-8099}"
FAILED=0
ok()  { printf '  ok    %s\n' "$1"; }
bad() { printf '  FAIL  %s\n' "$1"; FAILED=1; }
retry() { local n="$1"; shift; for _ in $(seq 1 "$n"); do "$@" >/dev/null 2>&1 && return 0; sleep 3; done; return 1; }
count_twins() { curl -sf -u "ditto:$DITTO_PASSWORD" "$DITTO/api/2/search/things?filter=like(thingId,%22org.openegiz.pit:*%22)&fields=thingId&option=limit(0,200)" | python3 -c 'import sys,json; sys.exit(0 if len(json.load(sys.stdin)["items"])>=34 else 1)'; }
clock() { curl -sf -u "ditto:$DITTO_PASSWORD" "$DITTO/api/2/things/org.openegiz.pit:pit-01/features/clock_min/properties/value"; }
echo "Digital pit"
retry 20 count_twins && ok "34 twins exist in Ditto" || bad "twins missing in Ditto"
c1=$(clock); sleep 6; c2=$(clock)
python3 -c "import sys; sys.exit(0 if float('${c2:-0}')>float('${c1:-0}') else 1)" && ok "simulated clock advances (telemetry flows MQTT -> Ditto)" || bad "twin telemetry is not advancing"
retry 10 curl -sf "$STAND/healthz" && ok "stand answers on $STAND" || bad "stand is not reachable"
retry 5 curl -sf -u "x:y" "$STAND/ditto/api/2/search/things?fields=thingId&option=limit(0,1)" && ok "stand reads twins through the platform" || bad "stand cannot read Ditto"
curl -sf -X POST -H 'Content-Type: application/json' -d '{"cmd":"scenario","name":"rain","on":true}' "$STAND/api/control" >/dev/null && sleep 8 \
  && curl -sf -u "ditto:$DITTO_PASSWORD" "$DITTO/api/2/things/org.openegiz.pit:dispatcher-01/features/sc_rain/properties/value" | grep -q 1 \
  && ok "what-if scenario 'rain' reached the twins" || bad "scenario did not reach the twins"
curl -sf -X POST -H 'Content-Type: application/json' -d '{"cmd":"scenario","name":"rain","on":false}' "$STAND/api/control" >/dev/null
[ "$FAILED" = 0 ] && echo "pit-check: ok" || { echo "pit-check: FAILED"; exit 1; }
