// Mirrors docs/architecture.md sections 2-4 (backend/app/models.py) and the events in section 7.
// Timestamps arrive as ISO strings. `null` / missing always means "signal not available", never "false".

export type Platform = 'instagram' | 'tiktok' | 'youtube' | 'news' | 'meta_branded' | 'web'
export type Mode = 'live' | 'cache' | 'mock'
export type Lang = 'cs' | 'en'
export type I18nText = Partial<Record<Lang, string>> & Record<string, string>

// ---------- section 2: normalized models ----------

export interface SourceRef {
  id: string
  url: string
  platform: Platform
  actor?: string | null
  fetched_at: string
  mode: Mode
  quote?: string | null
}

export type MediaType = 'photo' | 'video' | 'reel' | 'carousel' | 'other'

export interface Post {
  id: string
  platform: Platform
  url: string
  author_handle: string
  created_at: string
  caption?: string
  hashtags?: string[]
  mentions?: string[]
  coauthors?: string[]
  tagged_users?: string[]
  media_type?: MediaType
  likes?: number | null
  comments?: number | null
  views?: number | null
  location_name?: string | null
  paid_partnership?: boolean | null
  language?: string | null
  source: SourceRef
}

export interface Profile {
  handle: string
  platform: Platform
  url: string
  display_name?: string
  bio?: string
  followers?: number | null
  following?: number | null
  posts_count?: number | null
  verified?: boolean | null
  private?: boolean | null
  is_business?: boolean | null
  business_category?: string | null
  external_urls?: string[]
  related_handles?: string[]
  region?: string | null
  is_under_18?: boolean | null
  former_handles?: string[]
  latest_posts?: Post[]
  source: SourceRef
}

export interface CandidateRef {
  handle: string
  platform: Platform
  found_via: string[]
  source: SourceRef
}

export type CollabKind =
  | 'coauthor'
  | 'mention'
  | 'tag'
  | 'ad_hashtag'
  | 'discount_code'
  | 'paid_label'
  | 'meta_branded'
  | 'affiliate_link'

export interface CollabEvidence {
  id: string
  brand: string
  brand_handle?: string | null
  kind: CollabKind
  disclosed: boolean | null
  date: string | null
  post_id?: string | null
  is_competitor?: boolean
  source: SourceRef
}

export interface NewsItem {
  id: string
  title: string
  outlet: string
  url: string
  published_at: string | null
  snippet?: string
  /** optional translation of the title / snippet into the UI languages ({cs, en}); the original stays the source */
  title_gloss?: I18nText | null
  snippet_gloss?: I18nText | null
  source: SourceRef
}

export interface DiscoveryQuery {
  keywords?: string[]
  hashtags?: string[]
  places?: string[]
  city?: string | null
  platforms?: Platform[]
  limit?: number
}

// ---------- section 3: criteria and results ----------

export type CriterionKind =
  | 'public_account'
  | 'followers_range'
  | 'active_recently'
  | 'not_brand_account'
  | 'language_cs'
  | 'topic_share'
  | 'formats'
  | 'post_frequency'
  | 'max_commercial_share'
  | 'min_engagement'
  | 'cs_comment_share'
  | 'local_signal'
  | 'max_generic_comments'
  | 'no_competitor_collab'
  | 'discloses_ads'

export type ParamValue = number | string | boolean | string[] | number[] | null
export type CriterionParams = Record<string, ParamValue>

export interface Criterion {
  id: string
  kind: CriterionKind
  round: number
  label: I18nText
  why: I18nText
  params: CriterionParams
  enabled: boolean
}

export interface Refused {
  text: string
  reason: I18nText
}

export interface Competitor {
  name: string
  handles?: string[]
}

export interface Brief {
  business_type: string
  city: string | null
  audience: string
  goal: string
  budget_hint: string | null
  competitors: Competitor[]
  lang?: Lang
}

export interface CriteriaSet {
  brief: Brief
  criteria: Criterion[]
  refused: Refused[]
  discovery: DiscoveryQuery
}

export type ResultStatus = 'pass' | 'fail' | 'unknown'

export interface CriterionResult {
  criterion_id: string
  status: ResultStatus
  /** usually a string in the run's language; the demo replay sends {cs, en} (always read through pick()) */
  value: string | I18nText
  threshold: string | I18nText
  sources: SourceRef[]
  waived?: boolean
}

export interface Elimination {
  round: number
  criterion_id: string
  reason: I18nText
  sources: SourceRef[]
}

// ---------- section 4: candidate, metrics, report ----------

export interface Metrics {
  posts_analyzed: number
  median_likes: number | null
  median_comments: number | null
  engagement_rate: number | null
  posts_per_week: number | null
  last_post_at: string | null
  formats: Record<string, number>
  commercial_share: number | null
  topic_counts: Record<string, number>
  cs_comment_share: number | null
  comments_analyzed?: number
  comments_fetched?: boolean
  comments_sensitive?: number
  generic_comment_share: number | null
  local_signals: SourceRef[]
  engagement_spikes?: string[]
}

export interface IdentitySignal {
  /** a string in the run's language, or {cs, en} (read through pick()) */
  signal: string | I18nText
  supports: boolean
  source: SourceRef | null
}

export interface IdentityMatch {
  handle: string
  platform: Platform
  status: 'matched' | 'uncertain' | 'rejected'
  signals: IdentitySignal[]
}

export type FindingKind = 'fact' | 'inference' | 'gap'
export type FindingSection = 'goal' | 'profile' | 'content' | 'engagement' | 'collabs' | 'claims' | 'news' | 'identity'
export type Confidence = 'high' | 'medium' | 'low'
/** Relevance of a FINDING for the current goal (never a rating of the creator). "less" = collapsed. */
export type RelevanceTier = 'key' | 'related' | 'less'

export interface Finding {
  id: string
  kind: FindingKind
  text: I18nText
  sources: SourceRef[]
  based_on?: string[]
  section: FindingSection
  relevance?: string[]
  // docs/subject-mode.md section 3 (all optional: older reports do not have them)
  confidence?: Confidence | null
  confidence_basis?: I18nText | null
  aspect?: string | null
  tier?: RelevanceTier | null
  why_it_matters?: I18nText | null
}

export type ClaimStatus = 'supported' | 'conflicts_with_record' | 'unsupported' | 'cannot_verify'

export interface ClaimCheck {
  id: string
  claim: string
  claim_source: SourceRef
  evidence: string[]
  status: ClaimStatus
  confidence: Confidence
  note: I18nText
  confidence_basis?: I18nText | null
  relevance?: string[]
  aspect?: string | null
  tier?: RelevanceTier | null
  why_it_matters?: I18nText | null
  /** optional translation of the quoted claim ({cs, en}); shown under the quote when the UI language differs */
  claim_gloss?: I18nText | null
}

/** Where the creator / organization is: one is enough (docs/subject-mode.md section 3). */
export interface Anchor {
  city?: string | null
  website?: string | null
  company_id?: string | null
}

/** A namesake, look-alike or fan account the report does NOT use. */
export interface SetAside {
  ref: string
  /** a plain string from the backend, or {cs, en} (quote marks differ per language) */
  label: string | I18nText
  kind: 'namesake' | 'look_alike' | 'fan_account'
  reason: I18nText
  source?: SourceRef | null
}

export type VerdictStatus = 'confirmed' | 'likely' | 'uncertain' | 'not_found'

/** Is this the account the owner means? Never "trustworthy". */
export interface IdentityVerdict {
  status: VerdictStatus
  text: I18nText
  supporting?: IdentitySignal[]
  contradicting?: IdentitySignal[]
  set_aside?: SetAside[]
  anchor?: Anchor | null
}

export interface ReportSection {
  id: string
  title: I18nText
  tier: RelevanceTier
  /** Finding / ClaimCheck ids shown expanded, in display order */
  item_ids: string[]
  /** collapsed under "Less relevant for this goal" */
  less_ids?: string[]
}

export interface ReportDiff {
  candidate_id: string
  from_goal: Record<string, string>
  to_goal: Record<string, string>
  added?: string[]
  removed?: string[]
  moved_up?: string[]
  moved_down?: string[]
  collapsed?: string[]
  claims_changed?: { id: string; status?: [string | null, string | null]; tier?: [string | null, string | null] }[]
  checks_changed?: { criterion_id: string; status: [ResultStatus | null, ResultStatus | null] }[]
  questions_added?: I18nText[]
  questions_removed?: I18nText[]
  outreach_changed?: boolean
  summary: I18nText
}

export interface NewsFinding {
  item: NewsItem
  label: 'allegation' | 'confirmed' | 'neutral'
  attribution: string
}

export interface Report {
  candidate_id: string
  findings: Finding[]
  claims: ClaimCheck[]
  collab_timeline: CollabEvidence[]
  news: NewsFinding[]
  identity: IdentityMatch[]
  questions: I18nText[]
  outreach_draft: I18nText | null
  not_checked: I18nText[]
  skeptic_notes: I18nText[]
  sensitive_filtered: number
  /** brief.business_type the deep check ran for (a later goal change keeps it) */
  vetted_for?: string | null
  // goal-conditioned report (docs/subject-mode.md sections 3 and 6)
  identity_verdict?: IdentityVerdict | null
  /** {business_type, goal, city, brief_key} of the CURRENT render */
  rendered_for?: Record<string, string | null> | null
  /** the top key findings for this goal (never a score or a verdict on the creator) */
  summary?: I18nText | null
  sections?: ReportSection[]
  less_relevant?: string[]
  /** {claims: "llm+rules" | "rules", news, skeptic, questions, outreach} */
  text_source?: Record<string, string>
  /** "How this report was built" */
  method?: I18nText[]
  last_diff?: ReportDiff | null
}

export type CandidateStatus = 'active' | 'eliminated' | 'finalist'

export interface Candidate {
  id: string
  ref: CandidateRef
  profile?: Profile | null
  metrics?: Metrics | null
  results: CriterionResult[]
  status: CandidateStatus
  elimination?: Elimination | null
  restored?: boolean
  sensitive_filtered?: number
  /** part of sensitive_filtered counted by the last round-4 vetting (re-vetting replaces it) */
  sensitive_vetting?: number
  report?: Report | null
  /** post_id -> topic, classified once in round 2 */
  topic_labels?: Record<string, string>
}

export interface RoundStat {
  round: number
  entered: number
  remaining: number
}

export interface LogLine {
  text: string
  actor?: string | null
  mode?: Mode | null
  ts?: string | null
  level?: string | null
}

export type RunMode = 'discovery' | 'subject'

export interface SubjectSpec {
  raw: string
  handle: string
  platform?: Platform | null
  anchor?: Anchor | null
  candidate_id?: string | null
  status: 'pending' | 'resolved' | 'not_found'
}

export interface Run {
  id: string
  mode?: RunMode
  subject?: SubjectSpec | null
  llm_usage?: Record<string, number>
  criteria: CriteriaSet
  candidates: Record<string, Candidate>
  rounds: RoundStat[]
  log: LogLine[]
  mode_summary: Partial<Record<Mode, number>>
  status?: string
  llm_mode?: string
  llm_modes?: Record<string, string>
}

export interface Health {
  source_mode: string
  llm_mode: string
  apify_configured: boolean
  /** false while backend/app/sources/apify_provider.py is still a stub */
  apify_provider_implemented?: boolean
  /** "anthropic" | "openrouter" | null (rule-based fallback) */
  llm_provider?: string | null
  llm_model?: string | null
  llm_models_used?: Record<string, string>
  // LLM request budget (docs/subject-mode.md section 9.2, usage_snapshot)
  llm_requests_used?: number
  llm_budget?: number | null
  llm_budget_left?: number | null
  llm_budget_exhausted?: boolean
  llm_tasks?: string[]
  llm_requests_by_task?: Record<string, number>
}

// ---------- section 7: events ----------

/** Diff item for recompute / goal change. Shape not fixed by the contract; we accept a few variants. */
export interface DiffItem {
  candidate_id?: string
  id?: string
  handle?: string
  platform?: Platform
  before?: CandidateStatus
  after?: CandidateStatus
  /** backend: the NEW elimination for dropped, the PREVIOUS one for returned */
  elimination?: Elimination | null
  needs_fetch?: boolean
  // tolerated alternatives
  round?: number
  criterion_id?: string
  reason?: I18nText | string
  sources?: SourceRef[]
}

export interface RunDiff {
  dropped: (DiffItem | string)[]
  returned: (DiffItem | string)[]
  /** a fill_missing task is fetching data for returned candidates; a final diff follows */
  pending_fetch?: boolean
  /** the combined diff (recompute + fill_missing) against the state before the change */
  final?: boolean
  /** replace the provisional diff currently shown instead of opening a new one */
  replaces_pending?: boolean
  /** restore waivers that no longer apply (new goal, or that criterion changed) */
  waivers_dropped?: { candidate_id: string; handle: string; criterion_id: string }[]
}

export type RunEvent =
  | { type: 'run.started'; data: { run_id?: string } & Record<string, unknown> }
  | { type: 'log'; data: LogLine }
  | { type: 'round.started'; data: { round: number } }
  | { type: 'candidate.added'; data: { candidate: Candidate } }
  | { type: 'candidate.updated'; data: { candidate: Candidate } }
  | { type: 'candidate.eliminated'; data: { id: string; elimination: Elimination } }
  | { type: 'candidate.removed'; data: { id: string } }
  | { type: 'round.finished'; data: RoundStat }
  | { type: 'sensitive.filtered'; data: { candidate_id: string; count: number; total?: number } }
  | { type: 'vetting.progress'; data: { candidate_id: string; step: string } }
  | { type: 'report.ready'; data: { candidate_id: string; report?: Report } }
  | { type: 'diff'; data: RunDiff }
  | { type: 'run.finished'; data: Record<string, unknown> }
  | { type: 'error'; data: { message: string } }
  | { type: 'subject.resolved'; data: { candidate_id: string; platform: Platform; handle: string } }
  | { type: 'subject.not_found'; data: { subject: string; tried?: string[]; reason?: I18nText } }
  | { type: 'report.diff'; data: { candidate_id: string; diff: ReportDiff } }

export type ChatEvent =
  | { type: 'chat.delta'; data: { text?: string; delta?: string } }
  | { type: 'chat.tool'; data: { name: string; input?: unknown; result?: unknown; status?: string } }
  | { type: 'criteria.updated'; data: { criteria?: CriteriaSet } | CriteriaSet }
  | { type: 'done'; data: { run_id?: string | null; chat_id?: string; llm_mode?: string } & Record<string, unknown> }
