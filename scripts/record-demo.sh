#!/usr/bin/env bash
# Automated, repeatable capture of the demo flow in docs/video-script.md (version A, shots 1-10 + end card),
# so the team has clean 1440x900 footage even if manual screen recording fails.
#
# OUTPUT: /Users/honzik/Developer/creator-scout/demo-output/  (i.e. <repo>/demo-output/, override with --out)
#   NOT for git: add `demo-output/` to .gitignore. Each run writes demo-output/run-YYYYmmdd-HHMMSS/ and
#   points demo-output/latest at it:
#     creator-scout-demo.mp4   all shots at real speed + 4 s end card (H.264, 30 fps, 1440x900)
#     storyboard.mp4           one still per shot at the script's shot durations (88 s; fallback cut)
#     shots/NN-slug.mp4        one clip per shot, real speed, cut from the raw takes
#     frames/NN-slug.png       one 1440x900 still per shot (+ 04b eliminated panel, 06b source popover,
#                              10b header origin counts, 11 end card)
#     subject-run.json         the subject run as served by the API (end card counts and gaps come from it)
#     raw/*.webm               the continuous takes (discovery, subject) as recorded by agent-browser
#     shots.tsv                shot, file, real duration, script duration, script caption
#     run.log, backend.log, frontend.log
#
# What it does: starts its own backend (mock by default, temp DATA_DIR, no API keys, LLM fallback) and
# Vite frontend on free ports in 8080-8089 / 5210-5219, drives a headless Chromium with agent-browser
# (viewport 1440x900, English UI, visible cursor), records two takes (discovery flow, subject flow),
# waits for every UI state instead of sleeping blind, then cuts and assembles with ffmpeg.
#
# Usage:
#   scripts/record-demo.sh                          # working tree frontend/ + backend/, mock data
#   scripts/record-demo.sh --ref subject-frontend   # export frontend from a git ref (e.g. mid-merge tree)
#   scripts/record-demo.sh --frontend-ref A --backend-ref B
#   scripts/record-demo.sh --source cache --cache-dir data/live-run/cache   # replay a cache (real people:
#                                                   #   consent + blur rules in docs/video-script.md apply)
#   scripts/record-demo.sh --headed --no-video --out /tmp/x --keep-servers
#   EXPECT_FUNNEL="48 → 31 → 11 → 5" MOCK_LATENCY=0.4 scripts/record-demo.sh   # warn on other counts; slower funnel
#
# Requires: agent-browser (0.27+), /opt/homebrew/bin/ffmpeg (or ffmpeg on PATH), backend/.venv,
# frontend/node_modules. Runs about 2 minutes.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REC_DIR="$ROOT/scripts/record"
OUT_BASE="$ROOT/demo-output"
FRONTEND_REF="" BACKEND_REF="" SOURCE_MODE="mock" CACHE_DIR="" HEADED=0 VIDEO=1 KEEP=0
SUBJECT="@kuba.jidlo.brno" ANCHOR="Brno"

while (($#)); do
  case "$1" in
    --ref) FRONTEND_REF=$2 BACKEND_REF=$2; shift 2 ;;
    --frontend-ref) FRONTEND_REF=$2; shift 2 ;;
    --backend-ref) BACKEND_REF=$2; shift 2 ;;
    --source) SOURCE_MODE=$2; shift 2 ;;
    --cache-dir) CACHE_DIR=$2; shift 2 ;;
    --subject) SUBJECT=$2; shift 2 ;;
    --anchor) ANCHOR=$2; shift 2 ;;
    --out) OUT_BASE=$2; shift 2 ;;
    --headed) HEADED=1; shift ;;
    --no-video) VIDEO=0; shift ;;
    --keep-servers) KEEP=1; shift ;;
    -h | --help) sed -n '2,33p' "$0"; exit 0 ;;
    *) echo "unknown option: $1 (see --help)" >&2; exit 2 ;;
  esac
done

FFMPEG=${FFMPEG:-$(command -v /opt/homebrew/bin/ffmpeg || command -v ffmpeg || true)}
FFPROBE=${FFPROBE:-$(command -v /opt/homebrew/bin/ffprobe || command -v ffprobe || true)}
command -v agent-browser >/dev/null || { echo "agent-browser not found" >&2; exit 1; }
[[ -n "$FFMPEG" && -n "$FFPROBE" ]] || { echo "ffmpeg/ffprobe not found" >&2; exit 1; }
[[ -x "$ROOT/backend/.venv/bin/uvicorn" ]] || { echo "backend/.venv missing (see README quick start)" >&2; exit 1; }
[[ -d "$ROOT/frontend/node_modules" ]] || { echo "frontend/node_modules missing: cd frontend && npm install" >&2; exit 1; }

STAMP=$(date +%Y%m%d-%H%M%S)
OUT="$OUT_BASE/run-$STAMP"
mkdir -p "$OUT/raw" "$OUT/frames" "$OUT/shots"
: >"$OUT/markers.tsv"
TMP=$(mktemp -d "${TMPDIR:-/tmp}/cs-record.XXXXXX")
AB_SESSION="cs-record-$$"
export REC_DIR OUT AB_SESSION VIDEO
# shellcheck source=record/lib.sh
source "$REC_DIR/lib.sh"

BE_PID="" FE_PID=""
cleanup() {
  local rc=$?
  ab close >/dev/null 2>&1 || true
  if [[ "$KEEP" != 1 ]]; then
    [[ -n "$FE_PID" ]] && kill "$FE_PID" 2>/dev/null || true
    [[ -n "$BE_PID" ]] && kill "$BE_PID" 2>/dev/null || true
    rm -rf "$TMP"
  else
    log "servers kept: backend :$BE_PORT (pid $BE_PID), frontend :$FE_PORT (pid $FE_PID), tmp $TMP"
  fi
  exit $rc
}
trap cleanup EXIT INT TERM

# ---------- source trees ----------
export_ref() { # export_ref <ref> <path...> -> prints the export root
  local ref=$1 dir="$TMP/src-$(echo "$1" | tr -c 'A-Za-z0-9' '_')"; shift
  mkdir -p "$dir"
  git -C "$ROOT" archive "$ref" "$@" | tar -x -C "$dir"
  echo "$dir"
}
has_conflicts() { grep -rlE '^(<<<<<<<|>>>>>>>) ' "$1" --include='*.ts' --include='*.tsx' --include='*.py' --include='*.css' 2>/dev/null | head -1 || true; }

if [[ -n "$FRONTEND_REF" ]]; then
  FE_ROOT=$(export_ref "$FRONTEND_REF" frontend)/frontend
  ln -s "$ROOT/frontend/node_modules" "$FE_ROOT/node_modules"
  cmp -s "$FE_ROOT/package.json" "$ROOT/frontend/package.json" || log "warn: package.json at $FRONTEND_REF differs from frontend/; using frontend/node_modules"
else
  FE_ROOT="$ROOT/frontend"
fi
if [[ -n "$BACKEND_REF" ]]; then
  BE_TOP=$(export_ref "$BACKEND_REF" backend fixtures)
  ln -s "$ROOT/backend/.venv" "$BE_TOP/backend/.venv"
  BE_ROOT="$BE_TOP/backend"
else
  BE_ROOT="$ROOT/backend"
fi
for d in "$FE_ROOT/src" "$BE_ROOT/app"; do
  c=$(has_conflicts "$d")
  [[ -z "$c" ]] || die "merge conflict markers in $c; finish the merge or pass --ref / --frontend-ref <git ref>"
done
log "frontend: ${FRONTEND_REF:-working tree} ($FE_ROOT)"
log "backend:  ${BACKEND_REF:-working tree} ($BE_ROOT), SOURCE_MODE=$SOURCE_MODE"

# ---------- servers ----------
free_port() { local p; for p in $(seq "$1" "$2"); do lsof -nP -iTCP:"$p" -sTCP:LISTEN >/dev/null 2>&1 || { echo "$p"; return; }; done; return 1; }
BE_PORT=$(free_port 8080 8089) || die "no free port in 8080-8089"
FE_PORT=$(free_port 5210 5219) || die "no free port in 5210-5219"
DATA_DIR="$TMP/data"
mkdir -p "$DATA_DIR"

# No keys, ever: empty values also stop python-dotenv from loading them from a local .env.
BE_ENV=(SOURCE_MODE="$SOURCE_MODE" DATA_DIR="$DATA_DIR" LLM_PROVIDER=auto LLM_REQUEST_BUDGET=0
  ANTHROPIC_API_KEY= OPENROUTER_API_KEY= APIFY_TOKEN= ANTHROPIC_BASE_URL= MOCK_LATENCY="${MOCK_LATENCY:-0.15}")
if [[ "$SOURCE_MODE" == cache ]]; then
  [[ -n "$CACHE_DIR" ]] || die "--source cache needs --cache-dir <dir>"
  (cd "$BE_ROOT" && env "${BE_ENV[@]}" .venv/bin/python -m app.sources.cache import "$(cd "$CACHE_DIR" && pwd)") >>"$OUT/backend.log" 2>&1 \
    || die "cache import failed (backend.log)"
fi
(cd "$BE_ROOT" && exec env "${BE_ENV[@]}" .venv/bin/uvicorn app.main:app --host 127.0.0.1 --port "$BE_PORT") >>"$OUT/backend.log" 2>&1 &
BE_PID=$!
(cd "$FE_ROOT" && exec env API_TARGET="http://127.0.0.1:$BE_PORT" node_modules/.bin/vite --host 127.0.0.1 --port "$FE_PORT" --strictPort) >"$OUT/frontend.log" 2>&1 &
FE_PID=$!
for _ in $(seq 1 120); do
  curl -sf "http://127.0.0.1:$BE_PORT/api/health" >/dev/null 2>&1 && curl -sf "http://127.0.0.1:$FE_PORT/" >/dev/null 2>&1 && break
  kill -0 "$BE_PID" 2>/dev/null || die "backend exited (backend.log)"
  kill -0 "$FE_PID" 2>/dev/null || die "frontend exited (frontend.log)"
  sleep 0.5
done
curl -sf "http://127.0.0.1:$FE_PORT/api/health" >"$OUT/health.json" || die "frontend proxy to backend not answering"
log "backend :$BE_PORT, frontend :$FE_PORT, health $(cat "$OUT/health.json")"
APP_URL="http://127.0.0.1:$FE_PORT/?lang=en"

# ---------- browser ----------
open_args=()
[[ "$HEADED" == 1 ]] && open_args+=(--headed)
ab ${open_args[@]+"${open_args[@]}"} open about:blank >/dev/null
ab set viewport 1440 900 >/dev/null
ab set media dark >/dev/null || true
T_START=$(now)

# ===== Take A: discovery (shots 1-4) =====
seg_start A-discovery "$APP_URL"
wait_js 20 "empty guide" "window.__rec.find($CHAT_INPUT)"
hold 1.2

mark_shot 01 goal-in-chat 7 "Czech law: the advertiser shares liability for unlabeled ads (Act 40/1995 Coll., § 6b)"
say "I run a bakery in Brno. I want a local creator to bring more people into the shop."
hold 2.2
frame 01-goal-in-chat

mark_shot 02 criteria 8 "Criteria with reasons. No score."
say "Young families and students in central Brno."
hold 0.6
say "More people in the shop."
hold 0.6
say "Competitors: Pekarna B and Chlebarna Vlnka."
wait_js 20 "criteria chips" "/Round 1/i.test(window.__rec.text({css:'#criteria'}))"
hold 2.5
frame 02-criteria

mark_shot 03 refusal 6 "Refused: special-category data (GDPR Art. 9)"
say "Only religious creators, please."
wait_js 15 "Not checked chip" "/not checked/i.test(window.__rec.text({css:'#criteria'}))"
scroll_to "Not checked chip" '{css:"#criteria"}' end
hold 2.8
frame 03-refusal

mark_shot 04 funnel 12 "MOCK RUN · fictional data · eliminated accounts blurred"
click 10 "Blur eliminated toggle" '{testid:"blur-toggle", text:"Blur eliminated", role:"[role=switch]"}'
wait_js 5 "blur on" "document.querySelector('[role=switch][aria-checked=true]')"
say "Yes, run it."
FUNNEL_RE='/(\d+)\s*→\s*(\d+)\s*→\s*(\d+)\s*→\s*(\d+)/'
wait_js 120 "funnel rounds 0-3 done (Vet N in depth button)" \
  "$FUNNEL_RE.test(window.__rec.text({css:'#funnel'})) && /Vet \\d+ in depth/.test(window.__rec.text({css:'#funnel'}))"
FUNNEL=$(js "(window.__rec.text({css:'#funnel'}).match($FUNNEL_RE)||[''])[0]" | tr -d '"')
log "funnel: $FUNNEL"
[[ -z "${EXPECT_FUNNEL:-}" || "$FUNNEL" == "$EXPECT_FUNNEL" ]] || log "warn: expected funnel '$EXPECT_FUNNEL', got '$FUNNEL'"
scroll_to "funnel counts" '{css:"#funnel"}' start
hold 2.5
frame 04-funnel
click 10 "Show eliminated (round 1)" '{testid:"show-eliminated", text:"Show eliminated", css:"#funnel button"}'
wait_js 10 "eliminated panel" "document.querySelector('#elim-panel')"
hold 0.8
hover 5 "first elimination reason" '{css:"#elim-panel li"}'
hold 3
frame 04b-eliminated-panel
seg_stop

# ===== Take B: subject mode (shots 5-10) =====
seg_start B-subject "$APP_URL"
wait_js 20 "subject form" "window.__rec.find({testid:'subject-input', label:'Creator', exact:true})"
hold 1

mark_shot 05 subject-report 12 "MOCK · subject mode: $SUBJECT + $ANCHOR + goal"
click 10 "Creator field" '{testid:"subject-input", label:"Creator", exact:true}'
type_human "$SUBJECT"
click 10 "Anchor field" '{testid:"anchor-input", label:"Anchor"}'
type_human "$ANCHOR"
click 10 "goal: bakery" '{testid:"goal-bakery", text:"Bakery in Brno", css:"form label, form [role=radio]"}'
click 10 "Research button" '{testid:"subject-submit", text:"Research", css:"form button[type=submit]"}'
wait_js 90 "subject report ready" "document.querySelector('#subj-verdict-h') && document.querySelector('#subj-claims')"
scroll_to "report header" '{css:"#subject"}' start
hold 3
frame 05-subject-report

mark_shot 06 claims-vs-record 10 "Claim vs. record: [STATUS], confidence [LEVEL]"
scroll_to "claims vs record" '{css:"#subj-claims"}' start
hold 2.5
# Still before the click: the source popover covers the status chip.
frame 06-claims-vs-record
CLAIM=$(js "(()=>{const t=window.__rec.text({css:'#subj-claims'});const s=t.match(/(Conflicts with record|Unsupported|Supported|Cannot verify)/i);const c=t.match(/confidence:?\\s*(high|medium|low)/i);return (s?s[1].toLowerCase():'?')+'|'+(c?c[1].toLowerCase():'?')})()" | tr -d '"')
log "first claim: ${CLAIM/|/, confidence }"
click 10 "claim source chip" '{css:"#subj-claims button[aria-expanded]"}'
hold 3
frame 06b-source-popover
ab press Escape >/dev/null || true
hold 0.8

mark_shot 07 goal-switch 11 "Goal switch · recomputed from the same data, no new fetch"
scroll_to "goal switch" '{css:"#subj-goal-h"}' center
hold 0.8
click 10 "Fitness studio goal" '{testid:"goal-fitness", text:"Fitness studio in Brno", exact:true, scope:"#subject"}'
wait_js 30 "What changed panel" "document.querySelector('#what-changed')"
scroll_to "What changed" '{testid:"what-changed", css:"#what-changed"}' start
hold 4.5
frame 07-goal-switch

mark_shot 08 identity 8 "Look-alike set aside · signals shown, no percentage"
scroll_to "identity verdict" '{css:"#subj-verdict-h"}' start
hold 3.5
frame 08-identity

mark_shot 09 outreach-not-sent 5 "NOT SENT · the app has no send function"
scroll_to "outreach draft" '{css:"#subj-outreach"}' start
wait_js 10 "NOT SENT badge" "/NOT SENT/.test(window.__rec.text({css:'#subj-outreach'}))"
hover 5 "Copy button" '{testid:"outreach-copy", text:"Copy", scope:"#subj-outreach"}'
hold 3
frame 09-outreach-not-sent

mark_shot 10 honest-close 5 "Live [N] · Cache [N] · Mock [N] · Not checked: audience age, gender and origin · Gap: Meta Branded Content"
scroll_to "What we did not check" '{text:"What we did not check", css:"#subj-method h3, #subject h3"}' start
hold 2.5
frame 10-honest-close
# The app's own origin counts (header status tooltip "By origin"), so the end card numbers are on screen too.
hover 5 "header origin counts" '{css:"button.status-pill"}'
hold 2.5
frame 10b-origin-counts
RUN_ID=$(js "new URLSearchParams(location.search).get('run') || ''" | tr -d '"')
[[ -n "$RUN_ID" ]] || RUN_ID=$(ls -t "$DATA_DIR/runs" 2>/dev/null | head -1 | sed 's/\.json$//')
seg_stop
log "browser part done in $(python3 -c "print(round($(now)-$T_START))") s; subject run ${RUN_ID:-unknown}"

# ===== End card (still) =====
curl -sf "http://127.0.0.1:$BE_PORT/api/runs/$RUN_ID" >"$OUT/subject-run.json" 2>/dev/null || : >"$OUT/subject-run.json"
# Counts = the run's mode_summary (fetched objects by origin, as in the header tooltip). The Meta gap line
# only when the run really has the gap finding g:meta_branded (MOCK data includes Meta records, so no gap).
# Also fills the [STATUS] / [LEVEL] / [N] placeholders in the shot captions (markers.tsv -> shots.tsv).
IFS=$'\t' read -r COUNTS GAPS < <(python3 - "$OUT/subject-run.json" "$OUT/markers.tsv" "${CLAIM:-?|?}" <<'PY'
import json, sys
run_path, markers, claim = sys.argv[1:4]
try:
    run = json.load(open(run_path, encoding="utf-8"))
except Exception:
    run = {}
m = run.get("mode_summary") or {}
counts = "Live %s · Cache %s · Mock %s" % (m.get("live", "?"), m.get("cache", "?"), m.get("mock", "?"))
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
if "g:meta_branded" in set(ids(run)):
    gaps += " · Gap: Meta Branded Content"
status, _, level = claim.partition("|")
t = open(markers, encoding="utf-8").read()
t = t.replace("[STATUS]", status or "?").replace("[LEVEL]", level or "?")
t = t.replace("Live [N] · Cache [N] · Mock [N] · Not checked: audience age, gender and origin · Gap: Meta Branded Content",
              counts + " · " + gaps)
open(markers, "w", encoding="utf-8").write(t)
print(counts + "\t" + gaps)
PY
) || true
[[ -n "$COUNTS" ]] || COUNTS="Live ? · Cache ? · Mock ?"
[[ -n "${GAPS:-}" ]] || GAPS="Not checked: audience age, gender and origin"
NOTE=""
[[ "$SOURCE_MODE" == mock ]] && NOTE="Recorded on MOCK data: fictional creators, no real accounts."
python3 - "$REC_DIR/endcard.html" "$OUT/endcard.html" "$COUNTS" "$NOTE" "$GAPS" <<'PY'
import html, sys
src, dst, counts, note, gaps = sys.argv[1:6]
t = open(src, encoding="utf-8").read()
t = t.replace("{{COUNTS}}", html.escape(counts)).replace("{{NOTE}}", html.escape(note)).replace("{{GAPS}}", html.escape(gaps))
open(dst, "w", encoding="utf-8").write(t)
PY
ab open "file://$OUT/endcard.html" >/dev/null
ab wait 400 >/dev/null
frame 11-end-card
log "end card: $COUNTS"

# ===== Cut and assemble =====
python3 "$REC_DIR/assemble.py" "$OUT" "$FFMPEG" "$FFPROBE" "$VIDEO" | tee -a "$OUT/run.log"
ln -sfn "run-$STAMP" "$OUT_BASE/latest"
log "done in $(python3 -c "print(round($(now)-$T_START))") s -> $OUT"
