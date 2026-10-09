"""All pydantic models. THIS FILE IS THE CONTRACT (docs/architecture.md sections 2-4).

Conventions every module relies on:
- All timestamps are timezone-aware UTC. Naive datetimes are assumed UTC and converted.
- ``None`` always means "signal not available", never "false".
- Every user-facing ``dict[str, str]`` text field is an i18n map with keys ``"cs"`` and ``"en"``
  (Criterion.label/why, Refused.reason, Elimination.reason, Finding.text, ClaimCheck.note,
  Report.questions[i], Report.outreach_draft, Report.not_checked[i], Report.skeptic_notes[i]).
  Use ``i18n(cs, en)`` to build one.
- Handles (Profile.handle, CandidateRef.handle, Post.author_handle, hashtags, mentions, coauthors,
  tagged_users, IdentityMatch.handle) are normalized: lowercase, no leading '@' / '#'.
- Candidate.id == ``candidate_id(platform, handle)`` == f"{platform}:{handle}".
"""

from __future__ import annotations

import hashlib
import re
import warnings
from datetime import datetime, timezone
from typing import Annotated, Any, Literal, get_args

from pydantic import VERSION as PYDANTIC_VERSION
from pydantic import AfterValidator, BaseModel, Field, field_validator, model_validator

# --------------------------------------------------------------------------------------------
# Primitive types
# --------------------------------------------------------------------------------------------

Platform = Literal["instagram", "tiktok", "youtube", "news", "meta_branded", "web"]
Mode = Literal["live", "cache", "mock"]
SourceMode = Literal["mock", "cache", "apify"]   # config SOURCE_MODE
LLMMode = Literal["llm", "fallback"]             # label on every LLM task output
Lang = Literal["cs", "en"]

PLATFORMS: tuple[str, ...] = get_args(Platform)
QUOTE_MAX = 200


def _to_utc(v: datetime) -> datetime:
    if v.tzinfo is None:
        return v.replace(tzinfo=timezone.utc)
    return v.astimezone(timezone.utc)


MOCK_NAME_SUFFIX = " (MOCK)"


def person_name(display_name: str | None) -> str:
    """display_name without the fixtures' " (MOCK)" marker (for name matching, news queries, drafts)."""
    name = (display_name or "").strip()
    return name[: -len(MOCK_NAME_SUFFIX)].rstrip() if name.endswith(MOCK_NAME_SUFFIX) else name


def greeting_name(display_name: str | None) -> str:
    """The name to greet in an outreach draft: person_name without a tagline ("Kam v Brně | ty
    nejlepší tipy kam v Brně" -> "Kam v Brně"). Matching and news queries keep the full person_name
    (a short phrase like "Kam v Brně" would match unrelated articles, and it is the recorded query)."""
    name = person_name(display_name)
    head = re.split(r"\s*[|·•]\s*|\s+[–—-]\s+", name)[0].strip()
    return head if len(head) >= 2 else name


def norm_handle(v: str) -> str:
    """Lowercase, strip whitespace and a leading '@' or '#'."""
    v = (v or "").strip()
    while v[:1] in ("@", "#"):
        v = v[1:]
    return v.lower()


def _norm_handles(v: list[str]) -> list[str]:
    out: list[str] = []
    for h in v:
        n = norm_handle(h)
        if n and n not in out:
            out.append(n)
    return out


UTCDatetime = Annotated[datetime, AfterValidator(_to_utc)]


def _unset(v: Any) -> bool:
    """exclude_if for optional extension fields: omitted from serialized JSON while None / [], so
    JSON written before they existed (mock fixtures, imported caches) stays byte-identical."""
    return v is None or v == []


# Field(exclude_if=...) needs pydantic >= 2.12. Older versions only emit a deprecation warning and
# serialize the unset extension fields anyway, so a stale venv would differ silently: say it loudly.
if tuple(int(x) for x in re.findall(r"\d+", PYDANTIC_VERSION)[:2]) < (2, 12):  # pragma: no cover
    warnings.warn(f"pydantic {PYDANTIC_VERSION} < 2.12: optional model fields (Post.location_id, is_pinned, "
                  "sponsors, Profile.former_handles_count) will appear in JSON as null / []. "
                  "Run: pip install -r backend/requirements.txt", RuntimeWarning, stacklevel=2)


Handle = Annotated[str, AfterValidator(norm_handle)]
HandleList = Annotated[list[str], AfterValidator(_norm_handles)]

# --------------------------------------------------------------------------------------------
# 2. Normalized source models
# --------------------------------------------------------------------------------------------


class SourceRef(BaseModel):
    id: str                      # stable, e.g. "ig:post:Cxyz" or "news:<sha1(url)[:10]>"
    url: str
    platform: Platform
    actor: str | None = None     # e.g. "apify/instagram-profile-scraper"
    fetched_at: UTCDatetime
    mode: Mode
    quote: str | None = None     # short excerpt (<= 200 chars) that supports the claim

    @field_validator("quote")
    @classmethod
    def _clip_quote(cls, v: str | None) -> str | None:
        if v is not None and len(v) > QUOTE_MAX:
            return v[: QUOTE_MAX - 1] + "…"
        return v


class Post(BaseModel):
    id: str
    platform: Platform
    url: str
    author_handle: Handle
    created_at: UTCDatetime
    caption: str = ""
    hashtags: HandleList = Field(default_factory=list)      # lowercase, no '#'
    mentions: HandleList = Field(default_factory=list)      # lowercase, no '@'
    coauthors: HandleList = Field(default_factory=list)     # IG coauthorProducers handles
    tagged_users: HandleList = Field(default_factory=list)
    media_type: Literal["photo", "video", "reel", "carousel", "other"] = "other"
    likes: int | None = None
    comments: int | None = None
    views: int | None = None
    location_name: str | None = None
    paid_partnership: bool | None = None   # platform label; None = actor does not expose it
    language: str | None = None            # ISO 639-1 if the platform gives it
    # Optional extensions from the verified Apify fields (docs/apify-pro-krystofa.md); defaults keep
    # mock fixtures and older cache files valid.
    location_id: str | None = Field(default=None, exclude_if=_unset)   # IG locationId: reliable place key (locationName is free text)
    is_pinned: bool | None = Field(default=None, exclude_if=_unset)    # IG isPinned: keep pinned posts out of 30-day activity
    sponsors: HandleList = Field(default_factory=list, exclude_if=_unset)  # IG sponsors[].username (post-scraper detailedData only)
    source: SourceRef


class Profile(BaseModel):
    handle: Handle
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
    external_urls: list[str] = Field(default_factory=list)
    related_handles: HandleList = Field(default_factory=list)
    region: str | None = None              # TikTok account region, e.g. "CZ"
    is_under_18: bool | None = None        # if true: drop, store nothing
    former_handles: HandleList = Field(default_factory=list)
    former_handles_count: int | None = Field(default=None, exclude_if=_unset)  # IG about.former_usernames is a COUNT, not a list
    latest_posts: list[Post] = Field(default_factory=list)
    source: SourceRef


class Comment(BaseModel):                  # commenter identity is NEVER stored
    post_url: str
    text: str
    created_at: UTCDatetime | None = None
    source: SourceRef


class CandidateRef(BaseModel):
    handle: Handle
    platform: Platform
    found_via: list[str]                   # "hashtag:brnofood", "search:cukrárna brno", "place:Brno - Zelný trh", "related:@x", "manual"
    source: SourceRef


class CollabEvidence(BaseModel):
    id: str
    brand: str                             # normalized brand name or handle
    brand_handle: str | None = None
    kind: Literal["coauthor", "mention", "tag", "ad_hashtag", "discount_code", "paid_label", "meta_branded", "affiliate_link"]
    disclosed: bool | None                 # True = labeled as ad/partnership, False = brand present but no label found, None = unknown
    date: UTCDatetime | None
    post_id: str | None = None
    is_competitor: bool = False
    source: SourceRef


class NewsItem(BaseModel):
    id: str
    title: str
    outlet: str
    url: str
    published_at: UTCDatetime | None
    snippet: str = ""
    source: SourceRef


class DiscoveryQuery(BaseModel):
    keywords: list[str] = Field(default_factory=list)       # "cukrárna brno"
    hashtags: HandleList = Field(default_factory=list)      # "brnofood"
    places: list[str] = Field(default_factory=list)         # "Brno"
    city: str | None = None
    platforms: list[Platform] = Field(default_factory=lambda: ["instagram", "tiktok"])
    limit: int = 60


# --------------------------------------------------------------------------------------------
# 3. Criteria and results
# --------------------------------------------------------------------------------------------

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

CRITERION_KINDS: tuple[str, ...] = get_args(CriterionKind)

CRITERION_ROUND: dict[str, int] = {
    "public_account": 1, "followers_range": 1, "active_recently": 1, "not_brand_account": 1, "language_cs": 1,
    "topic_share": 2, "formats": 2, "post_frequency": 2, "max_commercial_share": 2,
    "min_engagement": 3, "cs_comment_share": 3, "local_signal": 3, "max_generic_comments": 3,
    "no_competitor_collab": 4, "discloses_ads": 4,
}

# Expected ``Criterion.params`` per kind, with defaults. Evaluators read these keys (missing key ->
# default here); the chat agent proposes these keys. Shares are fractions 0..1.
CRITERION_DEFAULT_PARAMS: dict[str, dict[str, Any]] = {
    "public_account": {},
    "followers_range": {"min": 5000, "max": 50000},           # either bound may be None
    "active_recently": {"days": 30},                          # last post within N days
    "not_brand_account": {},
    "language_cs": {"min_share": 0.5},                        # share of captions detected "cs"; unknown if < 3 captions
    "topic_share": {"topics": ["food", "recipes", "restaurants_cafes"], "min_share": 0.4},
    "formats": {"formats": ["reel", "video"], "min_share": 0.3},  # share of posts whose media_type is in formats
    "post_frequency": {"min_per_week": 1.0},
    "max_commercial_share": {"max_share": 0.3},
    "min_engagement": {"min_rate": 0.01},                     # Metrics.engagement_rate
    "cs_comment_share": {"min_share": 0.5},
    "local_signal": {"city": None, "min_count": 1},           # len(Metrics.local_signals) >= min_count; city None -> brief.city
    "max_generic_comments": {"max_share": 0.4},               # Metrics.generic_comment_share <= max_share
    "no_competitor_collab": {},                               # competitors come from CriteriaSet.brief.competitors
    "discloses_ads": {"max_undisclosed": 0},                  # count of CollabEvidence with disclosed=False
}

# Default plain-language labels (UI / fallback chat may use them; the LLM may write better ones).
CRITERION_DEFAULT_LABELS: dict[str, dict[str, str]] = {
    "public_account": {"cs": "Veřejný účet", "en": "Public account"},
    "followers_range": {"cs": "Velikost (sledující)", "en": "Size (followers)"},
    "active_recently": {"cs": "Aktivní v poslední době", "en": "Recently active"},
    "not_brand_account": {"cs": "Tvůrce, ne firemní účet", "en": "Creator, not a brand account"},
    "language_cs": {"cs": "Píše česky", "en": "Posts in Czech"},
    "topic_share": {"cs": "Podíl relevantních témat", "en": "Share of relevant topics"},
    "formats": {"cs": "Formát obsahu", "en": "Content format"},
    "post_frequency": {"cs": "Frekvence postů", "en": "Posting frequency"},
    "max_commercial_share": {"cs": "Komerční nasycenost", "en": "Commercial saturation"},
    "min_engagement": {"cs": "Aktivita publika", "en": "Audience engagement"},
    "cs_comment_share": {"cs": "Komentáře v češtině", "en": "Comments in Czech"},
    "local_signal": {"cs": "Lokální signály", "en": "Local signals"},
    "max_generic_comments": {"cs": "Pravost komentářů", "en": "Comment authenticity"},
    "no_competitor_collab": {"cs": "Bez spolupráce s konkurencí", "en": "No competitor collaboration"},
    "discloses_ads": {"cs": "Označuje reklamu", "en": "Discloses ads"},
}


class Criterion(BaseModel):
    id: str
    kind: CriterionKind
    round: int                       # 1..4, fixed per kind (always overwritten from CRITERION_ROUND)
    label: dict[str, str]            # {"cs": ..., "en": ...}
    why: dict[str, str]              # plain-language reason shown to the owner
    params: dict                     # e.g. {"min": 5000, "max": 50000}; {"topics": ["food","recipes"], "min_share": 0.4}
    enabled: bool = True

    @model_validator(mode="before")
    @classmethod
    def _fixed_round(cls, data: Any) -> Any:
        if isinstance(data, dict) and data.get("kind") in CRITERION_ROUND:
            data = {**data, "round": CRITERION_ROUND[data["kind"]]}
        return data


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
    lang: Lang = "cs"


class CriteriaSet(BaseModel):
    brief: Brief
    criteria: list[Criterion]
    refused: list[Refused] = Field(default_factory=list)
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


# TOPICS: fixed taxonomy, classified once, reused across goals.
TOPICS: tuple[str, ...] = (
    "food", "recipes", "restaurants_cafes", "local_tips", "family", "lifestyle", "fitness", "sport",
    "fashion", "beauty", "travel", "tech", "gaming", "music", "humor", "education", "other",
)

Confidence = Literal["high", "medium", "low"]
RelevanceTier = Literal["key", "related", "less"]     # "less" = collapsed under "Less relevant for this goal"
TIER_RANK: dict[str, int] = {"key": 2, "related": 1, "less": 0}

# Goal aspects: which part of the owner's goal a finding matters for.
ASPECTS: tuple[str, ...] = ("identity", "content_fit", "reach_engagement", "local_language", "competitors",
                            "ad_disclosure", "account", "reputation", "practical")
ASPECT_LABELS: dict[str, dict[str, str]] = {
    "identity": {"cs": "Identita", "en": "Identity"},
    "content_fit": {"cs": "Obsah k cíli", "en": "Content fit"},
    "reach_engagement": {"cs": "Dosah a aktivita publika", "en": "Reach and engagement"},
    "local_language": {"cs": "Lokalita a jazyk", "en": "Local reach and language"},
    "competitors": {"cs": "Konkurence a spolupráce", "en": "Competitors and collaborations"},
    "ad_disclosure": {"cs": "Označování reklamy", "en": "Ad disclosure"},
    "account": {"cs": "Účet", "en": "Account"},
    "reputation": {"cs": "Zmínky v médiích", "en": "Media mentions"},
    "practical": {"cs": "Praktické", "en": "Practical"},
}
CRITERION_ASPECT: dict[str, str] = {
    "public_account": "account", "active_recently": "account", "not_brand_account": "account",
    "followers_range": "reach_engagement", "min_engagement": "reach_engagement", "max_generic_comments": "reach_engagement",
    "language_cs": "local_language", "cs_comment_share": "local_language", "local_signal": "local_language",
    "topic_share": "content_fit", "formats": "content_fit", "post_frequency": "content_fit",
    "max_commercial_share": "ad_disclosure", "discloses_ads": "ad_disclosure",
    "no_competitor_collab": "competitors",
}

# --------------------------------------------------------------------------------------------
# 4. Candidate, metrics, report
# --------------------------------------------------------------------------------------------


class Metrics(BaseModel):
    posts_analyzed: int
    median_likes: float | None
    median_comments: float | None
    engagement_rate: float | None      # median((likes+comments)/followers)
    posts_per_week: float | None
    last_post_at: UTCDatetime | None
    formats: dict[str, int]            # media_type -> count
    commercial_share: float | None     # posts with ad label/hashtag/discount code / posts
    topic_counts: dict[str, int]       # TOPICS key -> number of analyzed posts with that topic; "unclassified" = the no-key fallback found no topic (not counted as "other")
    cs_comment_share: float | None
    comments_analyzed: int = 0
    comments_fetched: bool = False         # round 3 asked the provider (even if nothing came back / all filtered)
    comments_sensitive: int = 0            # share of Candidate.sensitive_filtered from comments (a refetch replaces it)
    generic_comment_share: float | None
    local_signals: list[SourceRef]     # posts with matching location_name, bio/caption city mentions
    engagement_spikes: list[str] = Field(default_factory=list)  # post ids with interactions > 3x median


class IdentitySignal(BaseModel):
    signal: str                         # "bio na IG odkazuje na TikTok @x", "stejný web"
    supports: bool
    source: SourceRef | None


class IdentityMatch(BaseModel):
    handle: Handle
    platform: Platform
    status: Literal["matched", "uncertain", "rejected"]
    signals: list[IdentitySignal]


class Finding(BaseModel):
    id: str
    kind: Literal["fact", "inference", "gap"]   # green / orange / gray
    text: dict[str, str]
    sources: list[SourceRef]                    # fact: >= 1; inference: cites fact ids in based_on; gap: []
    based_on: list[str] = Field(default_factory=list)   # Finding ids an inference relies on
    section: Literal["goal", "profile", "content", "engagement", "collabs", "claims", "news", "identity"]
    relevance: list[str] = Field(default_factory=list)  # criterion ids this matters for (goal change re-orders)
    # Goal-conditioned report (docs/subject-mode.md section 3); all optional so old snapshots load.
    confidence: Confidence | None = None
    confidence_basis: dict[str, str] | None = None   # i18n: "platform label", "own caption", "single news item", ...
    aspect: str | None = None                        # one of ASPECTS
    tier: RelevanceTier | None = None                # for the CURRENT goal
    why_it_matters: dict[str, str] | None = None     # i18n one line for the CURRENT goal

    @model_validator(mode="after")
    def _fact_needs_source(self) -> "Finding":
        # Hard line: every fact has a source. Build a "gap" instead when there is none.
        if self.kind == "fact" and not self.sources:
            raise ValueError(f"Finding {self.id!r} of kind 'fact' must have at least one source")
        return self


class ClaimCheck(BaseModel):
    id: str
    claim: str                                  # what the creator says
    claim_source: SourceRef                     # where and when they said it
    evidence: list[str]                         # Finding / CollabEvidence ids
    status: Literal["supported", "conflicts_with_record", "unsupported", "cannot_verify"]
    confidence: Literal["high", "medium", "low"]
    note: dict[str, str]
    confidence_basis: dict[str, str] | None = None
    relevance: list[str] = Field(default_factory=list)   # criterion ids
    aspect: str | None = None
    tier: RelevanceTier | None = None
    why_it_matters: dict[str, str] | None = None


class NewsFinding(BaseModel):
    item: NewsItem
    label: Literal["allegation", "confirmed", "neutral"]
    attribution: str                            # "píše Deník N" / "Deník N reports"


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
    reason: dict[str, str]                  # i18n, names the signals
    source: SourceRef | None = None


class IdentityVerdict(BaseModel):
    status: Literal["confirmed", "likely", "uncertain", "not_found"]
    text: dict[str, str]                    # the sentence at the top of the report
    supporting: list[IdentitySignal] = Field(default_factory=list)     # each with a source
    contradicting: list[IdentitySignal] = Field(default_factory=list)
    set_aside: list[SetAside] = Field(default_factory=list)
    anchor: Anchor | None = None


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
    claims_changed: list[dict] = Field(default_factory=list)   # {"id", "status": [before, after], "tier": [before, after]}
    checks_changed: list[dict] = Field(default_factory=list)   # {"criterion_id", "status": [before|None, after|None]}
    questions_added: list[dict[str, str]] = Field(default_factory=list)
    questions_removed: list[dict[str, str]] = Field(default_factory=list)
    outreach_changed: bool = False
    left_key: list[str] = Field(default_factory=list)     # ids that were "key" before and are not now (still present)
    skeptic_added: list[dict[str, str]] = Field(default_factory=list)     # skeptic notes (i18n) new in this render
    skeptic_removed: list[dict[str, str]] = Field(default_factory=list)   # e.g. AI notes written for the previous goal
    text_changed: list[str] = Field(default_factory=list)  # same tier, text rewritten for the goal ("9 of 9 food" -> "0 of 9 fitness")
    summary: dict[str, str]                  # i18n one line


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
    vetted_for: str | None = None                # brief.business_type the deep check ran for (a goal change keeps it)
    # Goal-conditioned report (docs/subject-mode.md section 3); all optional.
    identity_verdict: IdentityVerdict | None = None
    rendered_for: dict[str, str] | None = None     # {"business_type", "goal", "city", "brief_key"} of the CURRENT render
    summary: dict[str, str] | None = None          # i18n headline: top key findings for this goal (never a score)
    sections: list[ReportSection] = Field(default_factory=list)   # display order for this goal
    less_relevant: list[str] = Field(default_factory=list)        # all collapsed ids
    text_source: dict[str, str] = Field(default_factory=dict)     # step -> "llm+rules" | "rules" | "llm" | "template" ...
    method: list[dict[str, str]] = Field(default_factory=list)    # "How this report was built" i18n lines
    last_diff: ReportDiff | None = None            # vs. the previous render; None after the first vetting
    checks: dict[str, str] = Field(default_factory=dict)   # criterion_id -> pass | fail | unknown of THIS render (waived = pass); feeds ReportDiff.checks_changed


class VettingData(BaseModel):                # raw round-4 inputs: re-rendering for any goal needs no fetch
    vetted_at: UTCDatetime
    brief_key: str                           # goal the fetch + first LLM pass ran for
    posts: list[Post] = Field(default_factory=list)                # latest_posts + extra, sensitive-filtered, newest first
    cross_profiles: list[Profile] = Field(default_factory=list)    # sensitive-filtered, minors removed
    provider_collabs: list[CollabEvidence] = Field(default_factory=list)  # competitor flags NOT trusted (re-marked per render)
    news_items: list[NewsItem] = Field(default_factory=list)       # sensitive-filtered, ALL items incl. namesakes
    news_labels: dict[str, str] = Field(default_factory=dict)      # item id -> allegation | confirmed | neutral
    llm_claims: list[ClaimCheck] | None = None                     # validated LLM claims (goal-independent); None = not run / failed
    llm_questions: list[dict[str, str]] | None = None              # LLM-phrased gap questions (goal-independent)
    llm_by_goal: dict[str, dict] = Field(default_factory=dict)     # brief_key -> {"outreach": {cs,en}?, "skeptic": [raw notes]?}
    modes: dict[str, str] = Field(default_factory=dict)            # step -> "llm" | "fallback"
    counts: dict[str, int] = Field(default_factory=dict)           # posts, comments, cross, news, news_set_aside, collabs_provider, sensitive_dropped


class Candidate(BaseModel):
    id: str                                      # f"{platform}:{handle}"
    ref: CandidateRef
    profile: Profile | None = None
    metrics: Metrics | None = None
    results: list[CriterionResult] = Field(default_factory=list)
    status: Literal["active", "eliminated", "finalist"] = "active"
    elimination: Elimination | None = None
    restored: bool = False
    sensitive_filtered: int = 0
    sensitive_vetting: int = 0   # part of sensitive_filtered counted by the last round-4 vetting (re-vetting replaces it)
    report: Report | None = None
    topic_labels: dict[str, str] = Field(default_factory=dict)   # post_id -> TOPIC (round 2, reused by recompute)
    vetting_data: VettingData | None = None        # kept in the store snapshot; omitted from GET /api/runs/{id} and SSE


class Run(BaseModel):
    id: str
    criteria: CriteriaSet
    candidates: dict[str, Candidate]
    rounds: list[dict]                            # [{"round": 1, "entered": 48, "remaining": 22}]
    log: list[dict]                               # [{"ts", "text", "actor"?, "mode"?}]
    mode_summary: dict[str, int]                  # {"live": 3, "cache": 12, "mock": 0}
    # Extension (optional, not in architecture.md): which LLM tasks ran on the model vs. the
    # deterministic fallback, e.g. {"topics": "fallback", "sensitive": "llm", "vetting": "mixed"}.
    llm_modes: dict[str, str] = Field(default_factory=dict)
    # Subject mode (docs/subject-mode.md): one named creator checked against the goal, nothing eliminated.
    mode: Literal["discovery", "subject"] = "discovery"
    subject: SubjectSpec | None = None
    llm_usage: dict[str, int] = Field(default_factory=dict)   # {"total": n, "<task group>": n} (llm.budget)


# --------------------------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------------------------


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def i18n(cs: str, en: str) -> dict[str, str]:
    """Build the {"cs": ..., "en": ...} text map used by every user-facing text field."""
    return {"cs": cs, "en": en}


def short_hash(text: str, n: int = 10) -> str:
    """sha1(text) hex prefix; used for stable ids, e.g. f"news:{short_hash(url)}"."""
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:n]


def candidate_id(platform: str, handle: str) -> str:
    return f"{platform}:{norm_handle(handle)}"


def make_source_ref(
    *,
    url: str,
    platform: Platform,
    mode: Mode,
    id: str | None = None,
    actor: str | None = None,
    quote: str | None = None,
    fetched_at: datetime | None = None,
) -> SourceRef:
    """SourceRef with sane defaults: id = f"{platform}:{short_hash(url)}", fetched_at = now (UTC),
    quote clipped to 200 chars."""
    return SourceRef(
        id=id or f"{platform}:{short_hash(url)}",
        url=url,
        platform=platform,
        actor=actor,
        fetched_at=fetched_at or utcnow(),
        mode=mode,
        quote=quote,
    )


def make_criterion(
    kind: CriterionKind,
    params: dict | None = None,
    *,
    id: str | None = None,
    label: dict[str, str] | None = None,
    why: dict[str, str] | None = None,
    enabled: bool = True,
) -> Criterion:
    """Criterion with defaults from CRITERION_DEFAULT_PARAMS / CRITERION_DEFAULT_LABELS.
    ``params`` is merged over the defaults. id defaults to the kind (unique per CriteriaSet)."""
    return Criterion(
        id=id or kind,
        kind=kind,
        round=CRITERION_ROUND[kind],
        label=label or dict(CRITERION_DEFAULT_LABELS[kind]),
        why=why or i18n("", ""),
        params={**CRITERION_DEFAULT_PARAMS[kind], **(params or {})},
        enabled=enabled,
    )


def iter_source_refs(obj: Any):
    """Yield every SourceRef nested in a model / list / dict (used to relabel mode, count modes)."""
    if isinstance(obj, SourceRef):
        yield obj
    elif isinstance(obj, BaseModel):
        for name in type(obj).model_fields:
            yield from iter_source_refs(getattr(obj, name))
    elif isinstance(obj, (list, tuple)):
        for x in obj:
            yield from iter_source_refs(x)
    elif isinstance(obj, dict):
        for x in obj.values():
            yield from iter_source_refs(x)
