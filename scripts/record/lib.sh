# shellcheck shell=bash
# Helpers for scripts/record-demo.sh: agent-browser wrapper, waits, human-paced typing, shot markers.
# Sourced, not executed. Expects: REC_DIR (this folder), OUT (output run folder), AB_SESSION, APP_URL.

AB=${AB:-agent-browser}
PAGE_JS="$(cat "$REC_DIR/page.js")"

now() { perl -MTime::HiRes=time -e 'printf "%.3f", time'; }
log() { printf '[%s] %s\n' "$(date +%H:%M:%S)" "$*" | tee -a "$OUT/run.log" >&2; }
die() { log "FAIL: $*"; exit 1; }

ab() { "$AB" --session "$AB_SESSION" "$@"; }

# JSON-encode a string for embedding in JS.
jstr() { python3 -c 'import json,sys; print(json.dumps(sys.argv[1]))' "$1"; }

# Run a JS expression in the page with window.__rec available; prints agent-browser's JSON result.
js() { ab eval "$PAGE_JS
$1"; }

# wait_js <timeout_s> <description> <js-boolean-expression>
wait_js() {
  local timeout=$1 desc=$2 expr=$3 start r
  start=$(date +%s)
  while :; do
    r=$(js "!!($expr)" 2>/dev/null || true)
    [[ "$r" == "true" ]] && return 0
    if (( $(date +%s) - start >= timeout )); then
      ab screenshot "$OUT/debug-timeout.png" >/dev/null 2>&1 || true
      die "timed out after ${timeout}s waiting for: $desc (screenshot: $OUT/debug-timeout.png)"
    fi
    sleep 0.25
  done
}

# A spec is a JS object literal for window.__rec.find, e.g. '{testid:"chat-input", css:"textarea"}'.
# target <spec>: marks the element and moves the visible cursor onto it (animated). Fails if missing.
target() {
  local spec=$1 xy
  xy=$(js "JSON.stringify(window.__rec.mark($spec))" | tr -d '"\\')
  [[ "$xy" == "null" || -z "$xy" ]] && return 1
  xy=${xy#[}; xy=${xy%]}
  ab mouse move "${xy%,*}" "${xy#*,}" >/dev/null
  sleep 0.45
}

# click <timeout_s> <description> <spec>
click() {
  wait_js "$1" "$2" "window.__rec.find($3)"
  target "$3" || die "lost element: $2"
  ab click '[data-rec-target="1"]' >/dev/null || die "click failed: $2"
}

# hover <timeout_s> <description> <spec>: optional flourish, never fails the run.
hover() {
  local start r
  start=$(date +%s)
  until [[ "$(js "!!window.__rec.find($3)" 2>/dev/null || true)" == "true" ]]; do
    (( $(date +%s) - start >= $1 )) && { log "warn: nothing to hover: $2"; return 0; }
    sleep 0.25
  done
  target "$3" && ab hover '[data-rec-target="1"]' >/dev/null 2>&1 || log "warn: hover failed: $2"
}

# scroll_to <description> <spec> [block]: smooth scroll inside whatever container holds it.
scroll_to() {
  wait_js 15 "$1" "window.__rec.find($2)"
  js "window.__rec.scrollTo($2, $(jstr "${3:-start}"))" >/dev/null
  sleep 0.9
}

# type_human <text>: types word by word into the focused element (about 6 words a second).
type_human() {
  local words w i=0
  read -r -a words <<<"$1"
  for w in "${words[@]}"; do
    (( i++ > 0 )) && w=" $w"
    ab keyboard type "$w" >/dev/null
  done
}

hold() { sleep "$1"; }

# Chat: type a message into the guide input, send it, wait until the guide has answered.
CHAT_INPUT='{testid:"chat-input", css:"[aria-labelledby=chat-h] form textarea, [aria-labelledby=chat-h] textarea"}'
CHAT_LOG='[role=log]'
chat_count() { js "document.querySelector('$CHAT_LOG') ? document.querySelector('$CHAT_LOG').innerText.length : 0"; }
say() {
  local msg=$1 before
  before=$(chat_count)
  click 20 "chat input" "$CHAT_INPUT"
  type_human "$msg"
  sleep 0.3
  ab press Enter >/dev/null
  wait_js 45 "guide reply to: $msg" \
    "(()=>{const l=document.querySelector('$CHAT_LOG'); return l && l.getAttribute('aria-busy')!=='true' && l.innerText.length > $before + $(( ${#msg} + 20 ))})()"
}

# Shot markers: wall-clock times, converted to video offsets after the segment's recording stops.
SEG=""
mark_shot() { # mark_shot <nn> <slug> <script_seconds> <caption>
  printf '%s\t%s\t%s\t%s\t%s\t%s\n' "$SEG" "$1" "$2" "$(now)" "$3" "$4" >>"$OUT/markers.tsv"
  log "shot $1 $2"
}
frame() { ab screenshot "$OUT/frames/$1.png" >/dev/null || log "warn: screenshot $1 failed"; }

# Recording of one continuous segment (one WebM per segment; shots are cut from it later).
seg_start() { # seg_start <name> <url>
  SEG=$1
  if [[ "$VIDEO" == 1 ]]; then
    if ab record start "$OUT/raw/$SEG.webm" "$2" >/dev/null 2>>"$OUT/run.log"; then
      log "recording $SEG -> raw/$SEG.webm"
    else
      log "warn: video recording failed for $SEG; continuing with frames only"
      VIDEO=0
      ab open "$2" >/dev/null
    fi
  else
    ab open "$2" >/dev/null
  fi
  wait_js 30 "app loaded" "document.querySelector('[aria-labelledby=chat-h]') && document.querySelector('header')"
  js "1" >/dev/null # inject helpers + cursor
}
seg_stop() {
  local t
  t=$(now)
  if [[ "$VIDEO" == 1 && -n "$SEG" ]]; then
    ab record stop >/dev/null 2>>"$OUT/run.log" || log "warn: record stop failed for $SEG"
    printf '%s\n' "$t" >"$OUT/raw/$SEG.stop"
  fi
}
