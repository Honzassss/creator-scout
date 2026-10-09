# Creator Scout: architecture and contracts

Build spec for the hackathon app. Product plan: [brand-fit-cz.md](brand-fit-cz.md), screens: [kostra-aplikace-cz.md](kostra-aplikace-cz.md), Apify handoff: [apify-pro-krystofa.md](apify-pro-krystofa.md).

**Two entry points.** *Discovery* finds and narrows down creators for a goal (rounds 0-4). *Subject mode* checks one named creator: the input is a person or account, one anchor (city, website or company ID such as the Czech IČO) and a goal; the output is a report where every claim links to a source, fact is split from inference, gaps are stated and every finding has a confidence level. The same subject with a different goal gives a different report. Section 5a describes subject mode, the goal-conditioned report, confidence and the LLM budget as built; the detailed build contract is [subject-mode.md](subject-mode.md).

**Ownership.** Kryštof owns everything that calls Apify (`backend/app/sources/apify_provider.py`). The rest of the app never imports `apify_client`; it only sees the normalized models below through the `SourceProvider` protocol. The app must run end-to-end with no keys at all (`SOURCE_MODE=mock`, LLM fallback), so UI and logic never wait for live data.

## 1. Repo layout

```
backend/
  app/
    main.py              FastAPI app, routes, SSE
    config.py            env: SOURCE_MODE, LLM_PROVIDER, keys, OPENROUTER_TASKS, LLM_REQUEST_BUDGET, models, data dir
    models.py            ALL pydantic models (this file is the contract)
    store.py             run state: in-memory + JSON in data/runs/<run_id>.json
    events.py            SSE event bus per run
    sources/
      base.py            SourceProvider protocol + DiscoveryQuery
      mock_provider.py   reads fixtures/, every SourceRef.mode = "mock"
      cache.py           CachedProvider(inner): hash(method,args) -> data/cache/<hash>.json, mode "cache" on hit
      apify_provider.py  Kryštof: real actors -> normalized models, mode "live"
    compute/
      metrics.py         engagement, frequency, formats, commercial share, local signals
      language.py        comment language (lingua), generic/emoji-only detection
      collabs.py         brand mentions, coauthors, ad hashtags, discount codes -> CollabEvidence
      identity.py        cross-platform identity, namesakes, anchor signals, identity verdict
      subject.py         parse_subject / normalize_anchor / anchor_text (subject-mode input)
    rounds/
      engine.py          run_funnel(), run_subject(), revet_subject(), recompute(), restore()
      r0_discovery.py r1_basics.py r2_content.py r3_audience.py r4_vetting.py
      report.py          render_report() / diff_reports(): PURE goal-conditioned report from VettingData
    llm/
      client.py          Anthropic / OpenRouter structured calls; cache; fallback when no key (deterministic, labeled)
      budget.py          LLM request budget per process, task groups, per-run usage counter
      sensitive.py       filter Art. 9 content BEFORE storage, returns kept items + dropped count
      topics.py          classify captions into the fixed TOPICS taxonomy
      vetting.py         claims vs evidence, skeptic pass, gaps -> questions, outreach draft
      chat.py            chatbot with tools
      prompts.py
  tests/
fixtures/                MOCK dataset (fictional creators), see section 8
frontend/                Vite + React + TypeScript + Tailwind
data/                    runtime (gitignored): cache/, runs/
docs/
```

## 2. Normalized models (`backend/app/models.py`)

All timestamps are timezone-aware UTC. `None` always means "signal not available", never "false".

Fields marked *optional* below are extensions from the verified Apify fields (`docs/apify-pro-krystofa.md`). They default to `None` / `[]` and are omitted from serialized JSON while unset, so fixtures and older cache files stay valid and byte-identical.

```python
Platform = Literal["instagram", "tiktok", "youtube", "news", "meta_branded", "web"]
Mode = Literal["live", "cache", "mock"]

class SourceRef(BaseModel):
    id: str                      # stable, e.g. "ig:post:Cxyz" or "news:<sha1(url)[:10]>"
    url: str
    platform: Platform
    actor: str | None = None     # e.g. "apify/instagram-profile-scraper"
    fetched_at: datetime
    mode: Mode
    quote: str | None = None     # short excerpt (<= 200 chars) that supports the claim

class Post(BaseModel):
    id: str
    platform: Platform
    url: str
    author_handle: str
    created_at: datetime
    caption: str = ""
    hashtags: list[str] = []     # lowercase, no '#'
    mentions: list[str] = []     # lowercase, no '@'
    coauthors: list[str] = []    # IG coauthorProducers handles
    tagged_users: list[str] = []
    media_type: Literal["photo", "video", "reel", "carousel", "other"] = "other"
    likes: int | None = None
    comments: int | None = None
    views: int | None = None
    location_name: str | None = None
    paid_partnership: bool | None = None   # platform label; None = actor does not expose it
    language: str | None = None            # ISO 639-1 if the platform gives it
    location_id: str | None = None         # optional: IG locationId (reliable place key)
    is_pinned: bool | None = None          # optional: IG isPinned (keep out of 30-day activity)
    sponsors: list[str] = []               # optional: IG sponsors[].username (post-scraper detailedData)
    source: SourceRef

class Profile(BaseModel):
    handle: str
    platform: Platform
    url: str
    display_name: str = ""
    bio: str = ""
    followers: int | None = None
    following: int | None = None
    posts_count: int | None = None
    verified: bool | None = None
    private: bool | None = None
    is_business: bool | None = None
    business_category: str | None = None
    external_urls: list[str] = []
    related_handles: list[str] = []
    region: str | None = None              # TikTok account region, e.g. "CZ"
    is_under_18: bool | None = None        # if true: drop, store nothing
    former_handles: list[str] = []
    former_handles_count: int | None = None  # optional: IG about.former_usernames is a count, not a list
    latest_posts: list[Post] = []
    source: SourceRef

class Comment(BaseModel):                  # commenter identity is NEVER stored
    post_url: str
    text: str
    created_at: datetime | None = None
    source: SourceRef

class CandidateRef(BaseModel):
    handle: str
    platform: Platform
    found_via: list[str]                   # "hashtag:brnofood", "search:cukrárna brno", "place:Brno - Zelný trh", "related:@x", "manual"
    source: SourceRef

class CollabEvidence(BaseModel):
    id: str
    brand: str                             # normalized brand name or handle
    brand_handle: str | None = None
    kind: Literal["coauthor", "mention", "tag", "ad_hashtag", "discount_code", "paid_label", "meta_branded", "affiliate_link"]
    disclosed: bool | None                 # True = labeled as ad/partnership, False = brand present but no label found, None = unknown
    date: datetime | None
    post_id: str | None = None
    is_competitor: bool = False
    source: SourceRef

class NewsItem(BaseModel):
    id: str
    title: str
    outlet: str
    url: str
    published_at: datetime | None
    snippet: str = ""
    source: SourceRef

class DiscoveryQuery(BaseModel):
    keywords: list[str] = []               # "cukrárna brno"
    hashtags: list[str] = []               # "brnofood"
    places: list[str] = []                 # "Brno"
    city: str | None = None
    platforms: list[Platform] = ["instagram", "tiktok"]
    limit: int = 60
```

### SourceProvider (`sources/base.py`)

```python
class SourceProvider(Protocol):
    name: str
    async def discover(self, q: DiscoveryQuery) -> list[CandidateRef]: ...
    async def profiles(self, handles: list[str], platform: Platform) -> list[Profile]: ...       # with ~12 latest_posts
    async def posts(self, handle: str, platform: Platform, since: datetime, limit: int = 50) -> list[Post]: ...
    async def comments(self, post_urls: list[str], per_post: int = 15) -> list[Comment]: ...
    async def collabs(self, handle: str, platform: Platform) -> list[CollabEvidence]: ...       # Meta Branded Content etc.; [] if unsupported
    async def news(self, query: str, lang: str = "cs", region: str = "CZ", limit: int = 10) -> list[NewsItem]: ...
    async def find_cross_platform(self, profile: Profile) -> list[Profile]: ...                  # same creator on TikTok/YouTube; [] if unsupported
```

Rules for every provider: a method that cannot work returns `[]` and emits a `log` event saying why (never raises into the funnel). Each returned object carries `source.mode` and `source.actor`. Minors (`is_under_18`, or a bio that states an age under 18: `compute.minors`) are dropped inside the provider before returning; round 1 and the cache check again.

## 3. Criteria and results

Criteria are a whitelist of kinds. A sensitive request cannot be expressed as a criterion; the chatbot puts it in `refused`.

```python
CriterionKind = Literal[
  # round 1 basics
  "public_account", "followers_range", "active_recently", "not_brand_account", "language_cs",
  # round 2 content
  "topic_share", "formats", "post_frequency", "max_commercial_share",
  # round 3 audience (public signals only)
  "min_engagement", "cs_comment_share", "local_signal", "max_generic_comments",
  # round 4 deep vetting
  "no_competitor_collab", "discloses_ads",
]

class Criterion(BaseModel):
    id: str
    kind: CriterionKind
    round: int                       # 1..4, fixed per kind
    label: dict[str, str]            # {"cs": ..., "en": ...}
    why: dict[str, str]              # plain-language reason shown to the owner
    params: dict                     # e.g. {"min": 5000, "max": 50000}; {"topics": ["food","recipes"], "min_share": 0.4}
    enabled: bool = True

class Refused(BaseModel):
    text: str                        # what the owner asked for
    reason: dict[str, str]           # why we do not check it (Art. 9 / person scoring)

class Brief(BaseModel):              # output of the interview
    business_type: str               # "pekárna"
    city: str | None
    audience: str                    # owner's words; NOT used to infer audience demographics
    goal: str                        # "víc lidí v prodejně"
    budget_hint: str | None
    competitors: list[dict]          # [{"name": "Pekárna B", "handles": ["pekarnab"]}]
    lang: Literal["cs", "en"] = "cs"

class CriteriaSet(BaseModel):
    brief: Brief
    criteria: list[Criterion]
    refused: list[Refused] = []
    discovery: DiscoveryQuery

class CriterionResult(BaseModel):
    criterion_id: str
    status: Literal["pass", "fail", "unknown"]   # unknown never eliminates
    value: str                                    # "2 z 24 postů o jídle"
    threshold: str                                # "aspoň 40 %"
    sources: list[SourceRef]
    waived: bool = False                          # owner said "does not apply to this one"

class Elimination(BaseModel):
    round: int
    criterion_id: str
    reason: dict[str, str]
    sources: list[SourceRef]
```

TOPICS (fixed taxonomy, classified once, reused across goals): `food, recipes, restaurants_cafes, local_tips, family, lifestyle, fitness, sport, fashion, beauty, travel, tech, gaming, music, humor, education, other`. Sensitive content never reaches topic classification (filtered first).

## 4. Candidate, metrics, report

```python
class Metrics(BaseModel):
    posts_analyzed: int
    median_likes: float | None
    median_comments: float | None
    engagement_rate: float | None      # median((likes+comments)/followers)
    posts_per_week: float | None
    last_post_at: datetime | None
    formats: dict[str, int]            # media_type -> count
    commercial_share: float | None     # posts with ad label/hashtag/discount code / posts
    topic_counts: dict[str, int]
    cs_comment_share: float | None
    comments_analyzed: int = 0
    comments_fetched: bool = False      # round 3 asked the provider (even if nothing came back): no refetch
    comments_sensitive: int = 0         # share of sensitive_filtered from comments (a refetch replaces it)
    generic_comment_share: float | None
    local_signals: list[SourceRef]     # posts with matching location_name, bio/caption city mentions
    engagement_spikes: list[str] = []  # post ids with interactions > 3x median

class IdentitySignal(BaseModel):
    signal: str                         # "bio na IG odkazuje na TikTok @x", "stejný web"
    supports: bool
    source: SourceRef | None

class IdentityMatch(BaseModel):
    handle: str
    platform: Platform
    status: Literal["matched", "uncertain", "rejected"]
    signals: list[IdentitySignal]

class Finding(BaseModel):
    id: str
    kind: Literal["fact", "inference", "gap"]   # green / orange / gray
    text: dict[str, str]
    sources: list[SourceRef]                    # fact: >= 1; inference: cites fact ids in based_on; gap: []
    based_on: list[str] = []                    # Finding ids an inference relies on
    section: Literal["goal", "profile", "content", "engagement", "collabs", "claims", "news", "identity"]
    relevance: list[str] = []                   # criterion ids this matters for (goal change re-orders)
    confidence: Literal["high", "medium", "low"] | None   # set by render_report (section 5a.4)
    confidence_basis: dict[str, str] | None     # i18n: "platform paid-partnership label", "single news item", ...
    aspect: str | None                          # identity | content_fit | reach_engagement | local_language | competitors | ...
    tier: Literal["key", "related", "less"] | None   # relevance for the CURRENT goal
    why_it_matters: dict[str, str] | None       # i18n one line for the current goal

class ClaimCheck(BaseModel):
    id: str
    claim: str                                  # what the creator says
    claim_source: SourceRef                     # where and when they said it
    evidence: list[str]                         # Finding / CollabEvidence ids
    status: Literal["supported", "conflicts_with_record", "unsupported", "cannot_verify"]
    confidence: Literal["high", "medium", "low"]
    note: dict[str, str]
    confidence_basis: dict[str, str] | None     # + relevance, aspect, tier, why_it_matters as on Finding

class NewsFinding(BaseModel):
    item: NewsItem
    label: Literal["allegation", "confirmed", "neutral"]
    attribution: str                            # "píše Deník N" / "Deník N reports"

class Report(BaseModel):
    candidate_id: str
    findings: list[Finding]
    claims: list[ClaimCheck]
    collab_timeline: list[CollabEvidence]
    news: list[NewsFinding]
    identity: list[IdentityMatch]
    questions: list[dict[str, str]]             # from gaps, for the first meeting
    outreach_draft: dict[str, str] | None       # always shown as NOT SENT, copy only
    not_checked: list[dict[str, str]]           # what we did not check and why
    skeptic_notes: list[dict[str, str]]
    sensitive_filtered: int                      # count only
    vetted_for: str | None = None                # brief.business_type the deep check (fetch) ran for
    # goal-conditioned report (section 5a); all optional so old snapshots load
    identity_verdict: IdentityVerdict | None     # confirmed | likely | uncertain | not_found + sentence + set_aside
    rendered_for: dict[str, str] | None          # {business_type, goal, city, brief_key} of the CURRENT render
    summary: dict[str, str] | None               # top key findings for this goal (never a score)
    sections: list[ReportSection]                # display order for this goal; item_ids expanded, less_ids collapsed
    less_relevant: list[str]                     # all collapsed ids
    text_source: dict[str, str]                  # step -> "llm" | "rules" | "template" | "llm+rules"
    method: list[dict[str, str]]                 # "How this report was built", i18n lines
    last_diff: ReportDiff | None                 # vs. the previous render (goal / criteria change)
    checks: dict[str, str]                       # criterion_id -> pass | fail | unknown in this render

class Candidate(BaseModel):
    id: str                                      # f"{platform}:{handle}"
    ref: CandidateRef
    profile: Profile | None = None
    metrics: Metrics | None = None
    results: list[CriterionResult] = []
    status: Literal["active", "eliminated", "finalist"] = "active"
    elimination: Elimination | None = None
    restored: bool = False
    sensitive_filtered: int = 0
    sensitive_vetting: int = 0                   # share of sensitive_filtered from the last round-4 vetting (re-vet replaces, never double counts)
    report: Report | None = None
    topic_labels: dict[str, str] = {}            # post_id -> TOPIC, classified once in round 2, reused by recompute
    vetting_data: VettingData | None = None      # raw round-4 inputs; kept in the store, never sent to clients

class Run(BaseModel):
    id: str
    criteria: CriteriaSet
    candidates: dict[str, Candidate]
    rounds: list[dict]                            # [{"round": 1, "entered": 48, "remaining": 22}]
    log: list[dict]
    mode_summary: dict[str, int]                  # {"live": 3, "cache": 12, "mock": 0}
    mode: Literal["discovery", "subject"] = "discovery"
    subject: SubjectSpec | None = None
    llm_usage: dict[str, int] = {}                # {"total": n, "<task group>": n}, counted by llm.budget

class Anchor(BaseModel):                          # one is enough
    city: str | None                              # where the creator / organization is based
    website: str | None                           # normalized host, e.g. "fitpeceni.example"
    company_id: str | None                        # digits only, e.g. Czech IČO "12345678"

class SubjectSpec(BaseModel):
    raw: str; handle: str; platform: Platform | None; anchor: Anchor
    candidate_id: str | None; status: Literal["pending", "resolved", "not_found"]

class IdentityVerdict(BaseModel):
    status: Literal["confirmed", "likely", "uncertain", "not_found"]
    text: dict[str, str]                          # the sentence at the top of the report
    supporting: list[IdentitySignal]; contradicting: list[IdentitySignal]
    set_aside: list[SetAside]                     # {ref, label, kind: namesake | look_alike | fan_account, reason, source}
    anchor: Anchor | None

class ReportDiff(BaseModel):                      # one goal / criteria change for one candidate
    candidate_id: str; from_goal: dict; to_goal: dict
    added / removed / moved_up / moved_down / collapsed: list[str]     # finding / claim ids
    claims_changed: list[dict]; checks_changed: list[dict]
    questions_added / questions_removed: list[dict[str, str]]; outreach_changed: bool
    summary: dict[str, str]                       # "Goal changed from bakery to fitness studio: 2 findings became key, ..."

class VettingData(BaseModel):                     # everything round 4 fetched or asked an LLM, goal-independent
    vetted_at; brief_key                          # goal the fetch + first LLM pass ran for
    posts; cross_profiles; provider_collabs       # sensitive-filtered; competitor flags re-marked per render
    news_items; news_labels                       # ALL items incl. namesakes; id -> allegation | confirmed | neutral
    llm_claims; llm_questions                     # goal-independent LLM output (None = not run / failed)
    llm_by_goal: dict[str, dict]                  # brief_key -> {"outreach", "skeptic"}: per-goal LLM text, cached
    modes; counts
```

## 5. Funnel logic (`rounds/`)

- Rounds run in order. In each round, evaluate every enabled criterion of that round for every active candidate. A candidate is eliminated at the first `fail` (all results are kept for the card). `unknown` never eliminates. A `waived` result is treated as pass.
- **Round 0:** `provider.discover()` -> dedupe by (platform, handle), merge `found_via`. Cap at `discovery.limit`.
- **Round 1:** `provider.profiles()` in one batch. Drop `is_under_18` without storing. `public_account`, `followers_range`, `active_recently` (last post within N days), `not_brand_account` (is_business with a business category that looks like a company, not a creator; `unknown` if unclear), `language_cs` (captions language by lingua; `unknown` if under 3 captions).
- **Sensitive filter** runs on every caption and comment right after fetch, before anything is stored in the run. Dropped items only increment `sensitive_filtered`.
- **Round 2:** topics via `llm.topics` (one call per candidate, cached by post ids), then `topic_share`, `formats`, `post_frequency`, `max_commercial_share` in code.
- **Round 3:** `provider.comments()` only for remaining candidates, last 3-5 posts. `min_engagement`, `cs_comment_share`, `local_signal`, `max_generic_comments`. Audience demographics (age, gender, origin) are never estimated; the card says so.
- **Round 4:** only after the owner confirms (chatbot asks). For each finalist: more posts, cross-platform, collabs, news; build `CollabEvidence` (competitor flag from brief), `ClaimCheck`s, `Finding`s, identity, skeptic, questions, outreach draft. Then `no_competitor_collab` and `discloses_ads` results. Round 4 does NOT auto-pick: all vetted finalists stay; failures are shown, not hidden.
- **recompute(run, new_criteria):** rounds 1-3 from cached data and cached topic labels, no LLM and no fetch, < 2 s. Returns a diff: who dropped/returned and why.
- **restore(candidate, criterion_id):** sets `waived=True` on that result, re-evaluates from that round.
- **Ranking:** none by default. Finalists can be sorted only by one criterion value the owner picks.

## 5a. Subject mode, goal-conditioned report, confidence (as built)

Detailed contract and normative tables: [subject-mode.md](subject-mode.md). Deviations from it are listed at the end of this section.

### 5a.1 Subject mode

- **Input.** `POST /api/subject {subject, platform?, anchor?, brief | preset | criteria, lang}` or the chat tool `research_subject`. `subject` is an `@handle` or an Instagram / TikTok profile link (`compute/subject.parse_subject`; a trailing sentence "." is dropped; a post link gets "send the profile link"; a bare name gets 422 "a name alone can match namesakes ..."). `anchor` is an object or a plain string (`classify_anchor`: digits = company ID, a dot = website, else city); a field the owner filled in that does not normalize (a company ID that is not 6-8 digits, a website that is not a domain) is a 422, never a silent "no anchor". The anchor is one of city, website or company ID (`normalize_anchor`: host without scheme / `www.`, digits only, IČO zero-padded to 8). The goal comes from `criteria`, else a preset (`get_preset(name, lang)`, chosen by keywords from a free-text brief), else `chat.criteria_for_brief`. The brief city is the business's city and is never used as the creator's anchor.
- **Flow** (`engine.run_subject`, run `mode = "subject"`):
  1. Resolve: `provider.profiles([h], platform)` for the given platform, else Instagram, then TikTok. No profile or a minor: `subject.not_found`, `subject.status = "not_found"`, no candidate, nothing stored about a minor.
  2. Checks: rounds 1-3 evaluate every enabled criterion for the one candidate and **never eliminate**. A private account gives `unknown` results and the run continues.
  3. Vetting: round 4 as for a finalist, then the report (`report.ready`).
- `fill_missing` is a no-op, `restore` returns 400 ("subject runs do not eliminate"), `/vet` and the chat's `start_deep_vetting` re-vet (fetch again; 409 while the check is still running, 400 only when the subject was not found), `POST /goal` with a free-text brief uses the deterministic criteria (no chat agent, 0 LLM requests), and `run_rounds` refuses.

### 5a.2 Identity resolution with the anchor

- `identity.anchor_signals`: the anchor website / company ID found on the profile, its external links or a matched cross-platform profile; the anchor city in the bio or in post locations / captions (Czech word forms); another city in the bio or locations (contradiction).
- `identity.look_alike_signals`: a cross-platform account whose bio names another city than the anchor gets a negative signal, so a same-name account in Bratislava ends up rejected.
- `identity.identity_verdict` (deterministic):

| status | when |
|---|---|
| `confirmed` | anchor website or company ID matched, or anchor city in bio plus a linked cross-platform account; and no other-city signal |
| `likely` | only the anchor city matched; or no anchor but a linked cross-platform account |
| `uncertain` | anchor given and nothing matched; any other-city signal; or no anchor and no linked account |
| `not_found` | no profile |

- `set_aside` lists what the report does **not** use, with the signals as the reason: rejected cross-platform accounts (`look_alike`, or `fan_account` with fan markers), uncertain ones (`look_alike`) and namesake news (`namesake`). A namesake's label is the outlet plus the shared name and the other context ("Zlínský kurýr article about another Ondřej Toman (podnikatel)"), not the headline, so an allegation about a private namesake is not repeated.
- The company ID is only matched against public profile text. The business register is not queried, and the gap and the verdict say so. When the anchor is not found but a cross-platform account links to the profile, the verdict names both ("nothing on the profile matches the anchor (...), although an account on another platform links to it (...)"); "the signals contradict each other" appears only when a contradicting signal exists. Other-city signals use the canonical city name (Brno, not "Brnem"); English namesake labels translate the context word (podnikatel -> businessman).
- A rejected cross-platform account is a fact listing the observed signals (`f:identity:<platform>:<handle>`) plus an inference `i:lookalike:<platform>:<handle>` ("Most likely a different account ...; not used"), like namesake news (`f:namesake:` + `i:namesake:`). A matched account's confidence basis comes from its signals: link between the profiles (high), same website (high), else similar handle and name (medium).

### 5a.3 Goal-conditioned report

- **Fetch once, render many.** `r4_vetting.vet_candidate` fetches as before and stores everything in `Candidate.vetting_data` (`VettingData`): posts, cross-platform profiles, provider collaborations, all news including namesakes, news labels, LLM claims, LLM gap questions and per-goal LLM skeptic / outreach text. It makes at most 5 LLM requests (news labels, claims, questions, skeptic, outreach), each with a labeled fallback.
- **`rounds/report.render_report(criteria, candidate, data, anchor=, previous=)` is pure** (no I/O, no LLM, no clock): the same criteria and data give the identical report. Competitor marks are recomputed on a copy of the collaboration timeline for the CURRENT brief's competitors, so ProteoMax is a competitor for a fitness studio and not for a bakery.
- **A render contains**, in order: the identity verdict; one goal check per enabled criterion (`f:check:<id>` fact with the result's sources, or `g:check:<id>` gap for `unknown`); the goal-fit fact `f:fit:topics` ("n of m recent posts are about {this goal's topics}"); the finding families (profile, content, engagement, collaborations, local, identity, news minus namesakes); claims (rule floor + validated LLM claims; status is evidence-based and changes only when the evidence does); the skeptic pass; questions; outreach; `summary`, `sections`, `less_relevant`, `text_source`, `method` and `rendered_for`.
- **Goal-conditioned details (review round 2).** `no_competitor_collab` and `discloses_ads` are `unknown` ("posts not available") for a private account or one with no readable posts and an empty collaboration record, never a pass. A matched news item whose title or snippet names one of the current brief's competitors is `key`, tied to `no_competitor_collab`, and feeds `i:competitor.based_on`; an allegation about ad labels next to a failing `discloses_ads` check adds `i:news_record:<id>` based on both. If the subject is one of the brief's competitors, the report gets the key fact `f:subject_competitor` and the outreach is a one-line "No outreach draft" note. The outreach template says the topics "fit us" only when `topic_share` passes. Claim `why_it_matters` uses the competitor criterion's text only for a competitor brand. The summary and the chat's key findings take one key item per aspect, clipped at a word boundary. A custom brief mapped to a preset (`coffee roastery` -> bakery) gets why texts for its own business and competitors (`presets.overlay_why`).
- **Relevance tiers** per goal: `key` (failing checks, goal fit, competitor collaborations, claims that conflict with the record, allegations about the creator, identity contradictions), `related` (anything tied to an enabled criterion, identity / news / claims items, pricing and demographics gaps, undisclosed collaborations), `less` (passing basic checks, labeled non-competitor collaborations, anything tied to no enabled criterion). `less` items are collapsed under "Less relevant for this goal". Each item gets a one-line `why_it_matters` for the current business.
- **Questions**: evidence questions (conflicts, unlabeled posts), goal templates for key items (competitor collab, topic fit, local reach, formats, budget), one goal question ("Our goal is ... would a post about our {business} fit ..."), LLM or rule gap questions, then demographics and pricing; deduplicated, at most 8.
- **Outreach**: the cached LLM draft for this goal if the vetting ran for it, else a template that names the current business and goal. Never sent.
- **`method`** ("How this report was built"): subject and anchor, what was fetched with counts and live / cache / mock, the sensitive-filter count, identity signals and what was set aside, how facts / inferences / gaps are marked, the goal ordering, and AI vs. rules per step.
- **Goal or criteria change** (`POST /goal`, `POST /criteria`, chat `change_goal`): `engine.recompute` re-renders every report that has `vetting_data` (subject and discovery runs), sets `last_diff = diff_reports(previous, new)` and returns `report_diffs`. No fetch and no LLM request: the run's `llm_requests_used` does not move. The API publishes `report.diff` then `report.ready` per candidate and writes a run-log line ("Report for @h re-rendered for the new goal from the data already fetched (no new fetch). Goal changed from ..."). Switching back reproduces the first report. A goal the vetting did not run for uses the rule-based skeptic and the template outreach. Reports without `vetting_data` (old snapshots) keep the legacy partial refresh (`r4_vetting.refresh_for_brief`).
- **`ReportDiff`** lists added / removed / moved up / moved down / collapsed ids, claim status and tier changes, check status changes, new and dropped questions, whether the outreach changed, and a one-line i18n summary.

### 5a.4 Confidence per finding

Every Finding and ClaimCheck has `confidence` (high / medium / low) and `confidence_basis` (i18n). Confidence describes the evidence, never the person. Summary of the normative table (subject-mode.md section 7):

| evidence | confidence |
|---|---|
| platform profile data, media types, post dates; platform paid-partnership label, Meta branded content, co-author field; anchor website / company ID on the profile; linked cross-platform profiles; structurally private data gaps (demographics, reach, pricing) | high |
| own caption (collaboration without a platform label); engagement and comment-language counts with enough data; anchor city in bio; a single news item naming the handle; account rejected by fan markers, region or city; "not found in the sources we checked" gaps | medium |
| keyword topic labels; generic-comment rules; small samples; anchor city only in posts; news matching only the name; similar handle only | low |
| inference | the lowest of its `based_on` facts, capped at medium |

### 5a.5 Deviations from subject-mode.md (as built)

- `Report.checks` (criterion id -> status per render) was added for `ReportDiff.checks_changed`.
- There is always one goal question, so a goal-specific question exists even when every check passes.
- A collaboration finding is tied only to `no_competitor_collab` when the brand is a competitor of the current goal and to `discloses_ads` when it is unlabeled; the competitor rule is checked before the failing-criterion rule.
- `/status` also returns `subject` and `llm_usage`; `VettingData.counts` adds `news_relevant`.
- The chat gates `llm_task_enabled("chat")` only on the OpenRouter path (Anthropic is always enabled); an empty `OPENROUTER_TASKS` means the default list, only `none` switches everything off; a blocked OpenRouter key does not spend budget.

## 6. LLM layer (`llm/`)

Read the `claude-api` skill before writing this code. Models from env: `MODEL_CHAT` (default `claude-opus-5-5`), `MODEL_BULK` (default `claude-sonnet-5-5`). Structured outputs for every non-chat task. Every task has a deterministic fallback used when there is no key or a call fails; fallback output is labeled (`llm_mode: "fallback"`) and the UI shows it.

Providers (`LLM_PROVIDER`, default `auto`: Anthropic key first, then OpenRouter key, else fallback). Claude goes through `anthropic.AsyncAnthropic` with `base_url` always passed from `LLM_BASE_URL`, so a stray `ANTHROPIC_BASE_URL` in the shell cannot redirect calls. OpenRouter (`llm/openrouter.py`, plain httpx, OpenAI-compatible `chat/completions`) serves free models (`OPENROUTER_MODEL_CHAT` / `OPENROUTER_MODEL_BULK`, fallbacks in `models`). Every request sets `provider.require_parameters` and `provider.data_collection` (`OPENROUTER_DATA_COLLECTION`, default `deny`). `client.structured()` sends a strict `json_schema` response format derived from the pydantic model and validates the reply with pydantic. The chat runs the same tool loop over streamed SSE: the same system prompt, the tools translated to OpenAI function tools, the same guards, and history kept in Anthropic format and translated per request. A shared limiter caps all OpenRouter calls at 18 per minute, and a daily-cap 429 blocks calls until the reset time. Every failure (429, 402, 5xx, invalid JSON) falls back with the reason logged. The model that actually answered is reported in `GET /api/health` (`llm_models_used`) and in the chat `done` event (`llm_model`).

**Task groups and request budget** (`llm/budget.py`). Tasks belong to groups: chat, vetting (claims, skeptic, questions, outreach), news (news labels), topics, sensitive. `OPENROUTER_TASKS` (default `chat,vetting,news`; `all`; `none`) says which groups OpenRouter serves; the others use their labeled fallback, so topics and the sensitive filter are rule-based on the free tier. Anthropic serves every group. `LLM_REQUEST_BUDGET` caps LLM HTTP requests per process (default 40 with OpenRouter, unlimited with Anthropic; an integer applies to either; `unlimited` / `off` / `-1` = no cap). Whoever sends a request calls `budget.spend(task)` once per attempt: `client.structured()` checks the group, then its answer cache (`data/llm/structured-<sha1>.json`, validated answers only, 0 requests on a hit), then spends; `openrouter.stream_chat` and the Anthropic chat stream spend one request per call. When the budget is used up, each group logs "LLM budget exhausted" once and falls back (the chat apologises if text was already shown). The engine binds `bind_llm_usage(run.llm_usage)` so every run counts its own requests. A subject check costs at most 5 vetting requests; a goal switch costs 0. `OPENROUTER_BULK_TASKS=1` is a deprecated alias of `all`.

- `sensitive.filter(texts) -> (kept_mask, dropped_count)`: categories health, politics, religion, ethnicity, sexuality, criminal. Fallback: keyword lists (cs + en). Errs on dropping.
- `topics.classify(posts) -> {post_id: topic}`: fixed taxonomy. Fallback: hashtag/keyword map.
- `vetting.claims(profile, posts, collabs) -> list[ClaimCheck]`: extract the creator's own claims about brands, payments, exclusivity, audience size from bio and captions; match ONLY to provided evidence ids; may not introduce facts.
- `vetting.skeptic(report) -> notes + downgrades`: flags inferences without fact support, allegation vs confirmed in news, namesake risk.
- `vetting.questions(gaps)`, `vetting.outreach(brief, candidate)`: outreach is a draft, never sent.
- `chat`: Claude with tools. System prompt: guide a non-expert owner; ask the five questions one or two at a time; propose criteria in plain language with a reason each; refuse criteria about religion, politics, health, sexuality, ethnicity/origin, "values" of a person, personality, or any overall score, and explain why in one sentence; never declare a best creator. Tools: `propose_criteria(CriteriaSet)`, `update_criterion(id, params|enabled)`, `run_rounds(up_to: int)`, `explain_elimination(candidate_id)`, `start_deep_vetting(candidate_ids)`, `change_goal(brief)`, `draft_outreach(candidate_id)`, `research_subject(subject, anchor?, brief, preset?)`. Server validates tool input against the whitelist; anything else becomes `Refused`. Fallback (no key): scripted interview for the demo brief (bakery in Brno) and the second brief (fitness studio in Brno), complete in Czech and English.
- **Subject entry in the chat.** A message with an `@handle` or a profile link is a subject request when it is the first message or has a check verb (check, vet, research, look at, who is, prověř, zkontroluj, ...), never while the competitor question is pending. The chat asks only what is missing, one question per turn: the anchor ("To check the right @h and not a namesake or look-alike account: where is the creator based (city), or what is their website or company ID (IČO)? You can also say “skip”.") and the goal. "skip" means no anchor and the verdict can be at most likely. Then it calls `research_subject` and replies with the verdict, up to 3 key findings tagged fact / inference / gap with their confidence, the failing / unknown check counts, "Nothing was eliminated and there is no score", and the hint to try another goal. "What about my fitness studio?" calls `change_goal` and summarises the report diff.
- **Name-only subjects.** "check / research / prověř <Capitalised Name>" with no handle asks for the Instagram / TikTok @handle or profile link (question id `sh`); the next message with a handle runs the check with the anchor and goal from the name message. A first message without a check verb that names a handle as a competitor or example ("our competitor is @x", "creators like @x", "find ...") starts the discovery interview. While the anchor question is pending, a request to send / e-mail, a question ("what is IČO?") or a malformed IČO is answered and the anchor question is asked again (no check starts).
- **A failed follow-up LLM request** after `research_subject`, `change_goal` or `start_deep_vetting` already ran renders that tool's result with the deterministic formatter (`done.llm_mode = "fallback"`), never "try again" (which would start a new run).
- **Language.** The effective language is that of the first owner message (history, then the current one) whose language is clear, else the UI `lang`; a greeting or a bare @handle does not decide it. With a cs / en UI only a clear stopword majority overrides it (mid-sentence capitalised words, i.e. names and places, are ignored), so "Check Jakub Horák from Brno" stays English. It is set on the context before any tool runs, written to `brief.lang`, and returned in `done.lang`. English presets come from `presets.preset_brief(name, "en")`, so the English UI never shows "pekárna".

## 7. API and events

```
POST /api/chat                 {run_id?, message, lang} -> SSE: chat.delta, chat.tool, criteria.updated, done
GET  /api/runs/{id}            Run snapshot
GET  /api/runs/{id}/events     SSE stream of run events (replays log on connect)
POST /api/runs                 {criteria: CriteriaSet} -> {run_id}; starts rounds 0-3
POST /api/runs/{id}/vet        {candidate_ids} -> starts round 4
POST /api/runs/{id}/criteria   {criteria} -> recompute rounds 1-3 (+ re-render vetted reports), returns diff + report_diffs
POST /api/runs/{id}/restore    {candidate_id, criterion_id}
POST /api/runs/{id}/goal       {brief} | {preset} | {criteria} -> new criteria, recompute, diff + report_diffs
POST /api/subject              {subject, platform?, anchor?, brief|preset|criteria, lang} -> {run_id, mode: "subject", subject, status}
GET  /api/runs/{id}/compare?sort=<criterion_id>
POST /api/purge                deletes data/cache, data/runs, LLM outputs
GET  /api/runs/{id}/status     {busy, error, rounds, counts, mode, subject, llm_requests_used, llm_usage, llm_budget, llm_budget_left, ...}
GET  /api/health               {source_mode, llm_mode, llm_provider, llm_model, llm_models_used, apify_configured,
                                apify_provider_implemented, llm_requests_used, llm_budget, llm_budget_left,
                                llm_budget_exhausted, llm_tasks, llm_requests_by_task}
```

Run events (SSE `event:` name, JSON `data:`):
`run.started`, `log {text, actor?, mode?}`, `round.started {round}`, `candidate.added {candidate}`, `candidate.updated {candidate}`, `candidate.eliminated {id, elimination}`, `round.finished {round, entered, remaining}`, `sensitive.filtered {candidate_id, count}`, `vetting.progress {candidate_id, step}`, `report.ready {candidate_id}`, `diff {dropped: [...], returned: [...], pending_fetch?, final?, replaces_pending?}`, `candidate.removed {id}`, `run.finished`, `error {message}`.
Run-log lines follow the run's language (`events.current_lang`, bound by the engine from `brief.lang`): an English run gets English provider / LLM-client lines. The "LLM budget exhausted" line is logged once per run (per binding), and the report's method line says when the budget was used up.
Subject mode adds `subject.resolved {candidate_id, platform, handle}`, `subject.not_found {subject, tried, reason}` and, after a goal or criteria change, `report.diff {candidate_id, diff: ReportDiff}` before the matching `report.ready`. `GET /api/runs/{id}` and every SSE candidate payload omit `vetting_data`.

Integration notes (as built):
- `sensitive.filtered` carries `{candidate_id, count, total}`: `count` = dropped in this step, `total` = the candidate's running total (the UI shows `total`).
- `candidate.removed {id}`: round 1 / fill_missing removed a candidate (minor, or the provider did not return the profile). Nothing about it is kept.
- `diff`: after a recompute / restore / goal change, `pending_fetch: true` means `fill_missing` is fetching data for returned candidates; when it finishes, a second `diff` with `final: true, replaces_pending: true` is the combined result against the state before the change (the UI replaces the provisional one).
- `report.ready {candidate_id}` carries only the id; the UI re-fetches `GET /api/runs/{id}`.
- Chat `done {chat_id, run_id, llm_mode, llm_model?, lang}` (always exactly one, last); `criteria.updated {criteria, run_id}` binds the run as soon as `research_subject` creates it; `error {message}` may precede it. `X-Chat-Id` response header. Request also accepts `chat_id` and `reset`.
- `run.rounds` also holds round 0 (`entered` = raw discovery refs, `remaining` = unique candidates) and round 4 (`entered` = vetted, `remaining` = vetted; round 4 never eliminates).
- `diff.waivers_dropped [{candidate_id, handle, criterion_id}]`: restore waivers voided by a recompute (the goal changed, or that criterion's kind / params changed). On a goal change, vetted reports are re-rendered for the new goal from `vetting_data` (section 5a.3; no fetch, no LLM) and the response carries `report_diffs`; `report.vetted_for` keeps the goal the fetch ran for. Reports from snapshots without `vetting_data` only get competitor marks, collab inferences and the outreach draft rebuilt.
- Every CriteriaSet written through the API or a chat tool is normalized server-side (`chat.normalize_criteria_set`): brief text fields, criterion labels / why texts and the city param go through the sensitive guard (flagged -> `refused`), params are coerced per kind, unknown keys stripped, uncoercible values -> 422.
- `local_signal.params.city` defaults to `None` = `brief.city`; with no city at all the criterion is switched off.

## 8. MOCK fixtures

`fixtures/` holds a fictional dataset, every object `mode: "mock"`, handles visibly fictional (suffix `_mock` is not needed in the handle, but `display_name` and README say MOCK and the UI shows a MOCK badge). About 48 candidates found via mixed paths, designed so that the bakery goal and the fitness goal produce different finalists:
- some private, some > 200k followers, some brands (`is_business` + category "Bakery"), inactive 90+ days, mostly English captions;
- round 2 misses: travel, fashion, gaming creators; mixed accounts with only 2 of 24 food posts;
- round 3 misses: low engagement, mostly non-Czech comments, many emoji-only comments, no local signals;
- finalists for the bakery: 5, including one whose bio says "exkluzivní ambasador @pekarna_a" while two posts are coauthored with competitor `@pekarna_b` (one without any ad label), and one with a discount code and no label ("recenze, nikdo mi neplatí");
- finalists for the fitness studio: overlapping set, 1-2 shared with bakery, different findings relevant;
- a namesake: a news item about a different person with the same name; a fan account;
- a few captions that the sensitive filter must drop (health, politics), so the counter is > 0.
Real runs replace fixtures via `SOURCE_MODE=apify` (live) or a cache directory from Kryštof.

## 9. UI (frontend)

One screen. Left: chat (380 px). Right: board. Mobile: tabs Chat / Board. cs default, en toggle.
- **Header:** run mode badges (LIVE / CACHE / MOCK counts), LLM mode, "Změnit cíl", "Smazat data", "Rozmazat vyřazené" toggle (for the video).
- **Criteria panel:** chips grouped by round, click to edit params or disable, gray chips for refused requests with the reason.
- **Funnel:** five round columns with "vstoupilo 48 → zůstalo 22". Active cards in the current column; eliminated cards collapse into a lane under their round with the one-line reason and source chip; click -> restore.
- **Candidate card:** avatar initial, handle, followers, found via, topic bar, format, frequency, engagement, cs comment share, local signals, authenticity signals, criterion results (pass/fail/unknown + source chip). Label "odhad z veřejných dat, ne demografie". No overall score anywhere.
- **Finalist report** (drawer): collab timeline (competitors highlighted, disclosed yes/no), claim cards (claim left, evidence right, status, confidence, source), commercial saturation, news with allegation/confirmed tags, identity panel, questions for the first meeting, outreach draft with NEODESLÁNO + Copy only, not checked, sensitive filtered count. Colors: green fact, orange inference, gray gap; every value clicks through to its source.
- **Compare finalists:** table by criteria, sort only by a criterion the user picks.
- **Goal change:** diff view "vypadl jen u cíle A / B a proč".
- **Live log:** collapsible, each line with actor and live/cache/mock.
- **Subject mode and the goal-conditioned report** need UI work listed in [subject-mode.md section 12](subject-mode.md): identity verdict with set-aside items at the top of the drawer, sections in order with "Less relevant for this goal" collapsed, a confidence pill with its basis and the why line on every finding, the "How this report was built" panel, the report diff after a goal change, a subject entry form, and `llm_requests_used / llm_budget` in the header. The UI follows `done.lang` and defaults to English for the jury.

## 10. Hard lines (enforced in code, tested)

No overall score, no "best", no risk level. No audience age/gender/origin. No views/beliefs/personality. Sensitive content filtered before storage, count only. No likes scraping, no face recognition, no commenter identities stored. Minors dropped without storage. Outreach never sent (no send endpoint exists). Every Finding of kind fact has a source; inference cites facts; gaps become questions. Every fetched object shows live/cache/mock. Confidence levels describe the evidence for a finding, never the person: no trustworthiness, credit or personality score. Subject mode never eliminates and never ranks. A namesake's article is set aside by outlet and context and its allegation is not repeated. Identity resolution uses only public profile data and the anchor the owner gives; the business register is not queried.
