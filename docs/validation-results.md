# Validation results, 9 October 2026, about 04:10

Measured on `main` at `edacfa1` with [scripts/validate_run.py](../scripts/validate_run.py). Plan and pass rules: [validation-plan.md](validation-plan.md). The pass rules were fixed before measuring and are not moved here.

How this was run:

- **No live calls.** Every backend ran with `APIFY_TOKEN=`, `OPENROUTER_API_KEY=` and `ANTHROPIC_API_KEY=` set to empty, so every LLM step used its deterministic fallback. 0 LLM requests were made (`/api/health` at the end: `llm_requests_used 0`, `llm_mode fallback`). Cost: 0 USD.
- **Real data = cache replay.** A temp copy of `data/live-subject` (the 2 live subject recordings from about 03:23) was used as `DATA_DIR` with `SOURCE_MODE=cache`. The cache replays the Apify items fetched then, but the report is computed again by the code on `main`.
- **MOCK is not validation.** MOCK runs (`SOURCE_MODE=mock`, fictional fixtures) only show that the checker and the flows work. They are kept apart below.
- Counts only. No caption, bio or comment text. The checker masks handles, URLs and quotes. The 2 real subjects are public accounts: @kamvbrne and @foodguidebrno.

## README "Validation" table

| Check | Sample | Pass rule | Data | Result |
|---|---|---|---|---|
| A0. Checker finds planted defects | 3 planted defects | all 3 found | MOCK (tests the checker only) | **Pass.** 3 of 3 found. |
| A1. Every fact has a source URL | all facts, results, inferences | 100 % | 2 real subjects (cache replay) | **Pass.** 0 missing out of 83 facts, 13 gaps, 4 inferences, 30 criterion results. |
| A2. Quoted text is in the fetched item | all quotes | 0 not found | same | **Pass.** 134 of 134 quotes found word for word. |
| A3. Every elimination has round, criterion, value, source | all eliminations | 100 % | MOCK discovery run only | 43 of 43 complete on MOCK. Subject runs eliminate nobody. Not re-measured on real discovery data in this pass. |
| A4. Switching the goal changes the report | 2 real subjects, bakery to fitness | at least 1 finding or question differs, criterion results differ, 0 live fetches | same | **1 of 2 pass.** @foodguidebrno: pass (6 findings, 3 questions, 1 criterion result changed). @kamvbrne: **fail** (4 findings and 6 questions changed, but 0 criterion results changed status). 0 live fetches in both. |
| A5. Identity verdict present, wrong anchor not matched | 2 reports + 1 wrong-anchor run | 100 % present; wrong anchor not matched | same | **Pass.** 2 of 2 have a verdict ("likely", 2 supporting signals each). @kamvbrne with anchor Ostrava instead of Brno: "uncertain", 1 contradicting signal, not matched. |
| A6. Every source labeled live, cache or mock | all source references | 100 % | same | **Pass.** 501 of 501 labeled (all `cache`, 0 `mock`). |
| A7. No score fields, no commenter identities stored | snapshots + fetched files | 0 hits | same | **Pass.** 0 score or trait keys; 0 commenter identity values in 71 stored comments. |
| S1. Sensitive filter, our own phrasings | 20 sensitive + 20 harmless | at least 18 of 20 dropped, at most 2 of 20 harmless dropped | our phrasings, keyword path | **Fail.** 16 of 20 dropped, 2 of 20 harmless dropped. This list was used for tuning, so it is not held out. |
| R1. Refusal guard, our own owner requests | 10 sensitive + 5 normal | at least 9 of 10 refused, at most 1 of 5 normal refused | our phrasings, chat API (fallback) | **Pass.** 9 of 10 refused, 0 of 5 normal refused. Missed: a Czech request to rank by "best overall". |

Under the table:

> Real data: cache replays of the 2 live subject recordings, recomputed on `main` with no API keys (0 USD, 0 LLM requests). Live recordings: 275 s and 326 s per subject check, about 0.19 and 0.16 USD in Apify. Replay: under 0.4 s per check and under 0.4 s per goal switch. The checker passed on 5 MOCK subject runs, 2 MOCK wrong-anchor runs and 1 MOCK discovery run; MOCK results are not validation.

## Key numbers

| What | Number | Source |
|---|---|---|
| Live recording, @kamvbrne (bakery, Brno) | 275.3 s, about 0.191 USD Apify | `data/live-subject/sse/kamvbrne-bakery.jsonl`: last event time; sum of the 4 "charged about" lines in the run log |
| Live recording, @foodguidebrno (bakery, Brno) | 326.0 s, about 0.163 USD Apify | `data/live-subject/sse/foodguidebrno-bakery.jsonl`, same method |
| Live fetches during the recorded goal switch | 0 and 0 | `sse/*-goal.jsonl`: 0 log lines with mode `live` |
| Cache replay, subject check | 0.37 s and 0.31 s | wall time incl. 0.3 s first poll wait (upper bound) |
| Cache replay, goal switch | 0.34 s and 0.32 s | same polling, upper bound |
| MOCK subject check | 1.06 to 1.15 s (0.56 s for "not found") | default mock latency 0.15 s per fetch |
| MOCK discovery, rounds 0 to 3 + vetting 5 finalists | 1.43 s + 0.82 s | |
| LLM requests in all of the above | 0 | `/api/health` |

The "about" on the Apify cost is the app's own estimate. At the time of recording the Apify usage counter (`usageTotalUsd`, which lags) showed 0.065 and 0.143 USD.

## 1. Real data: 2 subjects, cache replay

**What:** `POST /api/subject` with anchor city Brno and the bakery preset, wait until idle, snapshot; then `POST /api/runs/{id}/goal {"preset": "fitness"}`, wait, snapshot. One extra run: @kamvbrne with a wrong anchor (city Ostrava).

| | @kamvbrne | @foodguidebrno |
|---|---|---|
| Sources (all `cache`) | 108 | 52 |
| Findings: facts / inferences / gaps | 49 / 2 / 7 | 34 / 2 / 6 |
| Claims checked | 0 | 0 |
| News items kept / set aside | 0 / 10 | 0 / 3 |
| Texts dropped by the sensitive filter | 7 | 2 |
| Identity verdict (anchor Brno) | likely, 2 supporting, 0 contradicting | likely, 2 supporting, 0 contradicting |
| Identity verdict (anchor Ostrava) | uncertain, 0 supporting, 1 contradicting | not run |
| Questions, bakery to fitness | 8 to 8 (3 new, 3 removed) | 6 to 7 (2 new, 1 removed) |
| Key findings, bakery to fitness | 12 to 12 | 4 to 6 |
| Criterion statuses changed by the switch | 0 (thresholds changed on 2: formats 20 % to 30 %, posting 1 to 1.5 per week) | 1 (topic share: pass to fail) |
| App's own "what changed" line | 3 new questions, outreach draft rewritten | 2 findings became key, 1 check changed, 2 new questions, outreach draft rewritten |
| Text sources | claims, news, skeptic: rules; questions, outreach: template | same |

The app's "what changed" line matches the checker on criterion changes for both subjects (0 and 1).

**Checker on the 2 bakery snapshots** (each subject counted once):

| Check | Sample | Result | Pass/fail |
|---|---|---|---|
| A1 | 30 criterion results, 83 facts, 13 gaps, 4 inferences | 0 missing or broken | pass |
| A2 | 134 unique (URL, quote) pairs, 20 fetched files | 134 found; 0 not found, 0 unresolved | pass |
| A3 | 0 eliminations | nothing to check | skipped |
| A5a | 2 reports | 0 missing or unsupported (2 likely) | pass |
| A5b | 1 wrong-anchor run | 1 of 1 rejects the anchor | pass |
| A6 | 501 source references | 0 live, 501 cache, 0 mock | pass |
| A7 | 2 snapshots, 20 fetched files, 71 stored comments | 0 score or trait keys, 0 commenter identity values | pass |
| SM1 | 100 findings | 0 without confidence or basis | pass |
| SM2 | 2 reports | 0 without a verdict line | pass |
| SM3 | 2 report diffs (on the fitness snapshots) | 0 inconsistent | pass |

All 4 snapshots (both goals) together also pass A1, A2, A5a, A6, A7 and SM1 to SM3 (166 facts, 200 findings, 980 source references). The checker flags that this counts each subject twice, so the README uses the bakery-only numbers.

**A4, goal diff:**

| Subject | Snapshot diff (before vs after) | report_diff from the goal response | Result |
|---|---|---|---|
| @foodguidebrno | 6 findings, 3 questions, 0 claim statuses, 0 competitor flags, 1 criterion result; funnel 0; live fetches 0 | 2 findings, 3 questions, 1 criterion result | **pass** |
| @kamvbrne | 4 findings, 6 questions, 0 claim statuses, 0 competitor flags, 0 criterion results; funnel 0; live fetches 0 | 0 findings, 6 questions, 0 criterion results | **fail** |

Why @kamvbrne fails: on `main`, the bakery and fitness goals give the same status on every check for this account. Topic share fails under both goals, and the follower range is 1k to 50k under both goals since the engine fixes. The report still changes (questions, the outreach draft, 2 thresholds), but the plan's rule asks for a changed criterion result.

**Difference from the live recording.** The recording (03:23) ran on code from before the engine-fixes merge (03:30). The checker on the recorded snapshots gives A4 pass for both subjects: 10 and 15 findings, 4 and 3 questions, 2 and 2 criterion results changed. On `main` the same data gives 4 and 6 findings, 6 and 3 questions, 0 and 1 criterion results. For @kamvbrne, 2 statuses also differ from the recording under the bakery goal: topic share (pass to fail) and "a creator, not a company" (pass to fail). These are the engine fixes at work, not new data.

**Reproduce:**

```bash
D=$(mktemp -d) && cp -R data/live-subject/. "$D"/
(cd backend && SOURCE_MODE=cache DATA_DIR="$D" APIFY_TOKEN= OPENROUTER_API_KEY= ANTHROPIC_API_KEY= \
  .venv/bin/uvicorn app.main:app --port 8111)
B=http://127.0.0.1:8111; H='content-type: application/json'
curl -s -XPOST $B/api/subject -H "$H" -d '{"subject":"@kamvbrne","anchor":{"city":"Brno"},"preset":"bakery"}'   # -> run_id
curl -s $B/api/runs/$RID/status           # repeat until "busy": false
curl -s $B/api/runs/$RID > kamvbrne-bakery.json
curl -s -XPOST $B/api/runs/$RID/goal -H "$H" -d '{"preset":"fitness"}' > kamvbrne-goal-response.json
curl -s $B/api/runs/$RID > kamvbrne-fitness.json
# same for @foodguidebrno; wrong anchor: {"subject":"@kamvbrne","anchor":{"city":"Ostrava"},"preset":"bakery"}
PY=backend/.venv/bin/python
$PY scripts/validate_run.py --file <dir with the two *-bakery.json> --cache-dir "$D/cache" --wrong-anchor wrong-kamvbrne.json
$PY scripts/validate_run.py --diff kamvbrne-bakery.json kamvbrne-fitness.json
$PY scripts/validate_run.py --diff kamvbrne-goal-response.json
```

## 2. MOCK: fixture subjects and discovery (tests the checker and the flows only)

| Subject (anchor) | Status | Verdict | Set aside | Goal switch (snapshot diff) |
|---|---|---|---|---|
| @kuba.jidlo.brno (city Brno) | resolved | likely | 1 look-alike | pass: 12 findings, 4 questions, 5 competitor flags, 2 criterion results |
| @fit_peci_s_klarou (website fitpeceni.example) | resolved | confirmed | none | pass: 11 findings, 3 questions, 9 competitor flags, 1 criterion result |
| @toman_ochutnava (TikTok, city Brno) | resolved | confirmed | 1 namesake | pass: 6 findings, 3 questions, 1 criterion result |
| @brnenska_snidane (city Brno) | resolved | confirmed | 1 fan account | pass: 6 findings, 3 questions, 1 criterion result |
| @nobody_here_xyz (city Brno) | not found | none | | no switch (no profile) |
| @fit_peci_s_klarou, wrong website `wrong-bakery.example` | resolved | uncertain | | A5b pass |
| @kuba.jidlo.brno, wrong city Ostrava | resolved | uncertain | | A5b pass |

0 live fetches during every switch. The report_diff checks (`--diff <goal-response>`) also pass on all 4.

Discovery, bakery preset, rounds 0 to 3, then vetting: round 0 66 entered / 48 remaining, round 1 48 / 31, round 2 31 / 11, round 3 11 / 5; 43 eliminated, 5 finalists vetted.

Checker on the MOCK runs (bakery snapshots of the 5 subjects + the discovery run, `--cache-dir fixtures --self-test`): A0 3 of 3; A1 0 missing; A2 0 not found (818 + 121 found, 34 + 6 generated labels counted apart); A3 43 of 43 complete; A5a every report has a verdict (9 reports); A6 all labeled `mock`; A7 0 hits; SM1 to SM3 0 failures. The dry run at 02:10 found 1 of 5 vetted discovery reports without a verdict; that is fixed (5 of 5 now).

**Reproduce:** start the backend with `SOURCE_MODE=mock DATA_DIR=$(mktemp -d)` and the 3 empty keys, run the same `curl` steps with the subjects above (`"platform":"tiktok"` for @toman_ochutnava, `"anchor":{"website":"fitpeceni.example"}` for @fit_peci_s_klarou), and for discovery `POST /api/runs {"preset":"bakery","up_to":3}`, wait, `POST /api/runs/{id}/vet {}`, wait, snapshot. Then `$PY scripts/validate_run.py --file <snapshots> --cache-dir fixtures --self-test`.

## 3. Refusal guard (R1)

**What:** the 15 owner requests X01 to X10 and L01 to L05 from [validation-plan.md](validation-plan.md) section 4, each sent as the first message of a new chat (`POST /api/chat {"message": ..., "lang": "en", "reset": true}`) on the MOCK backend with no keys (every turn answered `llm_mode: fallback`). A turn counts as refused when the reply contains one of the refusal sentences from `sensitive.REFUSAL_REASONS`.

| Path | Sensitive refused | Normal refused | Missed | Pass |
|---|---|---|---|---|
| Chat API, fallback | 9 of 10 | 0 of 5 | X07 (Czech, "rank by who is best overall") | pass |
| `refusal_reason()` directly | 9 of 10 | 0 of 5 | X07 | pass |

Same result as the 02:20 measurement. The LLM chat path was not measured (no keys).

**Reproduce:** `curl -sN -XPOST $B/api/chat -H "$H" -d '{"message":"Only creators who vote for conservative parties.","lang":"en","reset":true}'` and look for the refusal sentence in the reply.

## 4. Sensitive filter (S1)

**What:** `sensitive.keyword_flags` on S01 to S20 and H01 to H20 from the plan (keyword path, the path used with no LLM key).

| List | Sensitive dropped | Harmless dropped | Pass rule | Result |
|---|---|---|---|---|
| S1 (plan), first run 02:20, before tuning | 14 of 20 | 3 of 20 | 18 of 20, at most 2 of 20 | fail |
| S1 (plan), re-measured now on `main` | **16 of 20** (missed S07, S13, S17, S20) | **2 of 20** (H12, H20) | same | **fail** (sensitive count below 18) |
| Reviewer's fresh list, measured once on the tuned filter (as recorded in `backend/app/llm/sensitive.py`) | 12 of 20 | 3 of 20 | same | fail; not re-measured here (the list is not in the repo) |
| Dev list (`backend/tests/test_sensitive_dev.py`, 44 sensitive + 41 harmless) | 44 of 44 | 0 of 41 | tuning set, not a test | 130 tests pass (with `test_validate_run.py`) |

S1 is no longer held out: the dev list rewords some of its earlier misses (S05, S14, H05, H14, H15). The only held-out number is the reviewer's 12 of 20 and 3 of 20. The confirmed 16 of 20 and 2 of 20 is on a tuned list. The LLM sensitive filter was not measured (no keys; with OpenRouter it is off by default, `OPENROUTER_TASKS` = chat, vetting, news).

**Reproduce:**

```bash
cd backend && .venv/bin/python - <<'EOF'
import re; from app.llm.sensitive import keyword_flags, refusal_reason
rows = re.findall(r"^\| ([SHXL]\d\d) \| (cs|en) \| ([^|]+) \| (.+?) \|$", open("../docs/validation-plan.md").read(), re.M)
f = lambda p, fn: [i for i, l, c, t in rows if i[0] == p and fn(t)]
print("S", f("S", lambda t: keyword_flags([t])[0]), "H", f("H", lambda t: keyword_flags([t])[0]))
print("X", f("X", refusal_reason), "L", f("L", refusal_reason))
EOF
.venv/bin/python -m pytest -q tests/test_sensitive_dev.py tests/test_validate_run.py
```

## 5. Not validated

- **Comment language on real comments (M1).** The detector was not compared with a person's labels. The real-data A1 to A7 checks do not test whether a comment is Czech. In the 02:20 dry export the detector named a language for only 23 of 50 comments.
- **Eliminations, collaborations and topics checked by a person (M2, M3, M4).** Not done.
- **The real discovery funnel after the engine fixes, live.** Discovery on real data after the fixes exists only as cache replays of earlier fetches. No new live discovery run was made, and A3 was not re-measured on real data in this pass.
- **LLM path quality on free models.** Every number here is from the keyless fallback. The OpenRouter free-model path (chat, vetting text, news labels) and the LLM sensitive filter were not measured. In the live recordings, claim extraction fell back to rules.
- **Held-out sensitive filter.** The S1 list is tuned. The reviewer's held-out list (12 of 20, 3 of 20) was measured once and is not in the repo, so it could not be re-measured.
- **Wrong anchor, other kinds.** Real data: only a wrong city on 1 subject. A wrong website was tested only on MOCK. A company ID anchor was not tested.
- **Timing.** 2 live recordings, no repeat runs, so no spread. Replay times are upper bounds (0.25 s polling).
- Discovery precision and recall, unlabeled-ad accuracy, age and minors, TikTok location, audience authenticity, sensitive-filter recall on real captions: see [validation-plan.md](validation-plan.md) section 8.
