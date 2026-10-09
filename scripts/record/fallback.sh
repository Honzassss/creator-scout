#!/usr/bin/env bash
# Fallback demo footage (80-90 s): real @kamvbrne report replayed from cache + a short MOCK funnel.
# Order: chat opener, refused sensitive request, subject form (@kamvbrne, Brno, Bakery in Brno, two real
# competitors), identity verdict, not-met competitor check with its sources, collaborations
# FACT / INFERENCE / GAP rows with confidence, goal switch to fitness + "What changed", outreach NOT SENT,
# MOCK discovery funnel (separate mock backend) with elimination reasons, end card.
#
# OUTPUT: <repo>/demo-output/fallback/ (gitignored; a previous one moves to demo-output/fallback-prev-STAMP/)
#   creator-scout-fallback.mp4   assembled, real speed, 1440x900, 30 fps
#   raw/*.webm                   continuous takes: A-chat (cache), B-subject (cache), C-funnel (mock)
#   shots/NN-slug.mp4, shots.tsv one clip per shot; frames/NN-slug.png one still per shot
#   frames/1s/t_NNN.png          one frame per second of the assembled MP4 (for review)
#   run.log, backend-*.log, frontend-*.log, subject-run.json
#
# Usage: scripts/record/fallback.sh [--ref <git ref>|--worktree] [--live-subject data/live-subject] [--out DIR]
#   Default source is HEAD exported with git archive (uncommitted edits by others cannot break a take).
#   Backends: keys forced EMPTY (APIFY_TOKEN= OPENROUTER_API_KEY= ANTHROPIC_API_KEY=), ports 8080-8089 /
#   5210-5219, cache backend reads a temp copy of <live-subject>/{cache,snapshots}.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
REC_DIR="$ROOT/scripts/record"
REF="HEAD" LIVE="$ROOT/data/live-subject" OUT="$ROOT/demo-output/fallback" HEADED=0
while (($#)); do
  case "$1" in
    --ref) REF=$2; shift 2 ;;
    --worktree) REF=""; shift ;;
    --live-subject) LIVE=$2; shift 2 ;;
    --out) OUT=$2; shift 2 ;;
    --headed) HEADED=1; shift ;;
    -h | --help) sed -n '2,19p' "$0"; exit 0 ;;
    *) echo "unknown option: $1" >&2; exit 2 ;;
  esac
done

FFMPEG=${FFMPEG:-$(command -v /opt/homebrew/bin/ffmpeg || command -v ffmpeg)}
FFPROBE=${FFPROBE:-$(command -v /opt/homebrew/bin/ffprobe || command -v ffprobe)}
[[ -d "$LIVE/cache" && -d "$LIVE/snapshots" ]] || { echo "no cache replay in $LIVE" >&2; exit 1; }

STAMP=$(date +%Y%m%d-%H%M%S)
if [[ -d "$OUT" && -n "$(ls -A "$OUT" 2>/dev/null)" ]]; then mv "$OUT" "$OUT-prev-$STAMP"; fi
mkdir -p "$OUT/raw" "$OUT/frames/1s" "$OUT/shots"
: >"$OUT/markers.tsv"
TMP=$(mktemp -d "${TMPDIR:-/tmp}/cs-fallback.XXXXXX")
AB_SESSION="cs-fallback-$$" VIDEO=1
export REC_DIR OUT AB_SESSION VIDEO
# shellcheck source=lib.sh
source "$REC_DIR/lib.sh"
# Recording cursor: visible while it moves to a target, fades out during holds of 1.5 s or more, so the
# ring never sits on top of text in the held frames (take 1 had it over the chat input and the report).
cur() { js "(()=>{const c=document.getElementById('__rec_cursor');if(!c)return 0;c.style.transition='left .38s cubic-bezier(.3,.7,.4,1),top .38s cubic-bezier(.3,.7,.4,1),opacity .25s';c.style.opacity='$1';return 1})()" >/dev/null || true; }
# target: the ring fades in only once the move starts (no flash at its old spot, which after a scroll can
# sit on report text: take v1 had it on "✓ met" in What changed and on the Checks column).
target() {
  local xy
  xy=$(js "JSON.stringify(window.__rec.mark($1))" | tr -d '"\\')
  [[ "$xy" == "null" || -z "$xy" ]] && return 1
  xy=${xy#[}; xy=${xy%]}
  js "(()=>{const c=document.getElementById('__rec_cursor');if(c){c.style.opacity='1';c.style.left='${xy%,*}px';c.style.top='${xy#*,}px'}return 1})()" >/dev/null || true
  ab mouse move "${xy%,*}" "${xy#*,}" >/dev/null
  sleep 0.45
}
hold() { awk "BEGIN{exit !($1 >= 1.5)}" && cur 0; sleep "$1"; }
# typing: ring hidden, so it never sits on the text being typed (v1: chat question, competitors field)
eval "$(declare -f type_human | sed '1s/^type_human/_lib_type_human/')"
type_human() { cur 0; _lib_type_human "$@"; }
# point <timeout_s> <description> <spec>: ring in the left gutter of a text block, beside it, not on it
# (v1 hovered the element centre: the ring sat on "account" in the identity heading and on Finding 14).
point() {
  local start xy
  start=$(date +%s)
  until [[ "$(js "!!window.__rec.find($3)" 2>/dev/null || true)" == "true" ]]; do
    (( $(date +%s) - start >= $1 )) && { log "warn: nothing to point at: $2"; return 0; }
    sleep 0.25
  done
  xy=$(js "(()=>{const r=window.__rec.find($3).getBoundingClientRect();return Math.max(12,Math.round(r.left-16))+','+Math.round(r.top+Math.min(r.height/2,12))})()" | tr -d '"')
  js "(()=>{const c=document.getElementById('__rec_cursor');if(c){c.style.opacity='1';c.style.left='${xy%,*}px';c.style.top='${xy#*,}px'}return 1})()" >/dev/null || true
  ab mouse move "${xy%,*}" "${xy#*,}" >/dev/null
  sleep 0.45
}

PIDS=()
cleanup() {
  local rc=$?
  ab close >/dev/null 2>&1 || true
  for p in ${PIDS[@]+"${PIDS[@]}"}; do kill "$p" 2>/dev/null || true; done
  rm -rf "$TMP"
  exit $rc
}
trap cleanup EXIT INT TERM

# ---------- source tree ----------
if [[ -n "$REF" ]]; then
  SRC="$TMP/src"; mkdir -p "$SRC"
  git -C "$ROOT" archive "$REF" backend fixtures frontend | tar -x -C "$SRC"
  ln -s "$ROOT/backend/.venv" "$SRC/backend/.venv"
  ln -s "$ROOT/frontend/node_modules" "$SRC/frontend/node_modules"
  log "source: $REF ($(git -C "$ROOT" rev-parse --short "$REF"))"
else
  SRC="$ROOT"; log "source: working tree"
fi

# ---------- servers: cache (real replay) and mock ----------
free_port() { local p; for p in $(seq "$1" "$2"); do
  [[ " ${TAKEN:-} " == *" $p "* ]] && continue
  lsof -nP -iTCP:"$p" -sTCP:LISTEN >/dev/null 2>&1 || { echo "$p"; return; }; done; return 1; }
start_pair() { # start_pair <name> <source_mode> <data_dir> <VAR> -> sets <VAR>_URL, <VAR>_BE
  local name=$1 mode=$2 data=$3 be fe bp fp
  be=$(free_port 8080 8089) || die "no free port in 8080-8089"; TAKEN="${TAKEN:-} $be"
  fe=$(free_port 5210 5219) || die "no free port in 5210-5219"; TAKEN="$TAKEN $fe"
  (cd "$SRC/backend" && exec env SOURCE_MODE="$mode" DATA_DIR="$data" LLM_PROVIDER=auto LLM_REQUEST_BUDGET=0 \
    APIFY_TOKEN= OPENROUTER_API_KEY= ANTHROPIC_API_KEY= ANTHROPIC_BASE_URL= MOCK_LATENCY="${MOCK_LATENCY:-0.3}" \
    .venv/bin/uvicorn app.main:app --host 127.0.0.1 --port "$be") >>"$OUT/backend-$name.log" 2>&1 &
  bp=$!; PIDS+=("$bp")
  (cd "$SRC/frontend" && exec env API_TARGET="http://127.0.0.1:$be" node_modules/.bin/vite --host 127.0.0.1 \
    --port "$fe" --strictPort) >"$OUT/frontend-$name.log" 2>&1 &
  fp=$!; PIDS+=("$fp")
  for _ in $(seq 1 120); do
    curl -sf "http://127.0.0.1:$fe/api/health" >/dev/null 2>&1 && break
    kill -0 "$bp" 2>/dev/null || die "$name backend exited (backend-$name.log)"
    kill -0 "$fp" 2>/dev/null || die "$name frontend exited (frontend-$name.log)"
    sleep 0.5
  done
  curl -sf "http://127.0.0.1:$fe/api/health" >"$OUT/health-$name.json" || die "$name: no health"
  log "$name: backend :$be, frontend :$fe, $(cut -c1-80 "$OUT/health-$name.json")"
  printf -v "$4_URL" '%s' "http://127.0.0.1:$fe/?lang=en"
  printf -v "$4_BE" '%s' "http://127.0.0.1:$be"
}
CACHE_DATA="$TMP/cache-data"; mkdir -p "$CACHE_DATA" "$TMP/mock-data"
cp -R "$LIVE/cache" "$LIVE/snapshots" "$CACHE_DATA"/
start_pair cache cache "$CACHE_DATA" CACHE
start_pair mock mock "$TMP/mock-data" MOCK
grep -q '"source_mode":"cache"' "$OUT/health-cache.json" || die "cache backend is not in cache mode"
grep -q '"apify_configured":false' "$OUT/health-cache.json" || die "cache backend sees an Apify token"

# ---------- browser ----------
open_args=(); [[ "$HEADED" == 1 ]] && open_args+=(--headed)
ab ${open_args[@]+"${open_args[@]}"} open about:blank >/dev/null
ab set viewport 1440 900 >/dev/null
T_START=$(now)
# scroll the chat log so the element whose text starts with <prefix> is at the top of the log
chat_scroll_to() { js "(()=>{const l=document.querySelector('[role=log]');const els=[...l.querySelectorAll('*')].filter(e=>window.__rec.norm(e.innerText).startsWith($(jstr "$1")));const el=els[els.length-1];if(el)el.scrollIntoView({behavior:'smooth',block:'start'});return !!el})()" >/dev/null; sleep 0.9; }

# ===== Take A: chat, cached backend =====
seg_start A-chat "$CACHE_URL"
wait_js 20 "empty guide" "window.__rec.find($CHAT_INPUT)"
wait_js 10 "CACHED banner" "/CACHED/.test(window.__rec.text({css:'body'}).slice(0,200))"
hold 0.8
mark_shot 01 chat-opener 8 "CACHED · the guide explains what it checks and leaves out"
say "What do you check, and what do you leave out?"
chat_scroll_to "We check public data only"
hold 3.2
frame 01-chat-opener
js "document.querySelector('[role=log]').scrollTo({top:1e6,behavior:'smooth'})" >/dev/null
hold 1.2

mark_shot 02 refusal 6 "Refused: special-category data (GDPR Art. 9)"
say "Only religious creators, please."
hold 3.2
frame 02-refusal
seg_stop

# ===== Take B: subject report, cached backend =====
seg_start B-subject "$CACHE_URL"
wait_js 20 "subject form" "window.__rec.find({label:'Creator', exact:true})"
hold 0.6
mark_shot 03 subject-form 10 "CACHED · subject: @kamvbrne + Brno + Bakery in Brno + 2 competitors"
click 10 "Creator field" '{label:"Creator", exact:true}'
type_human "@kamvbrne"
click 10 "Anchor field" '{label:"Anchor"}'
type_human "Brno"
click 10 "goal: bakery" '{text:"Bakery in Brno", css:"form label"}'
click 10 "Competitors field" '{label:"Competitors"}'
type_human "William Thomas Bakery @william_thomas_bakery, SORRY pečeme jinak @sorrypecemejinak"
hold 0.6
frame 03-subject-form
click 10 "Research button" '{text:"Research", css:"form button[type=submit]"}'
wait_js 60 "subject report ready" "document.querySelector('#subject') && /Is this the account you mean/.test(window.__rec.text({css:'#subject'})) && document.querySelector('#checks-h')"

mark_shot 04 identity 5 "Identity: LIKELY, signals with sources; 10 unrelated news results set aside"
hold 0.6
point 5 "LIKELY verdict" '{text:"Is this the account you mean?", css:"#subject h3, #subject h2"}'
hold 3.4
frame 04-identity

mark_shot 05 competitor-check 9 "Check not met: worked with @sorrypecemejinak and @william_thomas_bakery, 3 sources"
scroll_to "competitor check" '{text:"No competitor collaboration", css:"li.check-row"}' center
hover 5 "competitor check" '{text:"No competitor collaboration", css:"li.check-row"}'
hold 2.8
frame 05-competitor-check
click 10 "check sources" '{css:"li.check-row[id*=no_competitor] button[aria-expanded]"}'
hold 3.4
frame 05b-check-sources
ab press Escape >/dev/null || true
hold 0.5

mark_shot 06 fact-inference-gap 8 "Collaborations: FACT (high), INFERENCE (medium), GAP, each with its basis"
scroll_to "Finding 15" '{text:"Finding 15", css:"li.finding"}' center
point 5 "Finding 14" '{text:"Finding 14", css:"li.finding"}'
hold 4.8
frame 06-fact-inference-gap

mark_shot 07 goal-switch 10 "Goal switch · from the same data, no new fetch, no LLM"
scroll_to "goal switch" '{css:"#subj-goal-h"}' center
hold 0.6
click 10 "Fitness studio goal" '{text:"Fitness studio in Brno", exact:true, scope:"#subject"}'
cur 0 # the panel scrolls in under the click spot
wait_js 30 "What changed panel" "document.querySelector('#what-changed')"
scroll_to "What changed" '{css:"#what-changed"}' start
hold 4.6
frame 07-goal-switch

mark_shot 08 outreach-not-sent 5 "NOT SENT · the app has no send function"
scroll_to "outreach draft" '{css:"#subj-outreach"}' start
wait_js 10 "NOT SENT badge" "/NOT SENT/.test(window.__rec.text({css:'#subj-outreach'}))"
hover 5 "Copy button" '{text:"Copy", scope:"#subj-outreach"}'
hold 3
frame 08-outreach-not-sent
RUN_ID=$(js "new URLSearchParams(location.search).get('run') || ''" | tr -d '"')
seg_stop

# ===== Take C: discovery funnel, MOCK backend =====
seg_start C-funnel "$MOCK_URL"
wait_js 20 "empty guide" "window.__rec.find($CHAT_INPUT)"
wait_js 10 "MOCK banner" "/MOCK/.test(window.__rec.text({css:'body'}).slice(0,200))"
# interview (cut from the video: the shot starts at "Yes, run it.")
say "I run a bakery in Brno. I want a local creator to bring more people into the shop."
say "Young families and students in central Brno."
say "More people in the shop."
say "Competitors: Pekarna B and Chlebarna Vlnka."
wait_js 20 "criteria chips" "/Round 1/i.test(window.__rec.text({css:'#criteria'}))"
click 10 "Blur eliminated toggle" '{testid:"blur-toggle", text:"Blur eliminated", role:"[role=switch]"}'
wait_js 5 "blur on" "document.querySelector('[role=switch][aria-checked=true]')"
cur 0 # not on the "Blur eliminated" label when the shot starts
hold 0.6
mark_shot 09 mock-funnel 14 "MOCK · fictional creators · rounds 48 → 31 → 11 → 5, every cut with a reason"
say "Yes, run it."
FUNNEL_RE='/(\d+)\s*→\s*(\d+)\s*→\s*(\d+)\s*→\s*(\d+)/'
wait_js 120 "funnel done" "$FUNNEL_RE.test(window.__rec.text({css:'#funnel'})) && /Vet \\d+ in depth/.test(window.__rec.text({css:'#funnel'}))"
FUNNEL=$(js "(window.__rec.text({css:'#funnel'}).match($FUNNEL_RE)||[''])[0]" | tr -d '"')
log "funnel: $FUNNEL"
[[ "$FUNNEL" == "48 → 31 → 11 → 5" ]] || log "warn: expected funnel 48 → 31 → 11 → 5, got '$FUNNEL'"
scroll_to "funnel counts" '{css:"#funnel"}' start
hold 2.6
frame 09-mock-funnel
click 10 "Show eliminated (round 1)" '{testid:"show-eliminated", text:"Show eliminated", css:"#funnel button"}'
wait_js 10 "eliminated panel" "document.querySelector('#elim-panel')"
hold 0.6
hover 5 "first elimination source" '{css:"#elim-panel li button, #elim-panel li a"}'
hold 3.2
frame 09b-eliminated-reasons
seg_stop
log "browser part done in $(python3 -c "print(round($(now)-$T_START))") s; subject run ${RUN_ID:-unknown}"

# ===== End card =====
[[ -n "$RUN_ID" ]] || RUN_ID=$(ls -t "$CACHE_DATA/runs" 2>/dev/null | head -1 | sed 's/\.json$//')
curl -sf "$CACHE_BE/api/runs/$RUN_ID" >"$OUT/subject-run.json" 2>/dev/null || : >"$OUT/subject-run.json"
IFS=$'\t' read -r COUNTS GAPS < <(python3 - "$OUT/subject-run.json" <<'PY'
import json, sys
try:
    run = json.load(open(sys.argv[1], encoding="utf-8"))
except Exception:
    run = {}
m = run.get("mode_summary") or {}
def ids(o):
    if isinstance(o, dict):
        if isinstance(o.get("id"), str):
            yield o["id"]
        for v in o.values():
            yield from ids(v)
    elif isinstance(o, list):
        for v in o:
            yield from ids(v)
gaps = "Not checked: audience age, gender and origin"
if "g:meta_branded" in set(ids(run)) or "Meta's branded content library" in json.dumps(run):
    gaps += " · Gap: Meta Branded Content"
print("Live %s · Cache %s · Mock %s\t%s" % (m.get("live", "?"), m.get("cache", "?"), m.get("mock", "?"), gaps))
PY
) || true
NOTE="Report: cached replay of real public data, fetched 9 Oct 2026. Funnel: MOCK, fictional creators."
python3 - "$REC_DIR/endcard.html" "$OUT/endcard.html" "${COUNTS:-Live ? · Cache ? · Mock ?}" "$NOTE" "${GAPS:-}" <<'PY'
import html, sys
src, dst, counts, note, gaps = sys.argv[1:6]
t = open(src, encoding="utf-8").read()
t = t.replace("{{COUNTS}}", html.escape(counts)).replace("{{NOTE}}", html.escape(note)).replace("{{GAPS}}", html.escape(gaps))
t = t.replace("Fetched objects by origin (subject run)", "Fetched objects by origin (@kamvbrne report)")
open(dst, "w", encoding="utf-8").write(t)
PY
ab open "file://$OUT/endcard.html" >/dev/null
ab wait 400 >/dev/null
frame 11-end-card
log "end card: ${COUNTS:-?} / ${GAPS:-?}"

# ===== Assemble + review frames =====
python3 "$REC_DIR/assemble.py" "$OUT" "$FFMPEG" "$FFPROBE" 1 | tee -a "$OUT/run.log"
[[ -f "$OUT/creator-scout-demo.mp4" ]] && mv "$OUT/creator-scout-demo.mp4" "$OUT/creator-scout-fallback.mp4"
rm -f "$OUT/storyboard.mp4"
"$FFMPEG" -v error -y -i "$OUT/creator-scout-fallback.mp4" -vf fps=1 "$OUT/frames/1s/t_%03d.png"
log "done in $(python3 -c "print(round($(now)-$T_START))") s -> $OUT/creator-scout-fallback.mp4"
