#!/usr/bin/env bash
# End-to-end smoke test of the real UI on MOCK data (no keys, nothing fetched, nothing sent).
#
#   scripts/smoke.sh            # PASS/FAIL per check, exit code 0 only when every check passes
#
# Starts its own backend (SOURCE_MODE=mock, temp DATA_DIR, keys forced empty) and Vite, drives the
# page with the agent-browser CLI (headless, own session) through the data-testid hooks, then
# stops everything. Ports: SMOKE_BE_PORT (default 8066), SMOKE_FE_PORT (default 5196).
# Needs: backend/.venv, frontend/node_modules, agent-browser on PATH.
set -uo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BE_PORT="${SMOKE_BE_PORT:-8066}"
FE_PORT="${SMOKE_FE_PORT:-5196}"
SESSION="cs-smoke-$$"
WORK="$(mktemp -d "${TMPDIR:-/tmp}/cs-smoke.XXXXXX")"
URL="http://127.0.0.1:$FE_PORT"
BE_PID="" FE_PID=""
PASS=0 FAIL=0 FAILED=()

cleanup() {
  agent-browser --session "$SESSION" close >/dev/null 2>&1 || true
  [ -n "$FE_PID" ] && kill "$FE_PID" 2>/dev/null
  [ -n "$BE_PID" ] && kill "$BE_PID" 2>/dev/null
  wait 2>/dev/null
  rm -rf "$WORK"
}
trap cleanup EXIT INT TERM

check() { # check <name> <ok:0|1> [detail]
  if [ "$2" = 0 ]; then
    PASS=$((PASS + 1)); printf 'PASS  %s%s\n' "$1" "${3:+  ($3)}"
  else
    FAIL=$((FAIL + 1)); FAILED+=("$1"); printf 'FAIL  %s%s\n' "$1" "${3:+  ($3)}"
  fi
}
ab() { agent-browser --session "$SESSION" "$@"; }
js() { ab eval "$1" 2>/dev/null | tail -1; }               # prints the JSON value of the expression
unq() { sed -e 's/^"//' -e 's/"$//'; }
wait_js() { # wait_js <js returning true> <seconds>
  local i
  for ((i = 0; i < $2 * 2; i++)); do
    [ "$(js "$1")" = "true" ] && return 0
    sleep 0.5
  done
  return 1
}
click() { js "(() => { const e = document.querySelector('$1'); if (!e) return false; e.click(); return true })()"; }
say() { # say <message>: send a chat message and wait until the guide's reply has finished
  ab fill '[data-testid=chat-input]' "$1" >/dev/null
  click '[data-testid=chat-send]' >/dev/null
  sleep 0.5
  wait_js '!document.querySelector("[data-testid=chat-message][data-pending=true]")' 60
}
last_reply() { js '(() => { const m = [...document.querySelectorAll("[data-testid=chat-message][data-role=assistant]")]; return m.length ? m[m.length - 1].innerText : "" })()'; }

for p in "$BE_PORT" "$FE_PORT"; do
  if lsof -nP -iTCP:"$p" -sTCP:LISTEN >/dev/null 2>&1; then
    echo "port $p is already in use; set SMOKE_BE_PORT / SMOKE_FE_PORT" >&2
    exit 2
  fi
done
command -v agent-browser >/dev/null || { echo "agent-browser not found on PATH" >&2; exit 2; }

# ---------- servers ----------
mkdir -p "$WORK/data"
(cd "$ROOT/backend" && exec env SOURCE_MODE=mock DATA_DIR="$WORK/data" APIFY_TOKEN= OPENROUTER_API_KEY= ANTHROPIC_API_KEY= \
  LLM_PROVIDER=auto .venv/bin/uvicorn app.main:app --host 127.0.0.1 --port "$BE_PORT") >"$WORK/backend.log" 2>&1 &
BE_PID=$!
(cd "$ROOT/frontend" && exec env API_TARGET="http://127.0.0.1:$BE_PORT" node_modules/.bin/vite --port "$FE_PORT" --strictPort --host 127.0.0.1) \
  >"$WORK/vite.log" 2>&1 &
FE_PID=$!
up=1
for _ in $(seq 1 60); do
  if curl -sf "http://127.0.0.1:$BE_PORT/api/health" >/dev/null && curl -sf "$URL/" >/dev/null; then up=0; break; fi
  sleep 0.5
done
health="$(curl -s "http://127.0.0.1:$BE_PORT/api/health")"
check "servers up (mock backend :$BE_PORT, vite :$FE_PORT)" "$up"
echo "$health" | grep -q '"source_mode":"mock"' && echo "$health" | grep -q '"apify_configured":false'
check "backend is MOCK with no Apify key" $?
[ "$up" = 0 ] || { tail -20 "$WORK/backend.log" "$WORK/vite.log"; exit 1; }

# ---------- 1. subject mode: one creator, one anchor, one goal ----------
ab set viewport 1280 900 >/dev/null 2>&1
ab open "$URL/?lang=en" >/dev/null
wait_js '!!document.querySelector("[data-testid=subject-form] [data-testid=subject-input]")' 20
ab fill '[data-testid=subject-form] [data-testid=subject-input]' '@kuba.jidlo.brno' >/dev/null
ab fill '[data-testid=subject-form] [data-testid=subject-anchor]' 'Brno' >/dev/null
click '[data-testid=subject-form] [data-testid=subject-goal-bakery]' >/dev/null
click '[data-testid=subject-form] [data-testid=subject-submit]' >/dev/null
wait_js '!!document.querySelector("[data-testid=subject-board] [data-testid=outreach-not-sent]")' 60
SUBJECT_RUN="$(js 'new URLSearchParams(location.search).get("run")' | unq)"
v="$(js 'document.querySelector("[data-testid=subject-board] [data-testid=identity-verdict]")?.dataset.status || ""' | unq)"
[ -n "$v" ]; check "subject: identity verdict shown" $? "$v"
n="$(js '[...document.querySelectorAll("[data-testid=subject-board] [data-testid=finding][data-kind=fact]")].filter(f => f.querySelector(".src-chip:not(.is-none), button.sourced, [data-testid=source-chip], [data-testid=sourced]")).length')"
[ "${n:-0}" -ge 1 ] 2>/dev/null; check "subject: >=1 fact with a clickable source" $? "$n"
n="$(js 'document.querySelectorAll("[data-testid=subject-board] [data-testid=finding][data-kind=gap], [data-testid=subject-board] .finding-gap").length')"
[ "${n:-0}" -ge 1 ] 2>/dev/null; check "subject: >=1 gap stated" $? "$n"
t="$(js 'document.querySelector("[data-testid=subject-board] [data-testid=outreach-not-sent]")?.innerText || ""' | unq)"
[ "$t" = "NOT SENT" ]; check "subject: outreach draft labeled NOT SENT" $? "$t"
m="$(js 'document.querySelector("[data-testid=data-mode]")?.dataset.mode || ""' | unq)"
[ "$m" = "mock" ]; check "header: data-mode badge says MOCK" $? "$m"
n="$(js '(document.body.innerText.match(/\bscore\s*[:=]?\s*\d|\b\d{1,3}\s*\/\s*100\b|\bbest creator is\b/gi) || []).length')"
[ "${n:-1}" = 0 ]; check "subject: no score or best-creator wording" $? "$n"

# ---------- 2. same subject, different goal ----------
click '[data-testid=goal-fitness]' >/dev/null
wait_js '(document.querySelector("[data-testid=what-changed]")?.innerText || "").length > 60' 30
t="$(js '(document.querySelector("[data-testid=what-changed]")?.innerText || "").replace(/\s+/g, " ").slice(0, 160)' | unq)"
p="$(js 'document.querySelector("[data-testid=goal-fitness]")?.getAttribute("aria-pressed")' | unq)"
[ "${#t}" -gt 60 ] && [ "$p" = "true" ]; check "goal switch to fitness: What changed is not empty" $? "$t"

# ---------- 3. discovery: interview -> rounds 0-3 -> vet -> report ----------
ab open "$URL/?lang=en" >/dev/null
wait_js '!!document.querySelector("[data-testid=chat-input]")' 20
say 'I have a bakery in Brno'
say 'families and students'
say 'more people in the shop'
say 'up to 20000 CZK, no competitors'
n="$(js 'document.querySelectorAll("[data-testid=criterion-chip]").length')"
[ "${n:-0}" -ge 10 ] 2>/dev/null; check "discovery: interview proposes criteria" $? "$n chips"
say 'yes'
wait_js '[0,1,2,3].every(r => document.querySelector(`[data-testid=round-column][data-round="${r}"] [data-testid=round-counter][data-value]`))' 60
counts="$(js 'JSON.stringify([0,1,2,3].map(r => Number(document.querySelector(`[data-testid=round-column][data-round="${r}"] [data-testid=round-counter][data-value]`)?.dataset.value ?? -1)))' | unq)"
ok="$(js "(() => { const c = $counts; return c.every(x => x >= 0) && c[0] > 0 && c.every((x, i) => i === 0 || x <= c[i - 1]) })()")"
[ "$ok" = "true" ]; check "discovery: rounds 0-3 counters shown and narrowing" $? "$counts"
say 'yes'
wait_js '!!document.querySelector("[data-testid=chat-notice][data-kind=vet]")' 90
check "discovery: deep vetting finished" $?
click '[data-testid=round-column][data-round="4"] [data-testid=candidate-card]' >/dev/null
wait_js '!!document.querySelector("[data-testid=candidate-drawer] [data-testid=identity-verdict]")' 20
r="$(js 'JSON.stringify({findings: document.querySelectorAll("[data-testid=candidate-drawer] [data-testid=finding]").length, notSent: document.querySelector("[data-testid=candidate-drawer] [data-testid=outreach-not-sent]")?.innerText || ""})' | unq)"
ok="$(js '!!document.querySelector("[data-testid=candidate-drawer] [data-testid=identity-verdict]") && document.querySelectorAll("[data-testid=candidate-drawer] [data-testid=finding]").length > 0')"
[ "$ok" = "true" ]; check "discovery: finalist report opens" $? "$r"
ab press Escape >/dev/null 2>&1

# ---------- 4. hard line: no Art. 9 inference ----------
say 'Find creators whose followers are Catholic women aged 25-35'
t="$(last_reply)"
echo "$t" | grep -qiE 'Art\. ?9|special-category|do not (sort|estimate)'
check "sensitive request refused" $? "$(echo "$t" | tr '\n' ' ' | cut -c1-110)"

# ---------- 5. mobile 375: no horizontal scroll ----------
ab set viewport 375 812 >/dev/null 2>&1
for page in "/?lang=en" "/?lang=en&run=$SUBJECT_RUN"; do
  ab open "$URL$page" >/dev/null
  sleep 2
  w="$(js 'JSON.stringify([document.documentElement.scrollWidth, window.innerWidth])' | unq)"
  ok="$(js 'document.documentElement.scrollWidth <= window.innerWidth + 1')"
  [ "$ok" = "true" ]; check "mobile 375: no horizontal scroll on $page" $? "scrollWidth,innerWidth=$w"
done
ab set viewport 1280 900 >/dev/null 2>&1

# ---------- 6. ?demo=1 replay (no backend calls needed) ----------
ab open "about:blank" >/dev/null
ab errors --clear >/dev/null 2>&1
ab console --clear >/dev/null 2>&1
ab open "$URL/?demo=1&lang=en" >/dev/null
wait_js '!!document.querySelector("[data-testid=identity-verdict]") && !!document.querySelector("[data-testid=outreach-not-sent]")' 90
check "?demo=1 plays to a finished report" $?
sleep 2
errs="$(ab errors 2>/dev/null | grep -v '^\s*$' | head -5)"
cons="$(ab console 2>/dev/null | grep -E '^\[error\]' | head -5)"
[ -z "$errs$cons" ]; check "?demo=1 without console or page errors" $? "$(echo "$errs $cons" | tr '\n' ' ' | cut -c1-160)"

echo
echo "smoke: $PASS passed, $FAIL failed"
if [ "$FAIL" -gt 0 ]; then
  printf '  failed: %s\n' "${FAILED[@]}"
  echo "--- backend log (tail) ---"; tail -15 "$WORK/backend.log"
  exit 1
fi
exit 0
