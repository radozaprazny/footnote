#!/usr/bin/env bash
# Build the image and smoke-test it as Azure Container Apps runs it: linux/amd64, 0.25 vCPU,
# 512 MB. Prints the image size, the cold start to /healthz, to /readyz and to each match's first
# /live message, the server's memory, and how long `docker stop` takes with a stream open, during
# the cold start and during the warm-up; exits 1 if any of them fails.
# Usage: scripts/container.sh [tag]  (default tag: the short git sha, with
# -dirty if the tree has changes; PORT on 127.0.0.1, default 8765; CPUS and MEMORY as
# `docker run`, default 0.25 and 512m)
set -euo pipefail
cd "$(dirname "$0")/.."
sha=$(git rev-parse --short HEAD)
[ -z "$(git status --porcelain)" ] || sha="$sha-dirty"
image="matchlens:${1:-$sha}"
port="${PORT:-8765}"
cpus="${CPUS:-0.25}"
memory="${MEMORY:-512m}"
base="http://127.0.0.1:$port"
name="matchlens-smoke-$$"
matches=(m0 m1 m3)
ready_limit_s=240 # every match streams within the readiness window planned for ACA (M6 item 3)
graceful_s=20     # GRACEFUL_TIMEOUT_S: what an open stream gets after SIGTERM
stop_limit_s=30   # ACA sends SIGKILL 30 s after SIGTERM
early_stop_s=5    # before the server is ready there is nothing to close (locally under 0.3 s)

now() { date +%s.%N; }
since() { awk -v a="$1" -v b="$(now)" 'BEGIN { printf "%.2f", b - a }'; }
left() { awk -v s="$(since "$t0")" -v l="$ready_limit_s" 'BEGIN { r = l - s; print (r > 1 ? r : 1) }'; }
fail() {
  echo "FAIL: $*" >&2
  docker logs --tail 20 "$name" >&2 || true
  exit 1
}

docker build --platform linux/amd64 -t "$image" .
# with Docker's containerd image store (the default since 29) `.Size` is the compressed content
docker image inspect -f '{{.Size}}' "$image" | awk -v i="$image" -v d="$(
  docker image ls --format '{{.Size}}' "$image"
)" '{ printf "image %s: %.1f MB content (docker image inspect), %s on disk\n", i, $1 / 1e6, d }'

tmp=$(mktemp -d)
cleanup() {
  kill "${poller:-}" 2>/dev/null || true
  docker rm -f "$name" >/dev/null 2>&1 || true
  rm -rf "$tmp"
}
trap cleanup EXIT
echo "limits: $cpus CPUs, $memory"
t0=$(now)
docker run -d --name "$name" --platform linux/amd64 --cpus "$cpus" --memory "$memory" \
  -p "127.0.0.1:$port:8000" "$image" >/dev/null
until curl -sf --max-time 2 -o /dev/null "$base/healthz"; do
  [ "$(docker inspect -f '{{.State.Running}}' "$name")" = true ] || fail "the container stopped"
  awk -v s="$(since "$t0")" -v l="$ready_limit_s" 'BEGIN { exit !(s > l) }' &&
    fail "no /healthz after $ready_limit_s s"
  sleep 0.1
done
echo "cold start to /healthz: $(since "$t0") s"
# every match of the image has its run, and since M5 the runs' replay check computes each
# match's overlay before the bind: the server is ready as soon as it listens
ready=$(curl -s --max-time 10 -o /dev/null -w '%{http_code}' "$base/readyz") || true
[ "$ready" = 200 ] || fail "/readyz answered $ready at /healthz, after every overlay was computed"
# readiness polled each second in the background while the /live requests below wait; each
# probe's time goes to probes.txt (an ACA probe's timeout must exceed it, item 3)
for _ in $(seq "$ready_limit_s"); do
  answer=$(curl -s --max-time 5 -o /dev/null -w '%{http_code} %{time_total}' "$base/readyz") || true
  echo "${answer#* }" >>"$tmp/probes.txt"
  [ "${answer%% *}" = 200 ] && since "$t0" >"$tmp/ready" && break
  sleep 1
done &
poller=$!
uid=$(docker exec "$name" awk '/^Uid:/ { print $2 }' /proc/1/status)
[ "$uid" = 10001 ] || fail "PID 1 runs as uid $uid, not 10001"
echo "PID 1: $(docker exec "$name" cat /proc/1/comm), uid $uid"
served=$(curl -sf --max-time 10 "$base/matches") || fail "no /matches"
for m in "${matches[@]}"; do
  [[ "$served" == *"\"match_id\":\"$m\""* ]] || fail "/matches does not list $m: $served"
done
echo "matches: $served"

for m in "${matches[@]}"; do
  t=$(now)
  # the first data line at 1x; the stream answers once the match's cue timeline is ready
  first=$(curl -sN --max-time "$(left)" "$base/matches/$m/live" | grep -m1 '^data: ') || true
  [ -n "$first" ] || fail "no /live message for $m within $ready_limit_s s of the start"
  echo "$m: first /live message after $(since "$t") s ($(since "$t0") s after start): ${first:0:80}"
done
wait "$poller" || true
poller= # reaped: its pid may be reused
[ -s "$tmp/ready" ] || fail "no /readyz 200 while polling"
awk -v r="$(cat "$tmp/ready")" -v l="$ready_limit_s" 'BEGIN { exit !(r <= l) }' ||
  fail "/readyz 200 only at $(cat "$tmp/ready") s, after $ready_limit_s s"
echo "cold start to /readyz 200: $(cat "$tmp/ready") s (polled each second)"
sort -n "$tmp/probes.txt" | awk '{ t[NR] = $1 } END {
  printf "/readyz polled until 200: %d probes, median %.3f s, max %.3f s\n",
    NR, t[int((NR + 1) / 2)], t[NR] }'
replays=$(docker logs "$name" 2>&1 | grep 'narratives from the run') || fail "no run was replayed"
echo "$replays"
[ "$(grep -c ', 0 refused at replay$' <<<"$replays")" = "${#matches[@]}" ] ||
  fail "not every run replayed with 0 narratives refused"
docker exec "$name" grep -E '^Vm(RSS|HWM)' /proc/1/status | tr -s ' \t' ' ' | paste -sd ',' |
  sed 's/^/server memory: /'

curl -sN "$base/matches/m0/live" >"$tmp/stream" 2>/dev/null &
stream=$!
for _ in $(seq 100); do
  grep -q '^data: ' "$tmp/stream" && break
  sleep 0.1
done
grep -q '^data: ' "$tmp/stream" || fail "the stream to hold open during the stop did not start"
t=$(now)
docker stop -t "$stop_limit_s" "$name" >/dev/null
took=$(since "$t")
code=$(docker inspect -f '{{.State.ExitCode}}' "$name")
wait "$stream" || true
echo "docker stop with a stream open: $took s, exit code $code"
# 143: `matchlens serve` exits through its SIGTERM handler, which uvicorn raises again after
# the graceful shutdown (137: killed)
[ "$code" = 143 ] || fail "exit code $code after SIGTERM, not 143"
awk -v t="$took" -v g="$graceful_s" -v l="$stop_limit_s" 'BEGIN { exit !(t >= g - 1 && t < l) }' ||
  fail "the stop took $took s: the open stream should get the graceful ${graceful_s} s"

# a stop before the server is ready: during the cold start (once the first run's replay check is
# logged, after match generation, while the other overlays compute) and during the warm-up (at
# /healthz; since M5 nothing computes then, as every overlay is ready before the bind)
reached() {
  if [ "$1" = "cold start" ]; then
    docker logs "$name" 2>&1 | grep 'narratives from the run' >/dev/null # no -q: no SIGPIPE
  else
    curl -sf --max-time 2 -o /dev/null "$base/healthz"
  fi
}
for phase in "cold start" "warm-up"; do
  docker rm -f "$name" >/dev/null
  t0=$(now)
  docker run -d --name "$name" --platform linux/amd64 --cpus "$cpus" --memory "$memory" \
    -p "127.0.0.1:$port:8000" "$image" >/dev/null
  until reached "$phase"; do
    [ "$(docker inspect -f '{{.State.Running}}' "$name")" = true ] || fail "the container stopped"
    awk -v s="$(since "$t0")" -v l="$ready_limit_s" 'BEGIN { exit !(s > l) }' &&
      fail "the $phase did not reach its stop point within $ready_limit_s s"
    sleep 0.1
  done
  at=$(since "$t0")
  if [ "$phase" = "cold start" ] && curl -sf --max-time 1 -o /dev/null "$base/healthz"; then
    echo "note: /healthz already answers, so this stop falls in the warm-up"
  fi
  t=$(now)
  docker stop -t "$stop_limit_s" "$name" >/dev/null
  took=$(since "$t")
  code=$(docker inspect -f '{{.State.ExitCode}}' "$name")
  echo "docker stop during the $phase ($at s after the start): $took s, exit code $code"
  [ "$code" = 143 ] || fail "exit code $code after SIGTERM during the $phase, not 143"
  awk -v t="$took" -v l="$early_stop_s" 'BEGIN { exit !(t < l) }' ||
    fail "the stop during the $phase took $took s, not under $early_stop_s s"
done
