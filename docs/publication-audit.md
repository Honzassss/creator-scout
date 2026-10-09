# Pre-publication privacy and security audit

Audit of 9 Oct 2026, about 03:30, before the freeze (reviewed and corrected about 03:55). The repo is private on GitHub (`Honzassss/creator-scout`, `origin/main` = `5a186db`). Local `main` = `0168b60`. Read-only audit: nothing was changed except this file.

**Verdict.** No secrets anywhere in git. No real scraped data committed, ever. No real comment texts, captions or bios. There is one commit message to fix before the history goes public (F3). Two gaps in the deletion plan must be closed by hand (F1, F2).

## Scope and method

- History: `git log --all -p` over all branches (`main`, `subject-frontend`, `origin/main`; 32 commits up to `0168b60`, about 270 paths ever tracked), plus every git object, including the 31 unreachable objects (2 commits, 10 trees, 19 blobs) left by merges and stashes.
- Working tree: tracked files, ignored files (`.env`, `data/`, `docs/design/inspirace/`), untracked files (`docs/design/board/`, `scripts/record*`), the other worktrees (`creator-scout-fe`, `creator-scout-engine`) and the shared session scratchpad.
- Secrets: regex scan for Apify (`apify_api_`), OpenRouter (`sk-or-v1-`), Anthropic (`sk-ant-`), GitHub (`ghp_`, `github_pat_`, `gho_`), Vercel, AWS, Slack and private-key patterns. The real `APIFY_TOKEN` (46 chars) and `OPENROUTER_API_KEY` (73 chars) values from the local `.env` were also searched for literally. They were never printed.
- Personal data: all 1,780 handles, 901 display names and 2,935 texts (40+ characters) in the real data (`data/live-tests`, `data/live-run`, `data/live-subject`) were cross-checked against every tracked file, every historical diff and every commit message.

## Clean (no action)

| Check | Result |
|---|---|
| Secrets in history (all branches, all objects incl. unreachable) | **0**. Only the fake test value `sk-or-test-not-real`. The real Apify and OpenRouter values: 0 hits in history, git objects, tracked tree, `frontend/dist`, `data/`. |
| `.env` committed | Never. Ignored by `.gitignore:5`. `.env.example` has empty keys only. |
| `data/` committed | Never (no `data/` path in any commit). Ignored by `.gitignore:1`. |
| Third-party screenshots `docs/design/inspirace/` (7.9 MB) | Never tracked (ignored by `.gitignore:10`, absent from all historical paths). |
| `fixtures/` | Fictional by design (seeded generator, `(MOCK)` names, `.example` URLs). No fixture handle appears in the real data. `proteomax` appears there only as a competitor the team typed into a brief, not as a scraped account. |
| `backend/tests/apify_samples/` (16 files) | All labelled HAND-MADE with `sample_*` accounts. Every historical version checked: no real handle ever. |
| Real comment texts, captions, bios in git | **0** of 2,935 real texts found in any tracked file or diff. |
| Commenter identities in raw data | None: the 162 comment items in `data/live-tests` hold only text, timestamp, likes, replies. The redaction in `scripts/live_tests.py` works. |
| Screenshots `docs/design/pred/`, `po/` | Show the MOCK replay only (MOCK frame and stamp). Committed in `71f4f92`, before the first real run was merged. |
| Fonts and assets | IBM Plex Sans/Mono and Newsreader load from Google Fonts (SIL OFL); no font files are committed. `favicon.svg` is our own. No vendored third-party code. |
| Hard lines in code | No overall score or "best" anywhere; such requests are refused (`backend/app/llm/sensitive.py`, `chat.py`, `prompts.py`). Nothing tracked scores a person or infers an Art. 9 trait. |
| Vercel demo (`scripts/deploy-demo.sh`) | Static MOCK replay only, noindex, refuses to deploy if the bundle looks like it holds a key. |

## Findings

| # | Severity | Where | What | Action | History rewrite? |
|---|---|---|---|---|---|
| F1 | **High** | `scripts/purge_all.sh` (`NAMES`, line 49) | The purge script does not cover **`data/live-subject/`**. That folder holds real subject runs of @kamvbrne (bakery and fitness goals) and @foodguidebrno (bakery): `cache/`, `llm/`, `runs/`, `snapshots/`, `sse/`. It has 37 files and 2.6 MB, and it is still growing. The in-app purge (`POST /api/purge`, `store.purge_all`) only clears `DATA_DIR/cache`, `runs` and `llm`. With the default `DATA_DIR` it misses this folder entirely. With `DATA_DIR=data/live-subject` (how `docs/README-draft.md` starts subject runs) it still leaves `snapshots/` and `sse/`. | Add `live-subject` to `NAMES` and to the `case` allow-list in `purge_all.sh`. This lane may not edit existing files, so the orchestrator must do it. Otherwise delete it by hand (see the list below). | No |
| F2 | **High** | Outside the repo | Copies of the real run data sit in the shared session scratchpad `/private/tmp/claude-501/-Users-honzik/ea9c8f0f-4c61-4c4b-9193-50ba58769a35/scratchpad/`. It was 523 MB at the audit and 617 MB with 5,282 files at 03:50, and it is still growing; about 1,500 of those files hold live/cache data. Examples: `cache/`, `cache_copy/`, `imported/`, `data-before*/`, `data-after*/`, `before_data/`, `after_data/`, `final_data/`, `head_data/`, `replay-data/`, `run_live*.json`, `sse_live*.txt`, `replay.json`, `fix2_*.json`, `kamvbrne-bakery.out`, `foodguidebrno-bakery.out`. The new `scripts/record-demo.sh` writes `<repo>/demo-output/` (videos, frames, raw `.webm`). With `--source cache` those show real people, and `demo-output/` is **not** in `.gitignore`. At 03:50 `demo-output/` already exists: 30 MB, untracked, one MOCK run (`run-20261009-034458`, no real data). A `git add -A` or `git add .` would commit it. | Delete the whole scratchpad after judging. Add `demo-output/` to `.gitignore` now (the orchestrator, since this is an existing file). After the video is cut, delete the raw takes and any shots that show real accounts. | No |
| F3 | **Medium** | Commit message of **`56bd747`** (on `main` and `origin/main`) | The message names a private person's Instagram handle (first name, surname and `_brno`; not repeated here on purpose). It calls her a council candidate whose texts were mostly removed by the sensitive filter. That ties political-opinion (Art. 9) information to an identifiable person. The same message also quotes short bio fragments from real creators, without handles. **The first version of this file (commit `f06e9be`, local, not pushed at the time) repeated the handle, the bio fragments and the author's e-mail. That made it the only commit whose file contents held the handle. The follow-up commit redacted them.** | Acceptable if the repo stays private and the jury gets read access. Before making the history public, either reword this message and scrub `f06e9be`, or publish a squashed snapshot (recommended, see below). The current tree is clean, so a squashed snapshot needs no extra step. | **Yes**, only if the full history is published. Use `git filter-repo --message-callback` for `56bd747` and `--replace-text` for the `f06e9be` blob, or a reword rebase. Either one changes those hashes and every later one. It then needs a force-push to `origin/main` (with the user's OK) and a re-sync of the worktrees. |
| F4 | Low | `backend/tests/test_engine_fixes.py:108-183,250,331-346`; `backend/app/rounds/r1_basics.py:261`; `backend/app/sources/apify_provider.py:956`; `backend/tests/test_apify_mappers.py:150` | Real names from the Brno run used as test inputs. Organisations (GDPR does not cover legal entities): `pirati.brno` (Political Party), "Hnutí Nové Brno", "Anarchistický Bookfair Brno", "Zelené Brno" with an election post ("Volte č. 3"), `elsabrno` (student union), "FC Slovan Brno", "Bulldogs Brno", "Vážkafé", "Kavárna Kofi2 Brno". Handles that may belong to people: `brnenska_mama` (test line 250), `foodiesbrno` (comment), `bruno_food_factory` (test). The council-candidate case in the test is pseudonymised as `marie`. | Optional: replace `brnenska_mama`, `foodiesbrno`, `bruno_food_factory` with `sample_*` names after the freeze. | No |
| F5 | Low | All commits | Author and committer use the author's real name and a school e-mail address. A public history exposes it. | Accept, or publish a squashed snapshot under a GitHub noreply address. | Only to change past commits |
| F6 | Low | `fixtures/`, `frontend/src/dev/demo*.ts`, README, tests, `docs/design/po`/`pred` | Fictional handles look plausible (`@kuba.jidlo.brno`, `@toman_ochutnava`, `@brnenska_snidane`, `@fit_peci_s_klarou`, `@mlsna_brnenka`, `@snidane_s_tomasem`, `@pekarna_a`/`_b`, `@proteomax`, `@fitzone_brno`, ...). They carry invented findings such as "brand post without an ad label". None of them is in the real data, and the UI labels are clear (`(MOCK)` names, MOCK frame, `.example`/`.invalid` URLs, disclaimer in the fixtures README). Someone could still own these handles. | None for the freeze. Later, consider a `mock_` prefix. | No |
| F7 | Low | `docs/design/pred/`, `docs/design/po/`; untracked `docs/design/board/` | 114 tracked PNGs, about 57 MB in HEAD; the pack is 57 MB; the largest file is 3.3 MB (under GitHub's 100 MB limit). The untracked `docs/design/board/` (20 MB) holds 46 copies of the pred/po PNGs plus an HTML page with text links to designspells.com, refero.design and details.so. It contains no third-party images. | Do not commit `docs/design/board/` as is: link to the `pred/`/`po/` paths, or leave it out. Optional: drop `pred/` from a squashed public snapshot. | No |
| F8 | Low | `.claude/launch.json:6,12`; `docs/subject-mode.md:5,41,47` | Absolute local paths (`/Users/honzik/...`) reveal the local username. `launch.json` also does not work on any other machine. | Optional. | No |
| F9 | Info | Repo root | There is no `LICENSE`, so a public repo is "all rights reserved" by default. | Add one (e.g. MIT) if reuse is intended. | No |
| F10 | Info | Local `.git` | 31 unreachable objects from merges and stashes (e.g. `57703ae "index on main"`). They are local only and never pushed. | Share through GitHub, not by zipping the folder. The folder also holds `.env` and `data/`. If a zip is unavoidable, run `git gc --prune=now` first and exclude `.env` and `data/`. | No |

### Recommended publication form

- **Option 1, simplest at the freeze:** keep the repo private and invite the jury as read-only collaborators. Nothing needs rewriting.
- **Option 2, if it must be public:** publish a **squashed snapshot**. Make one orphan commit of the freeze tree, in a new public repo or an orphan branch pushed alone. This drops F3, the old fixture versions and the old screenshots, and it needs no force-push on the team's `main`. Check `docs/design/board/` and `demo-output/` are not in the tree before the snapshot.
- **Avoid:** making the current repo public with its full history unless F3 is fixed first (reword `56bd747`, scrub `f06e9be`).

## Real public accounts named in tracked files (acceptable, listed)

- **Instagram, Brno food accounts as test/demo candidates** (`docs/apify-pro-krystofa.md:60,117-129`):
  - Active: `foodloverbrno`, `gourmetbrno`, `foodie_brno_`, `judgemental_tuna`.
  - Media account: `kamvbrne`. Also the default T5/T6 input in `scripts/live_tests.py`, used in `backend/tests/test_live_tests_script.py`, and named in `docs/verification.md` and `docs/overeni-2026-10-08.md`.
  - Named as "good examples of elimination", with last-post dates: `foodguidebrno`, `brno_best_bites`, `foodblogcs`. This is factual activity information.
- **TikTok:** `apifytech`, `khaby.lame` (`scripts/live_tests.py:86`, `docs/apify-pro-krystofa.md:177-180`).
- **YouTube videos:** `JsBZOcqZerk`, `1H20xp8Brnc` (`scripts/live_tests.py:87`, `docs/apify-pro-krystofa.md:199`, `backend/tests/test_live_tests_script.py:49-52`).
- **Brands:** Nike, Rohlík (T8 brand-collaboration tests; docs).
- **Code and tests:** see F4. **Commit messages:** one private person's handle (F3) and `zelenebrno` (a party).
- **Real subjects run in subject mode** (only in ignored `data/live-subject/`, not in docs): `kamvbrne` (bakery and fitness), `foodguidebrno` (bakery).

## Deleting raw data after judging (rule from the brief)

**`scripts/purge_all.sh --dry-run`, then `--yes`.** It deletes, in this repo and in every git worktree: `data/cache`, `data/runs`, `data/llm`, `data/live-tests`, `data/live-run`, `data/validation`. Today in `main` that means:

- `data/live-tests`: 29 MB, 26 files, the raw actor outputs of T1-T12.
- `data/live-run`: 4.3 MB, 134 files, the real Brno cache plus 4 live/cache runs.
- `data/runs`: 13 MB, 10 MOCK runs.

The other worktrees have no `data/` at the moment.

**The app's "Smazat data" / `POST /api/purge`** deletes only `cache/`, `runs/` and `llm/` in the running backend's `DATA_DIR`.

**Must be deleted by hand:**

1. `data/live-subject/`: `rm -rf data/live-subject`, unless F1 is fixed first.
2. Anything else under `data/` or a custom `DATA_DIR`. After the purge, `ls data/` should be empty.
3. `<repo>/demo-output/` (recordings, frames, raw `.webm`), plus any exported video takes that show real accounts. Keep only the final cut with eliminated names blurred.
4. The session scratchpad `/private/tmp/claude-501/-Users-honzik/ea9c8f0f-4c61-4c4b-9193-50ba58769a35/` (617 MB at 03:50 and growing, with real data among its files), plus any other agent scratchpad from these workflows (`grep -rl kamvbrne /private/tmp/claude-501`).
5. **Apify Console → Storage:** the datasets, key-value stores and request queues of the actor runs of 8-9 Oct. They live in the Apify account until deleted or until the plan's retention expires.
6. **OpenRouter:** `data_collection` is set to `deny` (`backend/app/config.py:107`). Check that prompt logging is off in the account settings. The Activity page keeps request metadata only.
7. **Hygiene:** rotate the Apify token and the OpenRouter key after the event. They never left the machine through git, but many agents used them.

## For the orchestrator

1. **Before the freeze:**
   - Add `live-subject` to `NAMES` and the allow-list `case` in `scripts/purge_all.sh`.
   - Add `demo-output/` to `.gitignore`.
   - Do not commit `docs/design/board/` or `demo-output/`.
2. **Decide the publication form:** keep private with jury access, or publish a squashed public snapshot. Making the current history public needs F3 fixed first (reword `56bd747`, scrub `f06e9be`), which means a force-push and the user's approval.
3. **After judging:** run `scripts/purge_all.sh --yes`, then work through the "by hand" list above.
