# Creator Scout: pitch

Written 9 Oct 2026, about 02:00; updated about 04:20 for the code freeze with the measured results in [validation-results.md](validation-results.md). Facts come from [architecture.md](architecture.md), [README.md](../README.md), the plan [brand-fit-cz.md](brand-fit-cz.md), the verification report [overeni-2026-10-08.md](overeni-2026-10-08.md), tonight's live Apify tests ([apify-pro-krystofa.md](apify-pro-krystofa.md), section "Výsledky živých testů 9. 10. 2026"), the validation results and the git log. Anything not measured is marked "not measured". Demo script: [video-script.md](video-script.md).

**In 2 minutes.**

- What it does: the owner's goal becomes criteria she can edit. In subject mode she names one account, one anchor and a goal and gets a sourced report. In discovery, public accounts are narrowed in rounds with a reason and a source per cut, and finalists' claims are set against their own posts. No score.
- Real, on `main`: subject mode, discovery funnel, goal switch with a diff, refusals, NOT SENT outreach, English UI by default. The Apify provider was live-tested (T1 to T12 except T7, about 1.11 USD).
- Live on real data: 2 public Brno accounts, @kamvbrne and @foodguidebrno, researched through Apify (275 s and 326 s, about 0.19 and 0.16 USD), now replayed from the cache and labeled CACHE. Apify spend tonight: about 3.1 USD in total.
- LLM: OpenRouter free tier with a labeled rule-based fallback for every task; claim extraction fell back to rules in the live runs. No Anthropic key was used.
- Measured on the 2 real subjects (cache replay, no keys): 0 facts without a source, 134 of 134 quotes found, an identity verdict on both, a wrong anchor rejected. The goal switch changed a check result for 1 of 2 subjects (A4 fails for @kamvbrne).
- Measured on our own phrasings: refusal guard 9/10 refused and 0/5 normal requests refused (pass); keyword sensitive filter 16/20 sensitive and 2/20 harmless dropped after tuning (fail, and not held out; a reviewer's held-out list gave 12/20 and 3/20).
- Not done: the real discovery funnel was not re-run live after the engine fixes; the 4 manual checks were not measured.

## 1. One-sentence pitch

Creator Scout helps a small business owner pick a social-media creator: it turns her goal into criteria she can edit, shows why each public account was kept or dropped, and checks what finalists claim against their own posts, with a source on every line.

## 2. 30-second spoken pitch

82 words: about 30 seconds at a brisk pace, 35 at a calm one.

> A bakery in Brno wants a local creator. Under Czech law, if that creator posts an unlabeled ad, the bakery is liable too. Creator Scout turns the owner's goal into criteria she can see and edit. It refuses criteria about religion, health or politics. It narrows real public accounts in rounds, with a reason and a source for every cut. For finalists, it sets their claims against their own posts. Change the goal, and the report changes. No score. The owner decides.

"Real" holds: the recorded Brno discovery runs are real public accounts, replayed from the cache. On that data the funnel ends with 0 or 1 finalist, so do not imply a full shortlist on real data.

Extra line (subject mode is on `main`): "Or start from one handle, one city and a goal, and get the report directly."

## 3. The problem

**Who.** The owner of a bakery, a café or a small e-shop. She wants a local creator but does not know whom to pick, by what rules, or what to check. Creator tools exist (HypeAuditor, Modash from 199 USD a month billed yearly, Heepsy with a free plan), but they are built for marketers.

**Why it matters to her, legally.** In Czechia the business that pays for the post is on the hook too.

- Paid collaborations, barter included, must be clearly labeled as advertising ([Czech Advertising Code 2025, art. 34.6](https://www.rpr.cz/wp-content/uploads/2025/09/Kodex-reklamy_2025.pdf)). A platform label, a text label, or an ad hashtag at the start is enough.
- The advertiser is liable jointly and severally with the creator ([Act No. 40/1995 Coll., § 6b](https://www.zakonyprolidi.cz/cs/1995-40)), unless it proves the creator ignored its instructions (§ 6b(3)). Fine up to CZK 5 million (§ 8a). The self-regulation body SPIR says the same ([SPIR guidance](https://old.spir.cz/www.samoregulace.cz/doporucena-pravidla-spoluprace-zadavatele-influencera.html)).
- As a seller she is also covered by consumer law: hidden paid promotion is always a misleading practice ([Act No. 634/1992 Coll., Annex 1(j)](https://www.zakonyprolidi.cz/cs/1992-634)). Fine up to CZK 5 million or 4 % of turnover.
- What protects her: a written instruction to label the post, and a check of the post once it is published.

**How common unlabeled ads are.** In autumn 2023 the European Commission and national consumer authorities, the Czech one included, screened 576 influencers. Results came out on 14 Feb 2024: 97 % posted commercial content, but only 1 in 5 consistently disclosed it as advertising. 358 accounts were picked for further investigation ([IP/24/708](https://ec.europa.eu/commission/presscorner/detail/en/ip_24_708)). The sample was mostly large accounts (82 over 1 million followers, 301 over 100,000, 73 between 5,000 and 100,000), so we do not present these numbers as a fact about micro-creators.

**What we do not claim.** We found no published Czech fines against influencers for 2025 (the 2025 annual reports of the consumer authority ČOI and the broadcasting council RRTV list none), so we cite no Czech cases.

## 4. How it maps to the official definition of done

| Brief | What Creator Scout does | State tonight |
|---|---|---|
| **Input:** a person or organization + one anchor + a goal | Two entry points. *Discovery:* the chat asks a few plain questions (what you sell and where, who you sell to, what the campaign should do, rough budget, competitors) and turns them into criteria, then searches. *Subject mode:* one @handle + an anchor (city, website or company ID) + a goal goes straight to a report. A company ID (IČO) can be the anchor. It is matched only as text in public data (bio, links, captions); there is no business-registry lookup. | Discovery: real code. Subject mode: real code, on `main`, run live on 2 real subjects. A company ID anchor was not tested. |
| **Output:** every claim links to a source | Every fact carries platform, URL, fetch date, live / cache / mock, actor name and a short quote. Every value in the UI clicks through to its source. A creator's claim is accepted only if it is quoted word for word from the fetched bio or caption. | Real code. The app does not re-fetch the URL to check the quote. Checked on the 2 real subjects (cache replay): 0 of 83 facts without a source (A1), 134 of 134 quotes found word for word in the fetched items (A2). |
| **Output:** fact split from inference | Green = fact with a source. Orange = inference, which cites the fact ids it rests on. Gray = gap. A skeptic pass downgrades inferences without fact support. | Real code. |
| **Output:** gaps are stated | Missing data never eliminates anyone; the criterion says "cannot verify". Gaps become questions for a first meeting. Each report has a "Not checked, and why" section. | Real code. |
| **Same subject, different goal, different report** | "Change goal" recomputes rounds 1 to 3 from stored data with no new fetch, then shows who dropped out only under goal A or only under goal B, and why. Vetted reports get competitor marks, collaboration inferences and the outreach draft rebuilt for the new goal. In subject mode, switching the goal re-renders the report from cache and lists what changed. | Discovery: real code, tested on mock data. Subject mode: real code, on `main`. On the 2 real subjects, bakery to fitness, 0 live fetches: @foodguidebrno passes A4 (6 findings, 3 questions and 1 check result changed); @kamvbrne fails A4, because the questions, the outreach draft and 2 thresholds change but no check result changes status. |
| **Wins:** a real subject goes in, a sourced report comes out | @kamvbrne and @foodguidebrno, 2 public Brno media accounts on Instagram, researched live through Apify actors with anchor city Brno and goal bakery, then switched to fitness studio. | Done. Recorded live on 9 Oct 2026 at about 03:23: 275 s and 326 s, about 0.19 and 0.16 USD in Apify. The recording ran on code from before the engine fixes; the reports on `main` are recomputed from that cache. All live tests from the Apify handoff (T1 to T12) ran tonight except T7, the comment scraper, which turned out not to be needed. T8 and T10 failed (cut, or treated as a gap); T3 and T9 worked only in part. The real Brno discovery runs are in the cache too (about 1.63 USD). |
| **Wins:** namesakes and look-alikes handled | Identity panel per finalist: "same creator", "uncertain" or "different person or account", with signals for and against and their sources (cross-links in bios, same website, city). News is matched by name, city and handle. A rejected namesake is shown but never attributed. Fan accounts are flagged. No made-up "identity 95 %". | Real code. On the 2 real subjects: verdict "likely", 2 supporting signals each. @kamvbrne with the wrong anchor Ostrava: "uncertain", 1 contradicting signal, not matched. News not tied to the account set aside: 10 and 3 items. Namesake, look-alike and fan accounts set aside: shown on MOCK data only. |
| **Wins:** the user understands how the report is put together | Criteria are visible with a reason each. The funnel shows "entered → remaining" per round. Each elimination shows round, reason and source, and can be undone. The live log names the actor and says live, cache or mock on every line. The LLM mode is shown; a deterministic fallback is labeled "fallback". | Real code. |
| **Out:** search-and-summarise without goal logic | The goal sets the criteria, the criteria set the rounds. A different goal gives different eliminations and different findings. | Real code. |
| **Out:** scrapers an Apify actor covers | We wrote no scraper and solve no CAPTCHA. All platform data comes from Apify actors: instagram-search, hashtag, profile and post scrapers, instagram-scraper for places, clockworks TikTok scrapers, streamers/youtube-scraper, data_xplorer/google-news-scraper-fast. | Real code, live-tested tonight. |
| **Out:** personality, credit or trust scores | No overall score, no "best creator", no risk level. The owner can sort finalists by one criterion she picks. A rule-based guard refuses requests for a score, and the data has no score field. | Real code, covered by tests. On our own 10 test requests the guard missed one: a Czech request to rank by "best overall" ([validation-plan.md](validation-plan.md), R1). |
| **Out:** private data | Public profiles only, no login. Private accounts drop in round 1. The app never stores commenter identities (stripped on load). The 162 raw comment items from tonight's tests in `data/live-tests/` hold only text, timestamp, likes and replies ([publication-audit.md](publication-audit.md)); on the 2 real subjects A7 found 0 commenter identity values in 71 stored comments. Accounts with a stated age under 18 are dropped without storing anything. | Real code. |
| **Out:** sending outreach | The outreach draft is marked NOT SENT and has only a Copy button. No endpoint can send anything. The draft says the collaboration will be clearly labeled as advertising. | Real code. |
| **Rule:** no Art. 9 inference | Sensitive criteria are refused on every path (chat, goal form, API). Sensitive captions and comments are filtered before they are stored in a run; only a count is kept. Criminal matters and fines are filtered too (GDPR Art. 10, [C-439/19](https://eur-lex.europa.eu/legal-content/EN/TXT/HTML/?uri=CELEX:62019CJ0439)). No audience age, gender or origin. | Real code. On our own 20 sensitive test captions, the keyword filter first dropped 14 (target 18) and 3 of 20 harmless ones (target at most 2) ([validation-plan.md](validation-plan.md), S1). After tuning on a dev list: 16 of 20 and 2 of 20, still a fail, and S1 is no longer held out. A reviewer's held-out list, measured once on the tuned filter: 12 of 20 and 3 of 20. LLM filter on top: not measured. Recall on real captions: not measured, on purpose. |
| **Rule:** delete raw data after judging | "Delete data" (`POST /api/purge`) clears `cache/`, `runs/` and `llm/` in the running backend's data folder. After judging, [`scripts/purge_all.sh`](../scripts/purge_all.sh) deletes `data/cache`, `runs`, `llm`, `live-tests`, `live-run`, `live-subject` and `validation` in the repo and every worktree. By hand: the run datasets in the Apify console, `demo-output/`, and the agents' scratch folders ([publication-audit.md](publication-audit.md)). | Real code for the button and the script. |
| **Rule:** at least one subject researched live | @kamvbrne and @foodguidebrno, researched live through Apify on 9 Oct 2026 at about 03:23, replayed from the cache and labeled CACHE. | Done. |
| **Rule:** cached run OK if labeled | The header counts LIVE, CACHE and MOCK objects. Every source chip says which; cached sources show their fetch date. | Real code. |
| **Rule:** MOCK only for unreachable sources, labeled | The repo ships a fictional MOCK dataset (48 candidates) so the app runs with no keys. Every mock object is labeled, display names end in "(MOCK)", URLs use a `*.mock.invalid` host, and the UI shows a MOCK badge with no outbound link. Meta Branded Content is unreachable for Czech brands; it is cut, not mocked. | Real code. MOCK in the demo: the online replay at https://creator-scout-demo.vercel.app (noindex) is static, all MOCK data, no backend. The 2 real-subject reports replay from the cache, labeled CACHE. |
| **Deliverables:** repo + video, max 90 s | This repo. Script in [video-script.md](video-script.md). Capture script [`scripts/record-demo.sh`](../scripts/record-demo.sh) (1440x900, MOCK by default). The demo setup replays @kamvbrne from the cache, labeled CACHE, with the rule-based LLM fallback. | Video: not in the repo at the time of writing (about 04:20). |

**Against the judging weights.**

- Value (35): a real owner with a real legal exposure gets a decision aid, not a list (section 3).
- Originality (25): we name the competitors ourselves and say what is still ours (section 5).
- Working end-to-end (20): discovery, rounds, vetting, goal switch and outreach run end-to-end on mock data. On real data, subject mode ran end to end live on 2 subjects and replays from the cache on `main`. The discovery funnel on the recorded Brno data ends with 0 or 1 finalist and was not re-run live after the engine fixes.
- Technical execution (10): one `SourceProvider` protocol behind mock, cache and Apify; a write-through cache; SSE events; an LLM fallback for every task; backend tests in `backend/tests/`.
- Validation and limitations (10): section 6 and [validation-plan.md](validation-plan.md) and [validation-results.md](validation-results.md) (pass rules fixed before measuring, 2 failures reported), and every validation check we have not run is listed as "not measured".

## 5. Originality

We name the competitors before the jury does.

| Tool | What it does | What you get at the end |
|---|---|---|
| **Modash** | 380 million+ profiles over 1,000 followers. Creator and audience location down to city on Instagram. A free public page, [Top 20 Brno Influencers](https://www.modash.io/find-influencers/czech-republic/brno), lists 82 Brno creators sorted by audience share in Brno, with a Brno food guide in first place. Its collaboration timeline shows whether posts were labeled. From 199 USD a month billed yearly, 299 USD monthly. | A ranked list. |
| **hypebridge/influencer-discovery-agent-instagram-tiktok** (on Apify) | Natural-language brief, Instagram and TikTok, a city in the `location` field ([actor](https://apify.com/hypebridge/influencer-discovery-agent-instagram-tiktok)). | A fit score from 0 to 10. |
| **HypeAuditor AI Scout** | A brief in chat or a questionnaire returns up to 50 creators with explanations ([help](https://help.hypeauditor.com/en/articles/15693186-ai-scout)). HypeAuditor also has an Audience Quality Score from 1 to 100 and red flags that include politics and religion. | Scores and flags. |
| **Kolsquare Compliance Score** | Rates how a creator's Instagram posts over 3 months disclose ads, in 5 levels ([blog](https://www.kolsquare.com/en/blog/kolsquare-launches-compliance-score-feature)). | A compliance score. |
| **apify/influencer-discovery-agent** (Apify's own) | Natural-language description, TikTok only, about 50 profiles per run, no location input (returns a country code), 100 USD per 1,000 profiles. | An AI fit score from 0 to 1. |

Also: Apify's own [influencer-vetting recipe](https://github.com/apify/agent-skills/blob/main/skills/apify-ultimate-scraper/references/workflows/influencer-vetting.md) describes almost the same data pipeline as our rounds 1 to 3. That part is not original, and we say so.

**What we do not claim:** that we are the only city-level search (Modash, Heepsy and hypebridge do it), that checking ad disclosure is new (Kolsquare, Modash), that we are cheaper per profile than the Apify agents, or that our data collection complies with Meta's terms.

**What is still ours.** Every tool we found ends in a score or a badge. Viral Nation (evidence packet) and Upfluence (links to flagged posts) show evidence behind their flags, but still end in a score or a badge. We end in reasons.

1. **A goal interview that becomes explicit, editable criteria, with refusals.** Each criterion has a plain reason, can be edited or switched off, and refused requests stay visible as gray "Not checked" chips with the reason. HypeAuditor AI Scout also turns a brief into a list, but none of the tools we checked refuses sensitive criteria; HypeAuditor and Phyllo flag politics instead.
2. **A reversible, transparent funnel with no score.** Rounds by the owner's own criteria. Each elimination has a round, a reason and a source, and the owner can bring a candidate back ("this criterion does not apply to this one").
3. **Claim vs. evidence pairs.** What the creator says (quote, place, date) next to what the record shows (posts, labels, discount codes, co-authored posts), with a status (supported, conflicts with record, unsupported, cannot verify), a confidence level and sources. We found no tool that pairs claims with evidence without a score. The closest, `rainminer/instagram-reel-fact-checker`, gives verdicts and a risk score.
4. **A goal switch that changes the report.** Same data, a new goal: different criteria, different eliminations, different findings, and a diff that says who dropped out under which goal and why.
5. **An identity verdict with signals.** Same creator / uncertain / different person, with the signals for and against, instead of a confidence percentage.
6. **Czech liability explained.** The owner learns why ad labeling is her problem too (Advertising Code art. 34.6, § 6b of Act 40/1995 Coll.), sees the exact posts behind each finding, and gets an outreach draft that promises labeling. Today the app says this in one line on the "discloses ads" criterion and in the draft; a fuller note in the report was not built.

Honest one-liner for the jury: "Creator search exists, including on Apify. We built a guide for a bakery owner in Brno that shows why each account dropped out and checks what the finalists claim."

## 6. What is real, cached, mocked or missing

| Part | State | Notes |
|---|---|---|
| Funnel engine: rounds 0 to 4, recompute, restore, goal change, compare | **Real** | Reproduces the designed outcome for both goals on mock data; covered by tests. |
| Apify provider | **Real, live-tested** | All live tests (T1 to T12) ran on 9 Oct 2026 except T7, the comment scraper, which turned out not to be needed. T8 and T10 failed (cut, or treated as a gap); T3 and T9 worked only in part. Code checked against the live items. Tests cost about 1.11 USD in total. |
| Full funnel on real Brno data | **Cached, not re-run live** | Recorded live on 9 Oct 2026 (about 1.63 USD), before the engine fixes. Replayed from the cache with the fixes and the current bakery preset, the accounts kept after rounds 0, 1, 2 and 3 were 40, 4, 1, 1 (of 74 found); 40, 1, 0, 0 (of 42); 40, 3, 0, 0 (of 41). No new live discovery run was made after the fixes. |
| Real subjects | **Cached** | @kamvbrne and @foodguidebrno, recorded live on 9 Oct 2026. On `main`: 49 and 34 facts, 2 and 2 inferences, 7 and 6 gaps; 7 and 2 texts dropped by the sensitive filter. |
| Cache replay | **Real code** | `SOURCE_MODE=cache` replays a recorded run; labeled CACHE with fetch dates. Real cached runs: the Brno discovery runs and the 2 real subjects. A subject replay makes 0 Apify calls and takes under 0.4 s per check and per goal switch. |
| Instagram paid-partnership label | **Works live** | `paidPartnership` was true on 3 of 3 labeled posts we tested and false on 21 of 21 Czech posts. We have not yet seen a Czech post with the label, so "false" is treated as unknown, never as "no label". |
| Meta Branded Content | **Cut** | rohlik.cz returned only a `no_items` error (still billed); nike returned 3 rows. Czech collaborations are not visible without login. Fallback: platform labels, ad hashtags, discount codes, co-authored posts. |
| TikTok account region and under-18 flag | **Missing at source** | The keys are absent, even for a foreign account. Region is not used. Age is a gap, not a filter. |
| Comments | **Real, via post details** | Up to 15 latest comments per post from the post scraper. Commenter names are dropped on load. |
| LLM: Claude | **Not run live** | No Anthropic key was used tonight. The request shapes were checked only against a fake server. |
| LLM: OpenRouter | **Used live, partly** | Free tier, `dots-studio/dots-3-note-preview:free`, a 40-request budget per backend process, a rule-based fallback for every task. One live chat turn and one live sensitive-filter call worked on 9 Oct 2026. In the 2 real subject runs it wrote the meeting questions and some vetting text; claim extraction fell back to rules after OpenRouter errors. Output quality: not measured. |
| LLM: no key | **Fallback, labeled** | Scripted interview and keyword rules, shown as "fallback". |
| English UI as default | **Real** | On `main`. `?lang=cs` switches to Czech. |
| Subject mode (@handle + anchor + goal → report) | **Real** | On `main`. Run live on 2 real subjects. |
| MOCK dataset | **Mock, labeled** | 48 fictional candidates for running with no keys. |
| Company ID as anchor | **Real code, not validated** | Part of subject mode. Matched as text in public profile data only; the business register is not queried. Not tested in the validation pass. |
| Audience age, gender, origin | **Missing by design** | Not in public data; we do not estimate it. It becomes a question for the creator. |
| Minors without a stated age | **Missing** | Only the provider flag (absent on TikTok) or an age under 18 in the bio is detected. |
| Validation | **Measured, 2 fails** | Plan: [validation-plan.md](validation-plan.md); results: [validation-results.md](validation-results.md), measured on `main` at `edacfa1` with no keys (0 Apify calls, 0 LLM requests). 14 checks: 8 scripted (one of them tests the checker itself), 2 on our own test phrasings, 4 manual. On the 2 real subjects (cache replay): A1, A2, A5, A6, A7 pass; A4 passes for 1 of 2 (fails for @kamvbrne). A3 was checked on MOCK only in this pass (43 of 43). On our own phrasings: R1 passes (9 of 10, 0 of 5); S1 fails (16 of 20, 2 of 20, tuned list). The 4 manual checks (M1 to M4): not measured. |

Known limits we say out loud: the source cache holds captions before the sensitive filter until "Delete data" runs; eliminated candidates keep their full fetched profile in the run (the minimizing function exists but is not called); matching namesakes and brands is heuristic and can be wrong; the `quote` field sometimes holds a label the code writes (for example "region SK") instead of quoted text, and the checker counts these apart; a goal switch can leave every check status unchanged (A4, @kamvbrne); the real discovery funnel was not re-run live after the engine fixes; the plan's owner check for finalists without confirmed adult age is not built. Fixed tonight: a vetted MOCK report with no other account found used to state no identity verdict (1 of 5); now 5 of 5 have one.

## 7. Likely jury questions

**Why no score?**
The brief rules out personality and trust scores, and a single number hides the reason. Scoring people is also close to the AI Act ban on social scoring (art. 5(1)(c), which applies since 2 Feb 2025). The Commission's draft guidelines of 19 May 2026 treat picking contractors on social media by criteria as high-risk under Annex III point 4(a), even when a human decides; those duties apply from 2 Dec 2027, and a hackathon prototype is not on the market. So each criterion is pass, fail or cannot verify, with a source, and the owner can sort by one criterion she picks. She decides.

**Why no audience demographics?**
Public data does not show the audience's age, gender or origin. Only the creator's own insights or paid estimates do. Guessing it would mean judging commenters by their names and photos, and origin is Art. 9 data. We show the language of the comments and place signals from the posts, call them signals and not demographics, and turn the rest into a question: "Can you send your audience insights?"

**How do you handle namesakes?**
The identity panel lists each candidate match as same creator, uncertain or different person or account, with the signals for and against and where each came from (bio links, same website, city, handle). News is matched by name, city and handle. A namesake is shown as rejected and never attributed to the creator. Matching can be wrong, which is why the signals are on screen. Real example tonight: with the anchor Brno, both real subjects came out "likely" with 2 supporting signals; @kamvbrne with the wrong anchor Ostrava came out "uncertain" with 1 contradicting signal and was not matched. News not tied to the account was set aside (10 and 3 items). A namesake in the news being set aside is shown on MOCK data (@toman_ochutnava), not on real data.

**What did the Apify actors give you, and what failed?**
Gave: Instagram account search with live search (15 of 20 results in Brno, versus 11 of 40 relevant without it); Brno places with coordinates (0 errors on 41 coordinates against our city box); profiles with 12 of 12 latest posts; post details with the paid-partnership label and up to 15 comments per post; news with publisher URLs (10 of 10); the YouTube paid-promotion flag.
Failed or limited: Meta Branded Content for Czech brands (cut); TikTok region and under-18 (absent); TikTok account search matches the word in the account name and returns mostly businesses; hashtag search returns only the first page (12 and 24 posts); only 36 % of hashtag posts carry a place id, never coordinates; related profiles always empty; error items are billed.

**What does a run cost?**
Tonight's tests cost about 1.11 USD in total. From verified Free-plan prices, before tonight's cuts, we estimated about 2.77 USD for the Instagram core and 7.28 USD for a full run with every source. Tonight removed two lines (comments now come with post details, saving 1.40 USD; Meta Branded Content is cut, saving 0.58 USD). Measured from the run logs: a real subject check cost about 0.19 and 0.16 USD in Apify (the app's own estimates; Apify's lagging usage counter showed 0.065 and 0.143 USD at the time), and the first real Brno discovery runs about 1.63 USD. Apify spend tonight: about 3.1 USD in total. The settled total in the Apify console: not checked. A goal switch or a replay from cache makes no new Apify calls. LLM: OpenRouter free-tier models, capped at 40 requests per backend process; LLM cost per run: not measured.

**GDPR, and when is the raw data deleted?**
Public data only, no login. Legal basis: legitimate interest, Art. 6(1)(f); a purely commercial interest can qualify ([C-621/22](https://eur-lex.europa.eu/legal-content/EN/TXT/HTML/?uri=CELEX:62022CJ0621)). A business that contacts a finalist owes them Art. 14 information. Minimization: no commenter identities in the app, minors dropped, sensitive content filtered before storage with only a count kept, criminal matters and fines filtered. "Delete data" removes the cache, runs and LLM outputs of the running backend. After judging, `scripts/purge_all.sh --yes` deletes `data/cache`, `runs`, `llm`, `live-tests`, `live-run`, `live-subject` and `validation` in the repo and every worktree; the Apify run datasets, `demo-output/` and the agents' scratch folders are deleted by hand. Open gap: until a purge, the cache holds captions the filter later drops.

**What about Meta's terms?**
Meta's terms (art. 3.2.3, since 1 Jan 2025) and Instagram's terms forbid automated collection without permission, explicitly also without login. TikTok's EEA terms forbid automated extraction without written consent. Whether that binds people who never log in is disputed (Meta v. Bright Data, US, 23 Jan 2024). We do not claim compliance with Meta's terms. We write no scraper, solve no CAPTCHA and do not log in. We use Apify-maintained actors, as the brief asks, collect the minimum and delete it after the event.
