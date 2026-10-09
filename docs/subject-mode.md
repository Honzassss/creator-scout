# Subject mode, goal-conditioned reports, confidence, English, LLM budget: build contract

**Status: implemented** on branch `subject-mode` (backend and chat; the frontend notes in section 12 are still open). As-built summary and the deviations from this contract: [architecture.md section 5a](architecture.md).

Contract for three parallel implementers (A engine+API+models, B chat, C LLM budget) on branch `subject-mode` in the worktree `/Users/honzik/Developer/creator-scout-subject`. It extends [architecture.md](architecture.md); where the two disagree, this file wins for the features below. Code freeze is about 07:00.

Jury definition of done: the input is a subject, one anchor and a goal. The output is a report where every claim links to a source, fact is split from inference, and gaps are stated. Same subject with a different goal gives a different report. Namesakes and look-alikes are handled, and the user can see how the report was put together.

## 0. Acceptance scenario (all three build toward this)

All of this runs with `SOURCE_MODE=mock`, no LLM keys and `LLM_PROVIDER=auto`.

1. `POST /api/subject {"subject": "@fit_peci_s_klarou", "anchor": {"website": "fitpeceni.example"}, "brief": "bakery", "lang": "en"}` returns `{run_id}`. The run stream shows `subject.resolved`, rounds 1-3 as checks (nothing eliminated), vetting progress and `report.ready`.
   - `report.identity_verdict.status == "confirmed"`. The text starts with "We are confident @fit_peci_s_klarou is the creator you mean because": the website is on the profile and TikTok @fit_peci_s_klarou links back.
   - Every finding has a `confidence` and a `confidence_basis`.
   - The labeled ProteoMax collaboration has tier `less` (ProteoMax is not a bakery competitor).
   - The questions are bakery-specific.
2. `POST /api/runs/{id}/goal {"preset": "fitness"}` makes no fetch and no LLM request: `llm_requests_used` stays the same. The response carries `report_diffs[0]`:
   - `i:competitor` is added, because ProteoMax is a fitness competitor.
   - The ProteoMax collab fact moves up to `key`.
   - The `f:fit:topics` text now talks about fitness topics.
   - Questions and the outreach draft change.
   - The run stream gets `report.diff` and `report.ready`.
3. `POST /api/subject {"subject": "https://www.instagram.com/kuba.jidlo.brno/", "anchor": {"city": "Brno"}, "brief": "bakery", "lang": "en"}` gives:
   - TikTok @kuba_jidlo (Bratislava, no links) is set aside as a look-alike.
   - The claim "exkluzivní ambasador @pekarna_a" is `conflicts_with_record` with tier `key`.
4. `{"subject": "@toman_ochutnava", "platform": "tiktok", "anchor": {"city": "Brno"}, "brief": "bakery"}`: the article about the Zlín businessman Ondřej Toman is set aside as a namesake, and the verdict text says so.
5. `{"subject": "@brnenska_snidane", ...}`: TikTok @brnenska_snidane_fans is set aside as a fan account.
6. `{"subject": "@nobody_here_xyz", ...}`: the run stream shows `subject.not_found`, `run.subject.status == "not_found"`, no candidate and no error.
7. In the chat (fallback, English UI), "Check @fit_peci_s_klarou for my bakery in Brno" gets one question about the anchor. The answer "fitpeceni.example" starts the run through `research_subject`. Then "what about my fitness studio?" changes the goal, and the reply summarises the report diff.

## 1. Ground rules for parallel work (read first)

- **Shared working tree.** All three of you edit the same directory at the same time.
  - Edit ONLY the files you own (section 2).
  - Never run `git add -A`, `git stash`, `git checkout -- <file>`, `git reset` or a formatter over the whole repo.
  - Commit only your own paths (`git add <paths>`), with a HEREDOC message and the Co-Authored-By trailer.
  - If `.git/index.lock` exists, wait and retry.
  - Do not push, rebase or merge. The orchestrator integrates.
- **Tests.**
  - While you work, run only your own test files, e.g. `cd /Users/honzik/Developer/creator-scout-subject/backend && /Users/honzik/Developer/creator-scout/backend/.venv/bin/python -m pytest -q tests/test_subject.py`.
  - Run the full suite once at the end. A failure in a file you do not own is reported in your final message, not fixed.
  - Existing tests in files you do not own must keep passing. Make your change backward compatible instead.
- **Environment.**
  - Servers only on ports 8020-8029: A uses 8020, B uses 8021, C uses 8022.
  - Use a temp `DATA_DIR`, `SOURCE_MODE=mock`, unset `ANTHROPIC_API_KEY` and `OPENROUTER_API_KEY`, and set `LLM_PROVIDER=auto`.
  - Never touch `/Users/honzik/Developer/creator-scout` (the main tree).
- **Backward compatibility.**
  - Every new model field is optional with a default, so old run snapshots and fixtures still load.
  - Do not rename or remove existing public functions, fields, events or routes, and do not change their signatures. Add alongside them.
  - These functions are used across teams and are frozen: `chat.criteria_for_brief(brief, refused=None)`, `chat.normalize_criteria_set(cs)`, `client.structured(...)`, `client.record_mode`, `client.bind_llm_modes`, `client.cache_get/cache_put`, and all `vetting.*` functions that `test_llm.py` calls.
- **i18n.** Every new user-facing string is a `{"cs": ..., "en": ...}` map (`models.i18n`). English must read naturally: the hackathon is judged in English.
- **Hard lines.** These are unchanged and also apply to the new code:
  - No overall score, rank, "best", risk level, or personality, credit or trust rating. A relevance tier ranks FINDINGS for a goal, never the creator.
  - The identity verdict says whether this is the account the owner means. It is never "trustworthy".
  - No GDPR Art. 9 inference and no audience demographics.
  - Sensitive content is filtered before storage and kept as a count only.
  - Minors are not processed.
  - Outreach is never sent.
  - Anchor `company_id` is matched as text in public data only. No registry or private lookups.
- **Not owned by anyone (do not edit):**
  - `backend/app/sources/*`, `backend/app/llm/sensitive.py`, `backend/app/llm/topics.py`, `backend/app/llm/text.py`
  - `fixtures/*`, `frontend/*`, `scripts/*`
  - `docs/architecture.md`, `README.md`. The orchestrator updates these from this file after integration.
  - `tests/test_apify_mappers.py`, `test_cache.py`, `test_factory.py`, `test_mock_provider.py`
  - Exception: `llm/prompts.py` belongs to B (see section 2).

## 2. File ownership (no overlap)

| Owner | Files |
|---|---|
| **A** engine + API + models | `backend/app/models.py`, `backend/app/presets.py`, `backend/app/rounds/*` (incl. new `rounds/report.py`), `backend/app/compute/*` (incl. new `compute/subject.py`), `backend/app/llm/vetting.py`, `backend/app/main.py`, `backend/app/store.py`, `backend/app/events.py`; tests: new `tests/test_subject.py`, new `tests/test_report_render.py`, and `tests/test_api.py`, `test_rounds.py`, `test_compute.py`, `test_models.py`, `test_review_fixes.py` |
| **B** chat | `backend/app/llm/chat.py`, `backend/app/llm/prompts.py` (CHAT_SYSTEM and new chat constants only; the vetting prompts in it stay byte-identical), tests: `tests/test_llm.py`, new `tests/test_chat_subject.py` |
| **C** LLM budget | `backend/app/config.py`, `backend/app/llm/client.py`, `backend/app/llm/openrouter.py`, new `backend/app/llm/budget.py`, `.env.example`, `backend/tests/conftest.py` (only: add env names to `_LLM_DEFAULTS` + an autouse budget reset), tests: `tests/test_openrouter.py`, new `tests/test_llm_budget.py` |

What each team owes the others first, so nobody waits:

- **A, in the first 20 minutes:**
  - the model additions in section 3 (`models.py`);
  - `presets.preset_brief` and `get_preset(..., lang)` (section 8.6);
  - `compute/subject.py` with `parse_subject` and `normalize_anchor` (section 4.2).
- **C, in the first 15 minutes:** `llm/budget.py` with the full public API in section 9.2. Simple bodies are fine at first, but the signatures are final.
- **B** depends on A only through names listed here. B imports A's modules lazily inside functions and tolerates their absence: `getattr(run, "mode", "discovery")`, and a try/except `ImportError` around `app.compute.subject`.

Avoid other A-to-B imports. A may call `chat.criteria_for_brief` and `chat.normalize_criteria_set`, which already exist. B may call `app.compute.subject.parse_subject`, `app.presets.preset_brief/get_preset` and `app.compute.language.detect_language`, which already exist.

## 3. Models (A, `backend/app/models.py`; all additive)

```python
Confidence = Literal["high", "medium", "low"]
RelevanceTier = Literal["key", "related", "less"]     # "less" = collapsed under "Less relevant for this goal"

# Goal aspects: which part of the owner's goal a finding matters for.
ASPECTS: tuple[str, ...] = ("identity", "content_fit", "reach_engagement", "local_language", "competitors",
                            "ad_disclosure", "account", "reputation", "practical")
ASPECT_LABELS: dict[str, dict[str, str]]   # i18n per aspect, e.g. "content_fit": {"cs": "Obsah k cíli", "en": "Content fit"}
CRITERION_ASPECT: dict[str, str] = {
    "public_account": "account", "active_recently": "account", "not_brand_account": "account",
    "followers_range": "reach_engagement", "min_engagement": "reach_engagement", "max_generic_comments": "reach_engagement",
    "language_cs": "local_language", "cs_comment_share": "local_language", "local_signal": "local_language",
    "topic_share": "content_fit", "formats": "content_fit", "post_frequency": "content_fit",
    "max_commercial_share": "ad_disclosure", "discloses_ads": "ad_disclosure",
    "no_competitor_collab": "competitors",
}

class Anchor(BaseModel):                    # one is enough; all optional
    city: str | None = None                 # where the creator / organization is based
    website: str | None = None              # normalized host, e.g. "fitpeceni.example" (no scheme, no www., no path)
    company_id: str | None = None           # digits only, e.g. Czech IČO "12345678" (8 digits, zero-padded)

class SubjectSpec(BaseModel):
    raw: str                                # what the owner typed, e.g. "https://www.instagram.com/x/"
    handle: Handle
    platform: Platform | None = None        # None until resolved (input "@x" without a platform)
    anchor: Anchor = Field(default_factory=Anchor)
    candidate_id: str | None = None         # set when resolved
    status: Literal["pending", "resolved", "not_found"] = "pending"

class SetAside(BaseModel):                  # a namesake / look-alike / fan account the report does NOT use
    ref: str                                # "tiktok:kuba_jidlo" | "news:<id>"
    label: str                              # "TikTok @kuba_jidlo" | outlet + title
    kind: Literal["namesake", "look_alike", "fan_account"]
    reason: dict[str, str]                  # i18n, names the signals ("different city: Bratislava; no link between the accounts")
    source: SourceRef | None = None

class IdentityVerdict(BaseModel):
    status: Literal["confirmed", "likely", "uncertain", "not_found"]
    text: dict[str, str]                    # the sentence at the top of the report (section 5.3)
    supporting: list[IdentitySignal] = Field(default_factory=list)     # each with a source
    contradicting: list[IdentitySignal] = Field(default_factory=list)
    set_aside: list[SetAside] = Field(default_factory=list)
    anchor: Anchor | None = None
```

Additions to existing models (all with defaults):

```python
class Finding:            # + section literal gains "goal" (the per-criterion checks block)
    section: Literal["goal", "profile", "content", "engagement", "collabs", "claims", "news", "identity"]
    confidence: Confidence | None = None
    confidence_basis: dict[str, str] | None = None   # i18n, short: "platform label", "own caption", "single news item", "rule-based inference"
    aspect: str | None = None                        # one of ASPECTS
    tier: RelevanceTier | None = None                # for the CURRENT goal
    why_it_matters: dict[str, str] | None = None     # i18n one line for the CURRENT goal

class ClaimCheck:         # confidence already exists
    confidence_basis: dict[str, str] | None = None
    relevance: list[str] = Field(default_factory=list)   # criterion ids
    aspect: str | None = None
    tier: RelevanceTier | None = None
    why_it_matters: dict[str, str] | None = None

class ReportSection(BaseModel):
    id: str                                  # "identity" | "goal" | "content" | "engagement" | "collabs" | "claims" | "news" | "profile"
    title: dict[str, str]
    tier: RelevanceTier                      # highest tier among its items
    item_ids: list[str]                      # Finding / ClaimCheck ids shown expanded, in display order
    less_ids: list[str] = Field(default_factory=list)   # collapsed under "Less relevant for this goal"

class ReportDiff(BaseModel):
    candidate_id: str
    from_goal: dict[str, str]                # {"business_type", "goal", "brief_key"}
    to_goal: dict[str, str]
    added: list[str] = Field(default_factory=list)       # finding / claim ids new in this render
    removed: list[str] = Field(default_factory=list)
    moved_up: list[str] = Field(default_factory=list)    # tier rose (less -> related -> key)
    moved_down: list[str] = Field(default_factory=list)
    collapsed: list[str] = Field(default_factory=list)   # ids now in tier "less" that were not before
    claims_changed: list[dict] = Field(default_factory=list)   # {"id", "status": [before, after], "tier": [before, after]} when either differs
    checks_changed: list[dict] = Field(default_factory=list)   # {"criterion_id", "status": [before|None, after|None]}
    questions_added: list[dict[str, str]] = Field(default_factory=list)
    questions_removed: list[dict[str, str]] = Field(default_factory=list)
    outreach_changed: bool = False
    summary: dict[str, str]                  # i18n one line (section 6.7)

class VettingData(BaseModel):                # raw round-4 inputs: re-rendering for any goal needs no fetch
    vetted_at: UTCDatetime
    brief_key: str                           # goal the fetch + first LLM pass ran for
    posts: list[Post]                        # latest_posts + extra, sensitive-filtered, newest first
    cross_profiles: list[Profile]            # sensitive-filtered, minors removed
    provider_collabs: list[CollabEvidence]   # provider.collabs() (Meta etc.), competitor flags NOT trusted (re-marked per render)
    news_items: list[NewsItem]               # sensitive-filtered, ALL items incl. namesakes
    news_labels: dict[str, str] = Field(default_factory=dict)      # item id -> allegation | confirmed | neutral
    llm_claims: list[ClaimCheck] | None = None                     # validated LLM claims (goal-independent prompt); None = not run / failed
    llm_questions: list[dict[str, str]] | None = None              # LLM-phrased gap questions (goal-independent)
    llm_by_goal: dict[str, dict] = Field(default_factory=dict)     # brief_key -> {"outreach": {cs,en}?, "skeptic": [raw notes]?}
    modes: dict[str, str] = Field(default_factory=dict)            # step -> "llm" | "fallback" (claims, news, skeptic, questions, outreach)
    counts: dict[str, int] = Field(default_factory=dict)           # posts, comments, cross, news, news_set_aside, collabs_provider, sensitive_dropped

class Report:             # + (all default None / [] / {})
    identity_verdict: IdentityVerdict | None = None
    rendered_for: dict[str, str] | None = None     # {"business_type", "goal", "city", "brief_key"} of the CURRENT render
    summary: dict[str, str] | None = None          # i18n headline: the top key findings for this goal (never a score or verdict on the creator)
    sections: list[ReportSection] = Field(default_factory=list)   # display order for this goal
    less_relevant: list[str] = Field(default_factory=list)        # all collapsed ids
    text_source: dict[str, str] = Field(default_factory=dict)     # {"claims": "llm+rules"|"rules", "news": "llm"|"rules", "skeptic": "llm+rules"|"rules", "questions": "llm+template"|"template", "outreach": "llm"|"template"}
    method: list[dict[str, str]] = Field(default_factory=list)    # "How this report was built" i18n lines (section 6.8)
    last_diff: ReportDiff | None = None            # vs. the previous render (goal / criteria change); None after the first vetting
    # vetted_for stays: business_type of the goal the fetch ran for

class Candidate:          # +
    vetting_data: VettingData | None = None        # kept in the store snapshot; omitted from GET /api/runs/{id} and SSE payloads

class Run:                # +
    mode: Literal["discovery", "subject"] = "discovery"
    subject: SubjectSpec | None = None
    llm_usage: dict[str, int] = Field(default_factory=dict)   # filled by C's counter while the engine binds it: {"total": n, "<task group>": n}
```

`Finding.relevance` keeps its meaning: the criterion ids of the CURRENT criteria set. A recomputes it on every render.

## 4. Subject mode (A)

### 4.1 API

```
POST /api/subject
  body {
    "subject": str,                          # "@handle", "handle", instagram.com/<h>, tiktok.com/@<h> (any scheme / www / m. / query)
    "platform": "instagram"|"tiktok"|null,   # optional; else from the URL; else try instagram, then tiktok
    "anchor": {"city"?, "website"?, "company_id"?} | null,   # optional at API level (the chat always asks)
    "brief": Brief | "bakery" | "fitness" | null,
    "preset": "bakery" | "fitness" | null,   # alias of brief as a string
    "criteria": CriteriaSet | null,          # full control (tests / API users); wins over brief/preset
    "lang": "cs" | "en"                      # default "en"; overrides brief.lang
  }
  200 {"run_id", "mode": "subject", "subject": {"raw", "handle", "platform"}, "status": "started"}
  422 subject not parseable ("@handle or an instagram.com / tiktok.com profile link"; a post link -> "send the profile link")
  422 none of criteria / brief / preset
```

- Criteria come from `criteria` if given. Otherwise from a preset: the string, or `main._preset_for_brief(brief)` by keywords, built with `get_preset(name, lang)` and the brief overlaid. Otherwise from `chat.criteria_for_brief(brief)`. Everything then goes through `_check_criteria`.
- The local criterion city is `brief.city`, and `anchor.city` is never used for it: the anchor is the creator's location, the brief city is the business's.
- Use `discovery = DiscoveryQuery(city=brief.city)`. It is unused.
- Entry point, used by the endpoint and by `ApiChatContext.research_subject`:

  ```python
  def start_subject_run(subject: SubjectSpec, criteria: CriteriaSet) -> Run   # main.py; creates + saves the run, starts the "subject" task
  ```

Changes to the other routes for subject runs (`run.mode == "subject"`):

- `GET /api/runs/{id}` returns the Run with `mode`, `subject` and the new Report fields. It omits `candidates[*].vetting_data`, using `model_dump(mode="json", exclude={"candidates": {"__all__": {"vetting_data"}}})`. SSE `candidate.*` payloads omit it the same way. `store.save` keeps it.
- `POST /api/runs/{id}/goal` and `POST /api/runs/{id}/criteria` (any run mode):
  1. Recompute.
  2. Re-render every report whose candidate has `vetting_data`.
  3. Respond with an extra `"report_diffs": [ReportDiff, ...]`.
  4. Publish `report.diff` and `report.ready` per candidate.

  No fetch and no LLM. Discovery-run reports become goal-conditioned too.
- `POST /api/runs/{id}/restore` on a subject run returns 400 ("subject runs do not eliminate").
- `POST /api/runs/{id}/vet` on a subject run re-vets the subject (fetches again; `candidate_ids` optional).
- `GET /api/runs/{id}/status` adds:
  - `mode`;
  - `llm_requests_used` (= `run.llm_usage.get("total", 0)`);
  - `llm_budget` and `llm_budget_left` (process level, from `budget.usage_snapshot()`).
- `GET /api/runs` rows add `mode` and `subject` (handle or null).
- `GET /api/health` adds `**budget.usage_snapshot()` (section 9.2), wrapped in try/except like the other lazy imports.

### 4.2 Parsing (`compute/subject.py`, new, pure)

```python
def parse_subject(text: str, platform: str | None = None) -> tuple[Platform | None, str] | None
    """-> (platform or None, normalized handle) or None if not a profile reference.
    "@x" / "x" -> (platform arg or None, "x"); instagram.com/<h>[/...] -> ("instagram", h);
    tiktok.com/@<h>[/...] -> ("tiktok", h). Rejects IG non-profile paths (p, reel, reels, tv, stories,
    explore, accounts, direct) and TikTok video-only links without @handle. Handle charset [a-z0-9._],
    1-30 chars; lowercase; strips query/fragment. A URL platform conflicting with `platform` -> URL wins."""

def normalize_anchor(raw: Anchor | dict | None) -> Anchor | None
    """Strip; website -> host lowercase without scheme / www. / path; company_id -> digits only (drops a
    leading "CZ"); 6-8 digits zero-padded to 8; city stripped. Empty -> None."""

def anchor_text(anchor: Anchor | None, lang: str) -> str
    """"city Brno, website fitpeceni.example" / "město Brno, web fitpeceni.example"; "" for None."""
```

### 4.3 Run flow (`rounds/engine.py`: `async def run_subject(run, provider, emit) -> Run`)

The flow binds `bind_emit(recording_emit(...))`, `bind_llm_modes(run.llm_modes)` and `budget.bind_llm_usage(run.llm_usage)`, the same as `run_funnel`.

1. Emit `run.started`. Log the subject and anchor in both languages (`tr`).
2. **Resolve.** If `subject.platform` is set, call `provider.profiles([h], platform)`. Otherwise call it for `"instagram"`, then `"tiktok"`.
   - On no profile (or a minor):
     - set `subject.status = "not_found"`;
     - emit `subject.not_found {"subject": raw, "tried": [platforms], "reason": i18n}`;
     - log it, save, and emit `run.finished`.

     Store nothing about a minor.
   - On success:
     - add `Candidate(ref=CandidateRef(handle, platform, found_via=["manual"], source=profile.source))`;
     - set `subject.platform`, `subject.candidate_id` and `subject.status = "resolved"`;
     - emit `candidate.added` and `subject.resolved {"candidate_id", "platform", "handle"}`.
3. **Checks, rounds 1-3.** For each round r:
   1. Emit `round.started`.
   2. Call `module.prepare(run, [c], provider, emit)`.
   3. Evaluate EVERY enabled criterion of round r and replace that round's results. Never eliminate.
   4. Emit `candidate.updated` and `round.finished {"round": r, "entered": 1, "remaining": 1}`.

   A private account gives `unknown` results and the run continues.
4. **Vetting.** Set `c.status = "finalist"`. Run `r4_vetting.prepare(run, [c], provider, emit)` (section 6.1). Evaluate the round-4 results, then render the report (the order is A's choice, see 6.2). Emit `report.ready`, `round.finished` for round 4, and `run.finished`. Save after every step.

`recompute(run, criteria)` with `run.mode == "subject"`:

- Re-evaluate all rounds 1-4 for the candidate with no elimination. Status stays `finalist`.
- Re-render the report with `previous=` the old report, and set `last_diff`.
- Return the usual Diff (empty `dropped`/`returned`) plus `"report_diffs": [ReportDiff]`.

`fill_missing` is a no-op for subject runs.

### 4.4 Events

These are added to the run stream. All existing events stay.

- `subject.resolved {candidate_id, platform, handle}`
- `subject.not_found {subject, tried, reason}`
- `report.diff {candidate_id, diff: ReportDiff}`, after a goal or criteria change, before the matching `report.ready`.

Chat stream changes (A emits these from main.py):

- `criteria.updated {criteria, run_id}`, emitted by `research_subject` right after the run is created, so the UI binds the run immediately (the frontend's `findRunId` reads `run_id`).
- `done {..., lang}`: main.py passes through a `lang` key that B puts in its `done` data.

## 5. Identity resolution with the anchor (A, `compute/identity.py` additions)

### 5.1 Signals

```python
def anchor_signals(profile: Profile, posts: list[Post], anchor: Anchor | None, *, cross: list[Profile] = (),
                   lang: str = "cs") -> list[tuple[str, IdentitySignal]]
    """kinds: anchor_website | anchor_company_id | anchor_city_bio | anchor_city_posts (supports=True)
    and anchor_city_other (supports=False: bio / location names another city from identity._CITIES and no
    anchor-city signal). Website: normalized host found in profile.external_urls or bio, or in a MATCHED
    cross profile's external_urls. company_id: digits found in bio / external URLs / captions. City:
    metrics.city_pattern (handles Czech cases: "Brnem", "v Brně"). "Another city" uses identity._CITIES
    with word-start matching on folded text and skips the ambiguous stem "most" (an English word).
    Every signal carries a SourceRef with a quote."""

def look_alike_signals(other: Profile, anchor: Anchor | None, *, lang: str) -> list[IdentitySignal]
    """For a cross-platform profile: another city in its bio than anchor.city -> supports=False
    ("bio says Bratislava, the anchor is Brno"). Added to that IdentityMatch's signals before
    identity_status, so a same-name account in another city ends up rejected or uncertain."""

def identity_verdict(profile: Profile | None, anchor: Anchor | None, anchor_sigs: list[tuple[str, IdentitySignal]],
                     identity: list[IdentityMatch], namesakes: list[IdentityMatch], news_items: list[NewsItem],
                     *, lang: str = "cs") -> IdentityVerdict
```

### 5.2 Verdict rules (deterministic)

| status | when |
|---|---|
| `not_found` | `profile is None` |
| `confirmed` | (anchor website or company id matched) OR (anchor city in bio AND >= 1 cross-platform `matched` with a link), AND no `anchor_city_other` |
| `likely` | anchor city matched (bio or posts) only; OR no anchor given but >= 1 cross-platform `matched`; AND no contradiction |
| `uncertain` | anchor given and nothing matched; OR any `anchor_city_other`; OR no anchor and no cross-platform match |

`set_aside` lists the following, each with the signals as its reason:

- every `IdentityMatch` with status `rejected`: kind `fan_account` if a fan signal is present, else `look_alike`;
- every `uncertain` cross-platform account: kind `look_alike`;
- every namesake news item (`match_news`): kind `namesake`.

### 5.3 Verdict text templates (en; A writes the cs equivalents)

- confirmed: `We are confident @{h} is the creator you mean because {reasons}.`
- likely: `@{h} is probably the creator you mean: {reasons}. {missing}`, where missing is e.g. "Their website or company ID would confirm it."
- uncertain: `We could not confirm @{h} is the creator you mean: {problems}. Check the handle or give another anchor (city, website or company ID).`
- not_found: `We found no public profile @{h} on {platforms}.`
- If `set_aside` is not empty, append: ` We set aside {n} look-alike or namesake {source|sources}: {labels}.`

`reasons` are the supporting signal texts joined with ", ", for example: "the website fitpeceni.example is on the profile, TikTok @fit_peci_s_klarou links back to this profile".

Identity findings (section `identity`) are built as today, plus `f:anchor:<field>` facts for matched anchor fields and `g:anchor:<field>` gaps for unmatched ones. A company-id gap reads: "Company ID 12345678 does not appear in the public profile; we did not query the business register."

## 6. Goal-conditioned report (A)

### 6.1 Where the logic lives

- **`rounds/r4_vetting.py` `vet_candidate`** (async, I/O + LLM). It fetches exactly as today, then:
  - builds `VettingData`;
  - runs the LLM steps;
  - stores their results in `VettingData`;
  - sets `candidate.vetting_data`;
  - calls `render_report`.

  The LLM steps (each falls back, each labeled with `record_mode("vetting", ...)`) are:
  1. `vetting.news_findings`, which gives `news_labels`;
  2. `vetting.claims`, which gives `llm_claims` (A removes `competitor=` from the claims prompt so it is goal-independent and cache-stable);
  3. LLM gap questions, which give `llm_questions`;
  4. `vetting.skeptic` and `vetting.outreach` for the current goal, which give `llm_by_goal[brief_key]`.

  Only these requests are made (5 at most). Order: render first, so the questions and skeptic can read the gaps and digest; store the LLM text; then render again.
- **`rounds/report.py`** (new, PURE: no I/O, no LLM, no `utcnow()`, no randomness):

```python
def brief_key(brief: Brief) -> str
    """short_hash(brief.model_dump_json(exclude={"lang"}))."""

def render_report(criteria: CriteriaSet, candidate: Candidate, data: VettingData, *,
                  anchor: Anchor | None = None, previous: Report | None = None) -> Report
    """Same inputs -> identical Report (ids, order, texts). Reads candidate.profile / metrics / results /
    topic_labels / sensitive_filtered. Re-marks competitors on a COPY of the timeline built from
    data.posts + data.provider_collabs (compute.collabs.extract_collabs + merge_timeline + mark_competitors
    for criteria.brief). Uses LLM text only from data (llm_claims, llm_questions, llm_by_goal[brief_key]).
    With previous: sets last_diff = diff_reports(previous, new)."""

def diff_reports(before: Report, after: Report) -> ReportDiff     # pure
```

- **Legacy fallback.** `r4_vetting.refresh_for_brief` stays for reports without `vetting_data` (old snapshots). `engine.recompute` calls `render_report` when `c.vetting_data` exists, and `refresh_for_brief` otherwise.
- **Determinism test (A).** Render twice and compare `model_dump_json`. Render for bakery, then fitness, then bakery again: the third equals the first, except `last_diff`.

### 6.2 What a render contains (in order)

1. `identity_verdict` (section 5).
2. **Goal checks** (section `"goal"`): one finding per enabled criterion of rounds 1-4, built from `candidate.results`.
   - id: `f:check:<criterion_id>` (a fact citing the result's sources), or `g:check:<criterion_id>` for status `unknown` or no sources.
   - text: `"{label}: {value} (needs {threshold})"`, plus an en/cs status word. Results come from the engine's evaluation; round 4 needs the re-marked timeline, so evaluate round 4 on the rendered timeline. Re-rendering once after evaluation is fine.
3. **Goal fit fact** `f:fit:topics` (section `content`, aspect `content_fit`, always tier `key`, when `topic_share` is enabled):
   - text: "{n} of {total} recent posts ({pct}) are about {this goal's topics}: what matters for a {business_type} (needs {min_share})";
   - sources: up to 5 `post_ref`s of matching posts (via `topic_labels`).
4. All existing finding families (`build_findings` + `collab_findings`), with `relevance` recomputed for the current criteria.
5. Claims: the rule floor `_fallback_claims(profile, data.posts, timeline)` merged with `data.llm_claims` (existing merge: LLM first, then floor claims the LLM did not cover), then the goal layer (6.4).
6. `news` from `data.news_items` minus rejected namesakes, labeled from `data.news_labels` (missing label means the keyword rule).
7. Skeptic:
   - `vetting.apply_skeptic_rules(report)` always;
   - `vetting.apply_llm_skeptic(report, raw)` when `llm_by_goal[brief_key]["skeptic"]` exists.
8. Questions (6.5), outreach (6.6), `summary`, `sections`, `less_relevant`, `text_source`, `method` (6.8), `rendered_for`, `not_checked` (unchanged), `sensitive_filtered`.

### 6.3 Relevance tier, aspect, why_it_matters

`aspect` is `CRITERION_ASPECT` of the first relevant criterion. Otherwise it comes from the section:

| section | aspect |
|---|---|
| identity | identity |
| news | reputation |
| collabs | competitors |
| claims | competitors |
| `g:pricing` | practical |

Tier rules are checked in this order. The first match wins.

1. **`key`:**
   - identity contradictions (`anchor_city_other`, signals behind an `uncertain` verdict);
   - `f:fit:topics`;
   - any finding whose relevant criterion result is `fail` (not waived);
   - a collab fact or inference involving a brand that `is_competitor` for the CURRENT brief;
   - a claim that is `conflicts_with_record` and has an enabled relevant criterion or competitor evidence;
   - a news item labeled `allegation` about the creator (not a namesake).
2. **`less` (explicit):**
   - goal checks with status `pass` for the kinds `public_account`, `active_recently`, `not_brand_account` and `language_cs`;
   - collab facts with a non-competitor brand that are labeled (disclosed True) or mention-only, and their inferences.
3. **`related`:**
   - relates to an enabled criterion of the current goal (any other result);
   - any other identity, news or claims item;
   - gaps with an enabled relevant criterion;
   - `g:pricing` and `g:demographics` (the latter is a hard-line statement that is always visible);
   - undisclosed collab facts (disclosed False).
4. **`less` (default):** everything else. That means findings whose relevance has no enabled criterion, and gaps without one.

- An inference takes the highest tier of its `based_on` facts. Inferences under rule 2 stay `less`.
- **`why_it_matters`** (i18n, one line):
  - If the primary relevant criterion has a non-empty `why`, use it, prefixed with "For your {business_type}: ".
  - Otherwise use a per-aspect template.
  - Competitor collab: "{brand} is your competitor: a creator who promoted them recently is less credible for you."
  - Tier `less`: "Less relevant for your {business_type}: {reason}", where reason is e.g. "the brand is not a competitor and the post is labeled" or "not linked to any of your criteria".
- Exclusivity claims for a brand whose name contains a keyword of the current goal's category (reuse the bakery/fitness keyword lists from main.py, moved into `rounds/report.py`) get tier `key`. Their why reads: "An exclusivity deal with {brand}, which looks like a business in your category (name match, a guess), may rule out working with you."

### 6.4 Claims goal layer

- `relevance`:
  - exclusive/partner claims, and LLM claims citing collab evidence: `no_competitor_collab` (+ `discloses_ads` if paid kinds);
  - unpaid claims: `discloses_ads`;
  - follower claims: `followers_range`.

  Only ids enabled in the current criteria count.
- `status` stays evidence-based. It is re-derived each render from the re-marked timeline: rule floor + LLM claims re-validated with `vetting.validate_llm_claims` against the current evidence ids when needed. It changes only when the evidence does.
- `claims_changed` reports both status changes and tier changes.

### 6.5 Questions (deterministic for any goal; cached LLM phrasing added)

The order is:

1. `vetting.evidence_questions(report, profile)`: conflicts, unlabeled posts.
2. Goal templates for key-tier items:

| trigger | question (en) |
|---|---|
| `topic_share` fail/unknown | "Would you make a post about our {business_type} even though {goal topics} are not your main topic?" |
| `local_signal` fail/unknown | "How many of your followers are in {city}? Could you share the city statistics from the app?" |
| `formats` fail | "Would you film a short video at our {business_type}?" |
| competitor collab | "You worked with {brand} ({date}). Is that still running, and does it include exclusivity?" |
| `discloses_ads` fail | "How do you label paid posts? We found {n} posts with a brand and no ad label." |
| `max_commercial_share` fail | "How many paid posts do you publish a month?" |
| `followers_range` fail and budget_hint | "Our budget is {budget_hint}. Does that fit how you price a collaboration?" |

3. `data.llm_questions` (or `_fallback_questions(gaps)`).
4. Always: demographics and pricing.

Dedupe by `cs` text and keep at most 8.

### 6.6 Outreach

- `llm_by_goal[brief_key]["outreach"]` if present.
- Otherwise `vetting.outreach_template(criteria.brief, candidate)` (deterministic). It must mention the current business type and goal, so it changes with the goal.
- The draft is never sent.

### 6.7 Diff summary (i18n one line, en example)

"Goal changed from bakery to fitness studio: 2 findings became key (ProteoMax is now a competitor), 4 moved to less relevant, 1 claim changed, 3 new questions, outreach draft rewritten."

Omit any zero parts. If nothing changed: "The report is the same for this goal."

### 6.8 `method` ("How this report was built")

These are i18n lines, deterministic from `data.counts`, `data.modes` and the run.

1. Subject and how it was resolved, plus the anchor.
2. What was fetched, with counts and the live/cache/mock mode.
3. "Filtered before storage: {n} items on sensitive topics (count only)."
4. Identity: number of supporting signals, and what was set aside.
5. "Every fact links to its source; inferences say which facts they rest on; gaps say what we could not check."
6. "Ordered for your goal: {business_type}{ in city}. {k} findings are collapsed as less relevant."
7. AI vs rules per step, from `text_source`. Add "Switching the goal re-orders and rewrites this report from the data already fetched: no new requests." when applicable.

### 6.9 Ordering

- `sections`:
  - `identity` first, then `goal`;
  - then the others sorted by (number of key items descending, then the default order: claims, collabs, content, engagement, news, profile).
- Within a section: key, then related, then original order. `less` items go to `less_ids`.
- `findings` (the flat list the current UI reads) is re-ordered to the same display order: all expanded items first, then the collapsed ones.
- `claims` are ordered by tier, then status (conflicts first).
- `summary` joins the short texts of the first 3 key findings.

## 7. Confidence per finding (A, set in render; table is normative)

| finding | confidence | basis (en) |
|---|---|---|
| followers / posts count, business category, formats, post dates / frequency | high | "platform profile data" / "platform media type" / "post dates" |
| `f:fit:topics`, `f:topics` | medium if `llm_modes["topics"]` is llm (or mixed); low if fallback | "AI topic labels on {n} captions" / "keyword rules on {n} captions" |
| commercial share | medium | "labels, ad hashtags and discount codes in captions" |
| engagement rate, spikes | medium (low if < 5 posts) | "public like and comment counts, {n} posts" |
| cs comment share | medium if >= 30 comments, else low | "language detection on {n} comments" |
| generic comments | low | "rule-based comment classification" |
| local signals | medium if >= 3, else low | "place tags and captions" |
| collab fact with `paid_label` / `meta_branded` / `coauthor` | high | "platform paid-partnership label" / "Meta branded content library" / "platform co-author field" |
| collab fact, other kinds | medium | "own caption" |
| identity matched with link/backlink | high | "the profiles link to each other" |
| identity uncertain | low | "similar name or handle only" |
| identity rejected (fan / region / other city) | medium | "fan-account markers" / "account region" / "city in bio" |
| anchor website / company id matched | high | "anchor found on the profile" |
| anchor city in bio | medium; posts only: low | "anchor city in bio" / "anchor city in post locations or captions" |
| news fact naming the handle | medium | "single news item" (high if >= 2 outlets agree) |
| news fact naming only the name | low | "name match only" |
| namesake fact | medium | "different context in the article" |
| goal check fact | inherits the confidence of the underlying finding family above (medium if unclear) | "check on {value source}" |
| inference | min(confidence of based_on), capped at medium | "rule-based inference from {n} facts" |
| gap: structurally never public (demographics, reach, pricing, private insights) | high | "never public on the platform" |
| gap: not found (news, cross-platform, comments, anchor) | medium | "not found in the sources we checked" |

Every ClaimCheck also gets `confidence_basis`:

- rule claims: "own caption vs. collaboration record", or "profile follower count";
- LLM claims: "AI reading of the caption, checked against the record".

## 8. Chat (B)

### 8.1 New tool `research_subject` (B owns the schema and validation)

```python
_tool("research_subject",
  "Check ONE specific creator the owner named (an @handle or an Instagram/TikTok profile link) for the owner's "
  "goal. Fetches the public profile, posts, comments, other-platform accounts, collaborations and news, runs "
  "the goal's criteria as checks (nothing is eliminated, no score) and builds a sourced report. Before calling, "
  "get what is missing and nothing else: an anchor (city where the creator is based, their website, or a "
  "company ID such as the Czech IČO) and the goal (business type, city, what they want).",
  {"subject": {"type": "string", "description": "@handle or profile URL exactly as the owner wrote it"},
   "anchor": {"type": "object", "properties": {"city": {"type": "string"}, "website": {"type": "string"},
              "company_id": {"type": "string"}}, "additionalProperties": False},
   "brief": _BRIEF_SCHEMA,
   "preset": {"type": "string", "enum": ["bakery", "fitness"]}},
  ["subject", "brief"])
```

- B validates input: subject is a str of at most 300 chars; anchor values are str of at most 200 chars; brief goes through `_validate_brief` + `sanitize_brief`. Invalid input returns `{"ok": False, "error": ...}` to the model without calling ctx.
- `TOOLS` order: the existing 7, then `research_subject` (update `test_tools_shape`).

`ChatContext` protocol (B adds; A implements in `ApiChatContext`; A adds `research_subject = _unavailable` to `_GoalCaptureContext`):

```python
async def research_subject(self, subject: str, anchor: dict | None = None, brief: Brief | None = None,
                           preset: str | None = None) -> dict: ...
```

Result (A returns it; texts resolved to `ctx.lang`). B's fallback and prompt rely on these keys:

```json
{"ok": true, "run_id": "r_…", "status": "finished" | "running" | "error",
 "subject": {"raw": "...", "platform": "instagram", "handle": "...", "candidate_id": "...", "status": "resolved" | "not_found" | "pending"},
 "anchor": {"city": "Brno", "website": null, "company_id": null},
 "criteria_source": "preset:bakery" | "generic" | "request",
 "identity": {"status": "confirmed" | "likely" | "uncertain" | "not_found", "text": "We are confident ..."},
 "checks": {"pass": 9, "fail": 2, "unknown": 2,
            "items": [{"criterion_id", "label", "status", "value", "threshold"}]},
 "key_findings": [{"id", "kind", "text", "confidence", "why"}],
 "less_relevant": 7,
 "claims": [{"claim", "status", "confidence"}],
 "questions": ["..."],
 "outreach_draft_ready": true,
 "note": "Subject check: nothing is eliminated and there is no score."}
{"ok": false, "error": "...", "missing": ["subject" | "brief" | "anchor"]}
```

- `checks.items`: fail and unknown first, at most 8. `key_findings`: at most 5. `claims`: at most 3. `questions`: at most 3.
- A: `research_subject` sets `session.run_id` and `session.criteria`, emits `criteria.updated {criteria, run_id}`, waits up to `CHAT_TOOL_WAIT` like `run_rounds`, then returns. An anchor is not required by A.
- A: on a subject run, `change_goal`, `propose_criteria` and `update_criterion` results gain `"report_diffs": [{"candidate_id", "handle", "summary": <lang text>, "added": n, "removed": n, "moved_up": n, "moved_down": n, "claims_changed": n, "questions_added": n, "outreach_changed": bool, "key_findings": [<lang text>, at most 3]}]`.
- A: `run_rounds` on a subject run returns `{"ok": False, "error": "this run checks one subject; use research_subject for another creator or change_goal for another goal"}`.
- A: `start_deep_vetting` on a subject run re-vets the subject.

### 8.2 Subject entry in the conversation (fallback and live)

- **Detection (B).** An owner message containing an `@handle` or an instagram.com / tiktok.com profile URL is a subject request when:
  - (a) it is the first owner message, or it contains a check verb (check, vet, research, look at, who is, prověř, zkontroluj, podívej se na, kdo je); and
  - (b) the pending question is not the competitor question (q5). Competitor answers contain handles too.

  B may validate tokens with `app.compute.subject.parse_subject`.
- **Extraction (B, from the same or later messages):**
  - Business and goal: `pick_preset` keywords, then `_business_from`, plus city via `find_city`. An explicit "for my bakery in Brno" fills `brief.business_type` and `brief.city`.
  - Anchor:
    - a non-instagram/tiktok URL or domain becomes `website`;
    - 6-8 digits, optionally after "IČO", "ICO" or "company ID", become `company_id`;
    - "based in X", "from X", "lives in X", "je z X", "z X" (subject context) become `city`.

  The business city is NOT the anchor unless the owner says the creator is based there.
- **Ask only what is missing, one question per turn, with these English texts.** B writes the cs equivalents.
  - Anchor: "To check the right @{h} and not a namesake or look-alike account: where is the creator based (city), or what is their website or company ID (IČO)? You can also say “skip”."
  - Goal: "What is your business and what should the creator help with? For example: “my bakery in Brno, more people in the shop”."

  "skip", "nevím" and "don't know" mean anchor None. The verdict then caps at likely or uncertain, and the reply says so.
- **Run.** Call `ctx.research_subject(subject, anchor, brief, preset)`. The preset brief is `presets.preset_brief(name, lang)` with the owner's city if one was given; otherwise `chat.criteria_for_brief(brief)`.
- **Reply, in this order:**
  1. the identity verdict text;
  2. up to 3 key findings, each tagged fact, inference or gap, with its confidence;
  3. the counts of failing and unknown checks;
  4. "Nothing was eliminated and there is no score: these are checks with sources.";
  5. the hint "Try “what about my fitness studio?” to see how the report changes for another goal."

  `not_found`: say so and ask for the right handle or link.
- **Goal switch in a subject run.** These phrases trigger `ctx.change_goal(brief)`:
  - existing `_RX_GOAL` phrases;
  - "what about my X", "for my X instead", "a co pro moje X", "místo toho X".

  Reply with `report_diffs[0].summary` and its `key_findings`.
- **`_board_state(ctx)` (live model note).** Mention `run.mode` and `run.subject.handle` (via getattr), so the model uses `change_goal`, not `run_rounds`, on a subject run.

### 8.3 English

- `fallback_turn` is a complete scripted interview in English when the effective language is `en`. That covers every question, hint, confirmation, run summary, vetting offer, refusal, goal change, outreach and explanation text, plus the subject flow.
- English answers must parse: business type, "in Brno", audience, goal, "up to 20k CZK" / "CZK 20,000", competitors such as "Bakery B @pekarna_b" or "no competitors".
- The English generic brief and presets use `preset_brief(name, "en")`, so the English UI never shows "pekárna".
- **Effective language:**
  - if the first owner message of the session is detected confidently (`compute.language.detect_language`, at least 3 words, or a clear English/Czech stopword majority), use that language;
  - otherwise use the UI `lang`.

  Set `ctx.lang = effective` at the start of every turn, before any tool runs, so A's tool results use it. Put `"lang": effective` in `done`. Set `brief.lang` to it.
- **Live prompt.** `CHAT_SYSTEM` gains:
  - reply in the owner's language;
  - subject mode: when the owner names a specific creator, do not run the discovery interview; ask only for the missing anchor and goal, then call `research_subject`;
  - summarise the verdict first, separate facts, inferences and gaps, and never score or rank;
  - on a goal switch, call `change_goal` and summarise `report_diffs`.
- Czech behavior and existing tests stay unchanged.

### 8.4 LLM budget hooks (B uses C's API, section 9.2)

- At the start of `chat_turn`: if `not budget.llm_task_enabled("chat")`, run `fallback_turn` instead. main.py keeps calling `chat_turn` whenever a provider is configured.
- Anthropic path: before each `client.messages.stream`, call `if not await budget.spend("chat"): raise budget.BudgetExhausted("chat")`. Catch `budget.BudgetExhausted` next to `openrouter.OpenRouterError`, with the same handling: fallback if nothing was shown yet, apology otherwise.
- OpenRouter path: `openrouter.stream_chat` spends itself (C). It raises `OpenRouterError(kind="budget")` when exhausted.

### 8.5 B's tests (`tests/test_chat_subject.py`)

- FakeCtx-based tests:
  - detection vs. a competitor answer;
  - anchor and goal extraction;
  - one question per missing item;
  - "skip";
  - English interview end to end (bakery);
  - language detection;
  - goal switch phrase routing;
  - budget-exhausted fallback (monkeypatch `budget.spend`).
- One end-to-end test through `app.main` with `httpx.AsyncClient` (the same pattern as `test_api.py`): fallback chat → subject run. Skip it with `pytest.skip` while `ApiChatContext` has no `research_subject`.

### 8.6 Presets in English (A writes, B uses)

```python
def preset_brief(name: PresetName, lang: Lang = "cs") -> Brief
def get_preset(name: PresetName, lang: Lang = "cs") -> CriteriaSet     # lang="cs" = byte-identical to today
```

The English briefs keep the same city and competitors as the Czech ones:

| | bakery | fitness |
|---|---|---|
| `business_type` | "bakery" | "fitness studio" |
| `audience` | "families and young people in Brno" | "people in Brno who want to start exercising" |
| `goal` | "more people in the shop, launch a new sourdough bread" | "more sign-ups for a trial class" |
| `budget_hint` | "up to CZK 20,000" | "up to CZK 30,000" |
| `lang` | "en" | "en" |

## 9. LLM budget (C)

### 9.1 Config (`config.py`)

```
OPENROUTER_TASKS     comma list of task groups OpenRouter may serve; default "chat,vetting,news".
                     Groups: chat, vetting (claims, skeptic, questions, outreach), news (news labels),
                     topics, sensitive. "all" = every group, "none" or "" set explicitly = no LLM task.
                     Anthropic ignores it (all tasks), as today.
OPENROUTER_BULK_TASKS  deprecated: "1" with OPENROUTER_TASKS unset = "all"; "0" is ignored (the new
                     default applies) with one warning log line.
LLM_REQUEST_BUDGET   max LLM HTTP requests per process. Unset: 40 when the provider is openrouter,
                     unlimited for anthropic. An integer N >= 0 applies to either provider (0 = no LLM
                     requests). "unlimited" / "off" / "-1" = no cap.
```

New `Settings` fields:

- `openrouter_tasks: frozenset[str]`
- `llm_request_budget_raw: str | None`
- property `llm_request_budget -> int | None`
- `openrouter_bulk_tasks` stays as a derived property for old callers.

C also updates the docstring and `.env.example`.

### 9.2 `llm/budget.py` (new; final public API, used by A, B and C)

```python
TASK_GROUPS: dict[str, str] = {"chat": "chat", "claims": "vetting", "skeptic": "vetting", "questions": "vetting",
                               "outreach": "vetting", "vetting": "vetting", "news": "news",
                               "topics": "topics", "sensitive": "sensitive"}
ALL_GROUPS: tuple[str, ...] = ("chat", "vetting", "news", "topics", "sensitive")

class BudgetExhausted(Exception):
    def __init__(self, task: str): ...           # .task, .reason = "LLM budget exhausted"

def task_group(task: str) -> str                 # unknown task -> itself
def llm_task_enabled(task: str) -> bool          # provider None -> False; anthropic -> True; openrouter -> group in openrouter_tasks
def request_budget() -> int | None               # None = unlimited
def requests_used() -> int                       # this process
def budget_left() -> int | None
async def spend(task: str) -> bool               # one HTTP request about to leave the process: if budget left,
                                                 # count it (process total, per group, bound run usage) and
                                                 # return True; else False and, once per group per process,
                                                 # log WARNING + emit_log("LLM budget exhausted ({used}/{budget}):
                                                 # {group} uses the deterministic fallback", actor="llm")
@contextmanager
def bind_llm_usage(target: dict[str, int])       # ContextVar like bind_llm_modes; spend() also adds to
                                                 # target["total"] and target[group]
def usage_snapshot() -> dict                     # {"llm_requests_used": int, "llm_budget": int | None,
                                                 #  "llm_budget_left": int | None, "llm_budget_exhausted": bool,
                                                 #  "llm_tasks": [enabled groups for the active provider],
                                                 #  "llm_requests_by_task": {group: n}}
def reset_budget() -> None                       # tests; client.reset_client() calls it too
```

### 9.3 Where requests are counted

The rule: whoever issues the HTTP request calls `spend` once per attempt.

- `client.structured(schema, *, system, user, model=None, max_tokens, effort, task)` keeps the same signature. New order inside:
  1. `if not llm_task_enabled(task): return None`. This is silent (one INFO log per group per process). The caller labels the result fallback, as today.
  2. **Structured cache.**
     - Key: `sha1(provider | task | schema.__name__ | system | user)`, stored at `data/llm/structured-<key>.json` via `cache_get/cache_put`.
     - A hit returns `schema.model_validate(cached)` with 0 requests.
     - Only validated successes are stored.
  3. `if not await spend(task): return None`.
  4. The call, as today. The Anthropic path spends again before the beta-less retry in `_parse_call`. The OpenRouter path does not spend inside `complete_json`: `structured()` already spent.
  5. On success: `cache_put`.
- `openrouter.stream_chat(...)` calls `if not await budget.spend("chat"): raise OpenRouterError("LLM budget exhausted", kind="budget")` before taking the rate-limit slot.
- B spends for the Anthropic chat stream (8.4).
- A: `main._agent_criteria` (used by `POST /goal` for non-preset briefs) runs only when `budget.llm_task_enabled("chat")`. Without it:
  - subject runs use `chat.criteria_for_brief(brief)`, so a new non-preset goal still gets its own topics;
  - discovery runs keep today's `kept_current` behavior.
- A's engine binds `bind_llm_usage(run.llm_usage)` in `run_funnel`, `run_vetting`, `run_subject` and `fill_missing`. A's main.py exposes the snapshot (4.1).

Chat turns are not cached: they are a conversation, and they count against the budget.

The free-tier run plan, with the defaults:

| step | requests |
|---|---|
| chat | about 2 per owner turn with a tool call |
| subject vetting | at most 5 (claims, news, skeptic, questions, outreach) |
| goal switch render | 0 |
| topics and sensitive | rule-based |

A full demo is about 15 requests. A replay of the same run makes 0 bulk requests, because they are all cached.

### 9.4 C's tests

`tests/test_llm_budget.py` covers:

- the defaults (openrouter 40, anthropic unlimited);
- parsing of `OPENROUTER_TASKS`, including deprecated `OPENROUTER_BULK_TASKS=1`;
- the group mapping;
- `llm_task_enabled` per provider;
- exhaustion: `structured` returns None and logs exactly once;
- a cache hit costs 0;
- `stream_chat` raises a budget error;
- `bind_llm_usage` counts into the target;
- the `usage_snapshot` shape.

C also updates `test_openrouter.py` for the task list.

In `conftest.py`, C adds `"OPENROUTER_TASKS"` and `"LLM_REQUEST_BUDGET"` to `_LLM_DEFAULTS` and calls `budget.reset_budget()` in the autouse fixture. The counter is per process, so without the reset, tests would leak budget into each other.

## 10. Cross-team signatures (summary)

| Provider | Name | Used by |
|---|---|---|
| A | `models.*` additions (section 3) | B (read via getattr), C (none) |
| A | `compute.subject.parse_subject(text, platform=None)`, `normalize_anchor(raw)` | B |
| A | `presets.preset_brief(name, lang)`, `presets.get_preset(name, lang="cs")` | B |
| A | `ApiChatContext.research_subject(subject, anchor=None, brief=None, preset=None) -> dict` (shape 8.1) | B (through ChatContext) |
| A | tool results `report_diffs` on change_goal / propose_criteria / update_criterion | B |
| A | `chat.done` passes `lang` through; `criteria.updated {criteria, run_id}` | B, frontend |
| B | `ChatContext.research_subject` protocol method + `TOOLS` entry | A implements |
| B | `chat.criteria_for_brief(brief, refused=None)` unchanged | A |
| C | `budget.*` (9.2) | A (bind_llm_usage, usage_snapshot), B (llm_task_enabled, spend, BudgetExhausted) |
| C | `client.structured(...)` unchanged signature, gated + cached | A (vetting), topics, sensitive |
| C | `openrouter.OpenRouterError(kind="budget")` from `stream_chat` | B |

## 11. Priorities if time runs short

- **A:**
  - P0:
    - models;
    - `compute/subject.py` + presets;
    - `run_subject` + `POST /api/subject`;
    - `VettingData` + `render_report` with tiers, why, confidence and identity verdict;
    - goal change → re-render + `report_diffs`;
    - `research_subject` in ApiChatContext.
  - P1: goal questions table, `method`, `summary`, health/status usage fields.
  - P2: exclusivity category heuristic, re-vet on subject runs.
- **B:**
  - P0: tool + protocol + live prompt; fallback subject flow (detect, ask anchor/goal, run, reply); English interview.
  - P1: language detection, goal-switch phrases, done.lang.
  - P2: polish.
- **C:**
  - P0: `budget.py`, gating + spend + cache in `structured()`, `stream_chat` spend, config, conftest reset.
  - P1: health snapshot fields, .env.example.
  - C finishes first. Then C runs the full suite and reports cross-team failures in its final message, without editing others' files.

## 12. Frontend notes (out of scope for A/B/C; for the integration step)

- **New report fields:**
  - show `identity_verdict.text` at the top of the drawer, with `set_aside` listed under it;
  - render `sections` in order, and `less_ids` under a collapsed "Less relevant for this goal";
  - every finding shows a `confidence` pill with `confidence_basis` and the `why_it_matters` line;
  - add a "How this report was built" (`method`) panel;
  - `text_source` labels.
- **Goal change:** show `report.diff` / `last_diff`: added, collapsed, moved up, claim changes, new questions.
- **Subject entry:** a form calling `POST /api/subject` with subject, anchor (city / website / company ID), preset or brief, and lang.
- **Header:** `llm_requests_used / llm_budget` from `/api/health`.
- **Defaults:** the chat sends `lang`, and the UI follows `done.lang`. Default the UI to English for the jury.
