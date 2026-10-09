# Creator Scout: choosing and vetting a creator for small businesses

> **About this version.** This is the English version of plan v6, written for the international jury. The Czech original is [brand-fit-cz.md](brand-fit-cz.md). Structure, sources, links and "(unverified)" markers are kept as in the original. Linked documents marked (Czech) are in Czech. Czech legal names are given in English, with the original in parentheses the first time. Short version for the jury: [pitch.md](pitch.md).
>
> **Added after the official brief: subject mode (in progress).** The official brief starts from a known subject: a person or organization, one anchor (city, website, company ID) and a goal. Plan v6 below starts one step earlier, from an owner who does not yet know which creator to pick. Subject mode covers the brief's path directly. The user enters a @handle, an anchor and a goal, and gets a report on that one subject, without the discovery funnel. Switching the goal re-renders the report from the cache and shows what changed. This is being built now and is not finished. Also in progress: English as the default UI language, an LLM path through Claude (Anthropic API) or OpenRouter, and the first real Brno run recorded into the cache.
>
> **Live test results since v6 (night of 8 to 9 October 2026).** Live Apify tests tonight cost about 1.11 USD. The Instagram paid-partnership label (`paidPartnership`) came back true on 3 of 3 labeled test posts and false on 21 of 21 Czech posts. We have not seen a labeled Czech post yet, so false means unknown. Meta Branded Content returned nothing for Czech brands, so it is cut (see section 12); the fallback is platform labels, ad hashtags and discount codes. TikTok `authorMeta.region` and `authorMeta.isUnderAge18` came back empty, so these flags filter no one and age stays a gap in the report. The text below is otherwise the v6 plan and still marks these points as unverified.
>
> Where this plan and the build differ, the README sections "Status" and "Limitations" are current. Known differences:
>
> - eliminated candidates keep their full profile in the run (sections 3 and 10 say name and reason only);
> - finalists without confirmed adult age are not held back; age is shown as a gap (sections 3 and 10);
> - `purge` does not delete `data/live-tests/` (section 10);
> - the citation check compares quotes with what we fetched and does not re-fetch the URL (section 9, item 7);
> - Meta Branded Content is cut (sections 3, 5, 10, 12).

Fact check as of 8 October 2026: [overeni-2026-10-08.md](overeni-2026-10-08.md) (Czech). Actors, inputs, tests and prices for Kryštof: [apify-pro-krystofa.md](apify-pro-krystofa.md) (Czech).

This develops the idea "Hypocrisy Compass / Brand Safety Shield" (idea 6) and other material from a teammate. Version 6 (8 October 2026): a chatbot for a layperson, elimination rounds, focus on content type and audience, a deep check of finalists; fixes based on the source check. Links sit next to the facts; what we did not verify is marked "(unverified)". Screen skeleton for design: [kostra-aplikace-cz.md](kostra-aplikace-cz.md) (Czech).

## 1. Verdict in brief

- **Problem:** the owner of a bakery or café wants to work with a creator, but does not know who, how to choose, or what to check. Creator search tools (HypeAuditor, Modash from 199 USD per month billed annually, Heepsy, which also has a free plan) are built for marketers, not for a layperson.
- **Solution:** a chatbot asks the owner about the business and the goal, proposes criteria and explains them. The app finds candidates, eliminates them over several rounds based on content and audience, and vets 3 to 5 finalists in depth. Every elimination has a round, a reason and a source.
- **What we take from idea 6:** the sponsor's values and goal as input, and looking for mismatches between what the creator claims and what their posts and collaborations show (in the deep check).
- **What we take from the other material:** identity with an explanation, fact / inference / gap colors, switching the goal.
- **What we cut:** everything that rates a person or infers their opinions: likes, "views on things", tags on other people's photos, "vegan persona", a 45/100 score, risk levels, "Family values", "Apolitical". And now also "best creator" as a single number.
- **Why it matters:**
  - Advertising from a paid collaboration, including barter, must be clearly labeled ([Advertising Code (Kodex reklamy) 2025, Art. 34.6](https://www.rpr.cz/wp-content/uploads/2025/09/Kodex-reklamy_2025.pdf)). The business (the advertiser) is jointly and severally liable for the ad together with the creator ([Section 6b of the Advertising Regulation Act (zákon o regulaci reklamy), Act No. 40/1995 Coll.](https://www.zakonyprolidi.cz/cs/1995-40), [SPIR recommendation](https://old.spir.cz/www.samoregulace.cz/doporucena-pravidla-spoluprace-zadavatele-influencera.html)), unless it proves that the creator did not follow its instructions. As the seller, it is also liable under consumer protection law, and hidden paid promotion is always misleading ([Consumer Protection Act (zákon o ochraně spotřebitele), Act No. 634/1992 Coll., Annex 1 letter j)](https://www.zakonyprolidi.cz/cs/1992-634)). Fine of up to CZK 5 million. A written instruction to label the post and a check of the published post help.
  - In autumn 2023 the European Commission and national consumer authorities, including the Czech one, screened 576 mostly large influencers (results 14 February 2024): 97% posted commercial content, but only one in five consistently labeled it ([IP/24/708](https://ec.europa.eu/commission/presscorner/detail/en/ip_24_708), [start of the screening](https://commission.europa.eu/news/commission-and-consumer-authorities-look-business-practices-influencers-2023-10-16_en)).

## 2. What we cut and what replaces it

| Element from the idea | Why it fails | Replacement |
|---|---|---|
| Likes and replies on X / Threads | Likes on X have been private since June 2024 ([source](https://www.ksat.com/business/2024/06/12/what-happened-to-the-likes-x-is-now-hiding-which-posts-you-like-from-other-users/)). Under the CJEU's reasoning, inferring a political opinion or belief from likes is processing of special category data under Art. 9 GDPR ([C-184/20, paras 123-128](https://eur-lex.europa.eu/legal-content/EN/TXT/HTML/?uri=CELEX:62020CJ0184); [C-252/21, para 68](https://eur-lex.europa.eu/legal-content/EN/TXT/HTML/?uri=CELEX:62021CJ0252)), even if the inference is wrong (C-252/21, para 69). Likes are not "manifestly made public" unless the user knowingly made them public (C-252/21, paras 80-82). | The creator's own public posts, content and business conduct only. |
| "His views on things" | A profile of opinions means politics, religion, health, sexuality, ethnicity, so Art. 9. | Content type (what they create about) and what they said about brands and products. |
| Tags on photos by others, "steakhouse" | Other people tag you; it proves nothing. Food can reveal a belief or a health condition (Art. 9). | The creator's own posts. |
| "Vegan persona vs. behavior" | Belief is an Art. 9 GDPR category. The ECtHR recognized a sincere vegan belief as protected under Art. 9 of the Convention (G.K. and A.S. v. Switzerland, Chamber judgment of 16 July 2026, paras 86-89, [HUDOC](https://hudoc.echr.coe.int/eng?i=001-251193)); it may not be final yet, and for GDPR it is only an analogy. | Competitors entered by the owner. |
| Brand Safety Score 45/100, "Not recommended", "best creator" | The brief forbids trust scores for a person. It is close to the ban on social scoring in the AI Act, Art. 5(1)(c), which applies since 2 February 2025 ([FPF](https://fpf.org/blog/red-lines-under-the-eu-ai-act-unpacking-social-scoring-as-a-prohibited-ai-practice)). Cautionary example: Predictim, 2018, blocked by Facebook, Instagram and Twitter ([CBS](https://www.cbsnews.com/news/ai-babysitting-service-predictim-blocked-by-facebook-and-twitter/)). | For each criterion: met / not met / cannot verify, with a source. Ranking only by a criterion the owner picks. The owner decides. |
| "Identity confidence 95%" | A made-up, uncalibrated number. | Signals and a status: same creator / uncertain / different person or account. |
| Values "Family values", "Apolitical" | They can only be checked through religion, sexuality or politics. | The chatbot refuses them and explains why. |
| "Arrogant debates → assertive" | A personality rating, not allowed. | Different goal = different criteria, different finalists (section 7). |
| Political campaigns as a target group | It is all about political opinions. | Drop. |
| "What could destroy them" framing | The jury will read it as a stalking tool. | "Find a creator who fits, and check what they claim." |
| CEO, "hidden telemetry", "CryptoBros s.r.o." | Not about creators. | Drop. |

## 3. Concept

**User:** the owner of a small business with no experience in influencer marketing (bakery, café, online shop). Secondary: agencies.

### Conversation with the chatbot

The chatbot (Claude with tools) asks:
- What do you sell and where? Who do you want to sell to? What should the campaign do?
- Roughly what budget (to size the creator)?
- Do you have competitors the creator should not work with?

Then it proposes criteria in plain language and says why for each one. The owner approves or edits them. The chatbot refuses criteria based on religion, politics, health, sexuality or origin, and explains why.

### Criteria

| Group | Criterion | How we know |
|---|---|---|
| Content type | topics (food, recipes, local tips, family, lifestyle), share of relevant posts | captions and hashtags of recent posts; an LLM sorts them into topics |
| | format (reels, photos, videos), frequency, last activity | post type and date |
| | commercial saturation (what % of posts are ads) | captions of the last ~12 posts: #reklama, #spoluprace (Czech for "ad", "collaboration"), discount codes, @brand mentions. The paid partnership label (`paidPartnership`) comes only from a second post-scraper run (unverified on Czech posts). |
| Audience | size (e.g. 5 to 50 thousand) | follower count |
| | audience activity | median of publicly visible likes and comments, interactions relative to followers. Posts with hidden likes are skipped; we do not use view counts from the profile. |
| | audience language | share of comments in Czech (language detection; we do not store commenter names) |
| | location | location of posts found during search (`locationId`, checked against coordinates to confirm it is in Brno; the `locationName` text is only a fallback), mentions of the city in bio and captions; on TikTok the video's country of creation (`locationCreated`) and the place, if the creator tags it on the video (`locationMeta`, unverified on Czech videos). The account region on TikTok is probably missing today. Posts scraped from the profile carry no location. |
| | audience authenticity | share of comments that are only emoji or generic phrases, mismatch between interactions and followers. Account signals only. |
| Collaborations | no collaboration with competitors | brands in posts, joint posts, collaboration labels |
| | labels ads | labels and hashtags on posts that mention a brand (a platform label, text, or an ad hashtag at the start is enough; this applies to barter too, Code Art. 34.6) |

**Honest note on the audience:** the age, gender and origin of an audience cannot be found from public data. Only the creator's account statistics or paid estimates show them. We do not estimate them, because that would mean judging people from names and photos. The report lists this as a gap and as a question for the creator ("Can you send your audience statistics?").

### Elimination rounds

| Round | What happens | Cost | Typically left |
|---|---|---|---|
| 0. Search | hashtags, keywords and places on IG and TikTok → list of accounts. Or the owner pastes their own list. | cheap | 40-60 |
| 1. Basics | public account, Czech, size, activity in the last 30 days (pinned posts do not count). Anyone who states an age under 18 in the bio is out immediately, with no data stored. | cheap, same batch | 20-30 |
| 2. Content | topics, share of relevant posts, format, frequency, commercial saturation | one LLM pass per account | 10-15 |
| 3. Audience | interactions, comment language, location, authenticity | comments only for those left | 5-8 |
| 4. Deep check | collaborations and competitors, claim vs. evidence, labeling, work-related news, identity | more expensive, the chatbot asks first | 3-5 finalists |

- Every elimination: round, criterion, value, source. "Round 2: only 2 of 12 posts are about food."
- Missing data is not a reason to eliminate. Empty `latestPosts` on a public profile (a known actor bug) means scrape again, not "inactive".
- We cannot reliably tell age from public data (IG has no age field, TikTok `isUnderAge18` is probably empty). A finalist without confirmed adult age does not go into the report until the owner verifies it.
- The owner can bring a candidate back ("this criterion does not apply to them").
- For eliminated accounts we keep only the account name and the reason after the run; downloaded posts are deleted.

### Deep check of a finalist (idea 6)

- **Creator claims we check:** "exclusive ambassador of X", "unpaid review", "community of 120 thousand", their own claims about collaborations.
- **Evidence:** their posts, paid collaboration labels (IG `paidPartnership`, TikTok `isSponsored`, YouTube "Includes paid promotion"; a missing label proves nothing), discount codes, joint posts, Meta Branded Content, targeted news.
- **Work-related news and controversies:** collaborations, ads, products, giveaways, decisions of the Advertising Standards Council (Rada pro reklamu). Always "outlet X reports", with a clear split between allegation and confirmed fact.
- **We do not take:** opinions, likes, tone and character, private life, photos by others, criminal matters or fines for administrative offences (Art. 10 GDPR, [C-439/19](https://eur-lex.europa.eu/legal-content/EN/TXT/HTML/?uri=CELEX:62019CJ0439)). Sensitive content (health, politics, religion, sexuality, ethnicity) is dropped by the filter before storage; the report shows only the count.

## 4. How it runs

The core is taken from the Lens plan (claim ledger, identity, skeptic, gaps).

1. **Chatbot → criteria.** Claude with tools: `propose_criteria`, `run_rounds`, `explain_elimination`, `draft_outreach` (names as in the code). The output of the conversation is the criteria as JSON. Sensitive criteria are refused already here.
2. **Round 0, search.** Queries based on the criteria, three paths: account search by keywords with the city ("cukrárna brno" = pastry shop Brno, "brno food"), hashtags (#brnofood) where we check the post location (`locationId`) against coordinates in Brno, and posts from specific places in Brno (places are filtered by coordinates, not by text). Optionally popular reels for a keyword (max about 64 per keyword; not every keyword has them). On TikTok, account search. Plus "related accounts" (`relatedProfiles`, unverified for small accounts) of the creators found. Result: a list of accounts, each with where it came from.
3. **Rounds 1 to 3 in one batch.** Candidate profiles with their last ~12 posts in one actor run. These posts carry no collaboration labels, places or co-authors, so round 2 takes ads from captions. Labels and places come only from a second run of `apify/instagram-post-scraper` in detailed mode for 20 to 30 accounts after round 1 (about 0.8 USD); it also returns a few recent comments. Code computes the numbers; the LLM only sorts captions into topics. Comments are fetched only for accounts in round 3, and only from a few recent posts.
4. **Identity.** The same creator on IG and TikTok (cross-links, same website), fan accounts, namesakes in the news.
5. **Round 4, deep check.** For finalists: more posts, TikTok, YouTube, collaborations, claim vs. evidence, targeted news, skeptic. At most 2 rounds of follow-up searches driven by gaps.
6. **Report and finalist comparison.** See section 6.

**Run budget:** max 60 candidates, round 4 max 5 finalists. Everything is cached by input hash, so changing a criterion recomputes rounds 1 to 3 within seconds, without new scraping. The log shows, for each step, the actor name and "live" or "from cache".

**Cost per run** (Apify price lists as of 8 October 2026, Free plan, breakdown in [apify-pro-krystofa.md](apify-pro-krystofa.md) (Czech)): the Instagram core comes to about 2.8 USD (search including places about 1.5 USD, 60 profiles 0.16 USD, second post run for rounds 2 and 3 about 0.8 USD, round 4 about 0.3 USD). A full run with TikTok, comments, Meta Branded Content, news and YouTube costs about 6 to 7 USD, which is more than the 5 USD monthly credit. On the Free plan, hashtags return only the first page, and comments only the 15 newest per post. For development and the demo, plan on the Starter plan (19 USD per month) unless we get credits.

## 5. Sources and Apify actors

Rule of the brief: do not write a scraper that an actor already covers. Meta's terms forbid automated collection without permission, and since 1/2025 explicitly also without logging in ([Meta, Section 3.2.3](https://www.facebook.com/legal/terms?locale=en_US), [Instagram](https://help.instagram.com/581066165581870)). TikTok forbids automated extraction without written consent ([EEA terms, 7/2026](https://www.tiktok.com/legal/page/eea/terms-of-service/en)). Whether this binds logged-out users is disputed (Meta v. Bright Data, US 2024, [ruling](https://storage.courtlistener.com/recap/gov.uscourts.cand.406956/gov.uscourts.cand.406956.181.0_1.pdf)). We do not scrape anything ourselves and do not log in: we take public data through ready-made Apify actors, as the brief asks, and we also read the public Meta Ad Library (Branded Content) through an actor. We do not claim that this complies with Meta's terms.

| Need | Actor | Note |
|---|---|---|
| Account search on IG | `apify/instagram-search-scraper` (`search`, `searchType: user`, `searchLimit`) | Returns profiles directly, with recent posts (no post location). Max 250 per query, fewer in practice. Always set `searchType`; the default is `place`. No city filter, so the city goes into the query ("cukrárna brno"). According to the README, results come from Google, Facebook Ads and Threads (the `searchSource` field); optional `liveSearch` = live Instagram search. |
| Search through hashtags | `apify/instagram-hashtag-scraper` (`hashtags`, `resultsType`, `resultsLimit`) | Returns posts (not profiles) with `ownerUsername`, `locationName` and `locationId`. We recognize a place in Brno by `locationId` resolved to coordinates; `locationName` is often just a venue name, and many posts have no place. We group posts by author. Only the newest posts, one content type per run. |
| Search by place | `apify/instagram-search-scraper` (`searchType: place`) → `apify/instagram-scraper` with the place URL | Places in Brno (filter by `lat`/`lng`, not by text) → `location_id` → posts from the place → authors. According to the README, a place URL returns a place item with nested `posts[].username`, not posts with `ownerUsername`; the parser handles both shapes. Community alternative: `apidojo/instagram-location-scraper` (cheap; on Free only demo mode: 5 runs per month × 10 items). |
| Search on TikTok | `clockworks/tiktok-scraper` (`searchQueries`, `searchSection: /user`, `maxProfilesPerQuery`, `resultsPerPage`, `proxyCountryCode: CZ`) | `resultsPerPage` defaults to 1, always set it. CZ is a paid add-on (+1.30 USD per 1000 results). Videos have `textLanguage` (caption language) and `locationCreated` (country of creation); a city only for videos with a tagged place (`locationMeta`, unverified on Czech videos). |
| Profiles + last ~12 posts | `apify/instagram-profile-scraper` | 50 accounts in one run. Bio, followers, `businessCategoryName`, `private`, `relatedProfiles` (related accounts, unverified for small accounts), `latestPosts` (caption, likes, comments, type, reel = `productType: clips`, hashtags, mentions, pinned `isPinned`). No post location, collaboration label or `coauthorProducers` here. The "About" add-on (country, creation date, number of name changes) is, according to the schema, for paid accounts only. |
| TikTok profile | `clockworks/tiktok-profile-scraper` | Followers, video stats. `resultsPerPage` defaults to 100; set 12. `authorMeta.region` is probably empty in TikTok public data today (unverified). |
| More posts (round 4, optionally rounds 2 and 3) | `apify/instagram-post-scraper` | Captions, hashtags, mentions, `coauthorProducers`, `locationName`. With `dataDetailLevel: detailedData` also `paidPartnership` and `sponsors` (the paid partnership label, unverified on Czech posts) and `latestComments`. Always set `dataDetailLevel`. `isSponsored` has been dead since 12/2025 (always false). |
| Comments (round 3) | `apify/instagram-comment-scraper` | Post URLs as input, no login. Free: 15 newest comments per post, no replies. Used only for language and the share of generic comments; the output includes commenter names, which we delete on load. |
| TikTok labels | `clockworks/tiktok-scraper` | `isSponsored` = paid collaboration (missing = unknown), `isAd` = promoted ad, not a collaboration. `authorMeta.isUnderAge18` is probably always empty: exclude only on `true`; empty = age unknown. Filter out error items (`errorCode`). |
| YouTube | `streamers/youtube-scraper` | `isPaidContent` = the "Includes paid promotion" label; only `true` is evidence. It cannot search channels by country; we take the channel from links in the bio. |
| Paid collaborations | `apify/brand-collaboration-scraper` (`startUrls`, `resultsLimit`, `onlyPostsNewerThan`) | Official Apify actor; source: the public Meta Ad Library (Branded Content). Only posts with the Paid partnership label since 17 August 2023. Without login, the library lists Czech collaborations but did not display them (unverified whether the actor returns them). [Ready-made recipe](https://raw.githubusercontent.com/apify/awesome-skills/main/skills/apify-influencer-brand-collabs/SKILL.md). |
| News | `data_xplorer/google-news-scraper-fast` | Community actor. `keywords`, `region_language: CZ:cs`, `timeframe: 1y` (the default 1h finds nothing), `maxArticles: 10`, `decodeUrls: true`. Targeted queries only. |

All actors need only an Apify token, with no Instagram or TikTok login. Checked on the actor pages on 8 October 2026; we check the outputs of real runs in the first 45 minutes of building. Exact inputs, outputs and tests: [apify-pro-krystofa.md](apify-pro-krystofa.md) (Czech).

## 6. Output

**Funnel board:** rounds, counters such as "48 in → 22 left", candidate cards, eliminated candidates with a reason.

**Candidate card:** content type (topic chart, format, frequency), audience (interactions, comment language, local signals, authenticity signals), criteria met / not met / cannot verify, with a source. No overall score.

**Finalist report** (ILLUSTRATION, the creator is fictional):

| Claim (where and when) | Evidence | Status | Confidence |
|---|---|---|---|
| "Exclusive ambassador of brand A" (IG bio, 1 Oct 2026) | 2 posts with a collaboration with competing bakery B, 9 Sep and 21 Sep 2026 | Conflicts with record | high (own posts) |
| "Review, nobody pays me" (post, 12 Sep 2026) | A discount code and an affiliate link in the caption. We found no collaboration label. | Unsupported, open question | medium |
| "Community of 120 thousand" (bio) | Median interactions 1.1% of followers over 24 posts, 38% of comments only emoji | Signal, not a verdict | low |

Also in the report: a timeline of collaborations (competitors highlighted), commercial saturation, work-related news (allegation vs. confirmed), questions for the first meeting, an outreach draft (NOT SENT, Copy only), what we did not check and why, the identity panel. Colors: green = fact, orange = inference, gray = gap.

**Finalist comparison:** side by side by criteria, ranked only by a criterion the owner picks.

## 7. Different goal = different result

Same list of candidates, different business:

| | Bakery in Brno | Fitness studio in Brno |
|---|---|---|
| Content type | food, recipes, local tips | sport, exercise, local tips |
| Audience | families and young people, Czech, Brno | young active people, Czech, Brno |
| Competitors | other bakeries and chains | other studios and fitness apps |
| Result | different finalists, different eliminations | different finalists, different eliminations |
| Deep check | collaborations with bakeries, food reviews | collaborations with supplement brands and studios |

In the video: who dropped out under only one goal, and why. And for a finalist shared by both goals, different findings in the report.

## 8. Demo (90 s)

> Replaced by [video-script.md](video-script.md); kept as written in v6.

| s | Screen | Voice-over |
|---|---|---|
| 0-8 | Bakery owner in front of a phone | "I want to work with an influencer, but I don't know who." |
| 8-25 | Chat: 4 questions → criteria with explanations. The owner tries "believers only", the chatbot refuses | "The chatbot turns the business into criteria. Anything that would mean judging faith or opinions, it refuses." |
| 25-45 | Live funnel: 48 → 22 → 11 → 5, cards drop with reasons (for recording, the backend runs with `MOCK_LATENCY=0.8`; otherwise the rounds finish in ~1 s) | "Every elimination has a round, a reason and a source." |
| 45-62 | Finalist report: collaboration timeline, mismatch with the exclusivity claim | "On the left, what they claim. On the right, what their posts show." |
| 62-76 | Goal switched to a fitness studio | "Different business, different finalists. Data from cache, recomputed in seconds." |
| 76-84 | Outreach draft NOT SENT, questions for the meeting | "The owner decides. We show the evidence." |
| 84-90 | Validation and limits | Only numbers we actually measure. |

**Live vs. cache:** we show the conversation, the round recomputation and the goal switch live. Scraping comes from the cache, and the screen says so.

**Protecting people in the video:** real creators will appear in the funnel. Names of eliminated accounts are blurred in the video. The deep check is shown on a creator who gives consent, or on a team member using their real profiles. Do not create new accounts or fake posts. Protection of personality: Sections 81 to 87 of the Civil Code (občanský zákoník), especially Section 85 (spreading someone's likeness only with consent) and Section 87 (consent can be withdrawn) ([text](https://www.zakonyprolidi.cz/cs/2012-89)).

## 9. Validation (what we can do overnight)

> Tonight's version with pass rules: [validation-plan.md](validation-plan.md).

1. **Search:** for 30 found accounts, check by hand whether they really fit the brief (e.g. a local food creator).
2. **Content type:** for 50 posts, label the topic by hand and compare with the LLM.
3. **Comment language:** for 100 comments, compare language detection with a manual check.
4. **Eliminations:** for 20 eliminated accounts, check by hand whether the reason is right.
5. **Collaborations and labeling:** for 3 finalists, count collaborations and labels over 90 days by hand.
6. **Sensitive filter:** 20 hand-picked sensitive items, and how many the filter caught. Plus 10 sensitive criteria in the chat, and how many the chatbot refused.
7. **Citations:** for every claim, we check automatically that the quoted text really is at the URL.

Only numbers we actually measure go into the video and the README, failures included.

## 10. Rules and how we meet them

| Rule | How |
|---|---|
| Public data only | Public profiles, the public Meta Ad Library (Branded Content) read through an Apify actor, news. No login. We do not solve any CAPTCHA ourselves and do not write our own scraper; we only use actors maintained by Apify (according to their changelogs, they handle blocking themselves). Login walls and blocks (`PROFILE_EMPTY`, `AGE_RESTRICTED`) are a gap in the report. A private account is out in round 1. |
| No Art. 9 inference | The chatbot refuses sensitive criteria; no "views"; no age, gender or origin for the audience; a sensitive filter before storage; the number of skipped items is in the report. We do not take criminal matters or fines for administrative offences (Art. 10, C-439/19). |
| No score of a person | Criteria met / not met with a source, no overall number and no "best". Ranking only by the owner's criterion. A human decides. As a product, according to the Commission's draft guidelines (19 May 2026, with the example of searching for contractors on social media), it would be a high-risk system under Annex III point 4(a) of the AI Act, even when a human decides ([draft guidelines](https://digital-strategy.ec.europa.eu/en/library/draft-commission-guidelines-classification-high-risk-ai-systems)). The obligations apply from 2 December 2027 ([Regulation 2026/1744](https://eur-lex.europa.eu/legal-content/EN/TXT/HTML/?uri=CELEX:32026R1744)); a hackathon prototype is not placed on the market. |
| A source for every claim | Criteria and claims have a URL, a quote and a date. |
| Fact vs. inference, gaps | Colors, inferences cite facts, a "What we did not check" section. |
| Different goal = different content | Different criteria, eliminations, finalists and findings (section 7). |
| Namesakes | Identity panel: the same creator across networks, fan accounts, namesakes in the news. |
| Outreach not sent | Outreach draft with a Copy button only. |
| Minors | Public data has no reliable age (IG has no age field, TikTok `isUnderAge18` is probably empty). An explicit age under 18 in the bio, or `isUnderAge18: true`, means elimination in round 1, and the data is not stored. A finalist without confirmed adult age does not go into the report until the owner verifies it. |
| Data minimization | For eliminated accounts, only the account name and the reason. `purge` deletes the cache, LLM outputs and Apify run data right after the results are announced. |
| Live run | At least one run live; the cache is labeled on screen. |

## 11. Originality: let's be honest

**What already exists:**
- **Directly on Apify:** `apify/influencer-discovery-agent`, Apify's own actor. It finds creators from a natural-language description, on TikTok only (max about 50 profiles per run), and gives them an AI fit score from 0 to 1. It has no location input and returns only a country code. 100 USD per 1000 profiles. The jury almost certainly knows it, so we must mention it in the pitch ourselves. A closer competitor is `hypebridge/influencer-discovery-agent-instagram-tiktok`: a natural-language brief, Instagram and TikTok, the `location` field also accepts a city, output score 0 to 10 ([Apify](https://apify.com/hypebridge/influencer-discovery-agent-instagram-tiktok)). Also `influship/influencer-search` (Instagram only, filters on followers and engagement, location only in the query text, match score 0 to 1) and `alizarin_refrigerator-owner/influencer-discovery---find-influencers-across-social-platforms` (a `locations` field with cities, 5 networks, sends emails on its own). The data part of our rounds 1 to 3 is also described in Apify's official recipe ([influencer vetting](https://github.com/apify/agent-skills/blob/main/skills/apify-ultimate-scraper/references/workflows/influencer-vetting.md)).
- **Paid services:** Modash (380 million+ profiles above 1,000 followers, creator and audience location down to city level on IG, public ranking [Top 20 Brno](https://www.modash.io/find-influencers/czech-republic/brno), from 199 USD per month billed annually, 299 USD billed monthly, [pricing](https://www.modash.io/pricing)), HypeAuditor (audience location filter for up to 3 countries, cities too in Discovery, "Audience Quality Score" 1 to 100, [AI Scout](https://help.hypeauditor.com/en/articles/15693186-ai-scout) picks up to 50 creators from a brief in chat, with explanations), Heepsy (also a free plan, location down to city level, [search](https://www.heepsy.com/influencer-search)), Kolsquare (Compliance Score rates how IG posts over 3 months label ads, [blog](https://www.kolsquare.com/en/blog/kolsquare-launches-compliance-score-feature)), Influee (a global marketplace from the US that also covers Czechia, from 229 USD per month, its own creator score). Emplifi (a US company that grew out of the Czech Socialbakers) has an enterprise creator module: 30 million+ creators, an AI brand fit score ([Emplifi](https://emplifi.io/product/influencer-management/)).
- **Brand safety:** Viral Nation (also sells an "evidence packet" with reasons), Phyllo, Captiv8, Ferretly, Upfluence, the n8n template "Instagram via Apify + LLM score" ([#11808](https://n8n.io/workflows/11808-influencer-brand-safety-auditor-with-engagement-analysis/)).

**How we differ:**
1. For a layperson: the chatbot turns a conversation into explicit criteria that the owner sees, edits and can veto, and it refuses sensitive criteria. A chat that turns a brief into a list of creators already exists in HypeAuditor (AI Scout).
2. A transparent funnel instead of an AI number: reversible rounds based on the owner's criteria, and every elimination has a round, a reason and a source. All competitors we found give a summary score (Apify agent 0 to 1, hypebridge 0 to 10, HypeAuditor 1 to 100).
3. Location backed by evidence: the claim "creates in Brno" links to specific posts with a place in Brno, or to the bio, not to a database estimate. City-level search on its own is not unique (Modash, Heepsy, hypebridge).
4. Audience from public signals (comment language, location, authenticity), with the gaps stated honestly.
5. The deep check of finalists as claim + evidence pairs, not a flag or a score. Checking ad labeling is not new by itself (Kolsquare); what is new is showing the specific posts and explaining to the owner their liability under Czech rules.
6. The chatbot refuses discriminatory criteria. Competitors (HypeAuditor, Phyllo) instead flag "politics", and HypeAuditor even religion ([HypeAuditor](https://hypeauditor.com/solutions-for/brands/)).
7. Pay per run, in single-digit dollars, instead of a SaaS subscription. We do not win on price against agents on Apify (0.10 to 0.15 USD per profile).

Honest pitch line: "Creator search tools exist, even on Apify. We are a guide for a bakery owner in Brno that shows why each candidate dropped out and checks what the finalists claim."

## 12. Risks and what to cut

- **Search quality:** hashtags are noisy (businesses, foreign accounts, aggregators), and account search has no city filter. Rounds 1 and 2 must filter this out. Business accounts: `businessCategoryName` comes as comma-separated text, including "None" (e.g. "None,Candy Store"), and creators often have a category too, so on its own it eliminates no one. Fallback: the owner pastes their own list.
- **Apify Free plan:** for hashtags only the first page, 15 newest comments per post, `apidojo/instagram-location-scraper` in demo mode only (5 runs per month × 10 items), the About add-on and comment replies only on paid plans. A full run (about 6 to 7 USD) does not fit in the 5 USD credit. For the demo we need a paid plan or credits.
- **Time and cost:** 60 profiles in one batch, comments only for those left, round 4 max 5 finalists. The cache is a must.
- **The audience is only an estimate.** Comment language and post locations are not demographics. Say so in the report.
- **Meta Branded Content may not return Czech collaborations.** The library is worldwide since 17 August 2023, but only for posts with the Paid partnership label. Without login, it lists Czech collaborations but did not display them (Rohlík.cz 10, Notino.cz 4, Alza 2 results, 0 rows; Nike 17 of 21, [Ad Library](https://www.facebook.com/ads/library/branded_content/)). Test at 0:00 to 0:45: rohlik.cz, with nike as a control; if the Czech one returns 0, cut it right away. An empty result means "not found in the Meta library", not "has no collaborations". Fallback: labels on IG (`paidPartnership`), TikTok and YouTube, hashtags, discount codes.
- **Real people in a public video:** blur eliminated accounts, deep check only with consent.
- **Cut in this order:** YouTube → outreach draft → Meta Branded Content → news in round 4 → goal switch as a separate screen. Never cut the chatbot, the funnel or the candidate card.

## 13. Schedule (times from the start of building)

> As planned before the build; kept for the record.

**Roles:** A: actors (search, profiles in a batch, comments, TikTok), cache. B: chatbot with tools, round logic, topic sorting, comment language, deep check, sensitive filter. C: from the start, UI on top of static JSON (chat + board, funnel, cards, report), finding the demo creator, validation, video. Solo: Instagram only, rounds 1 to 3 and a simple deep check, UI in Streamlit.

| When | What | Done when |
|---|---|---|
| 0:00-0:45 | **Source test** | search-scraper ("cukrárna brno"), hashtag-scraper with `locationId`, profile-scraper on 50 accounts, post-scraper with `detailedData` (`paidPartnership`), comment-scraper, tiktok-scraper with and without CZ, brand-collaboration-scraper (rohlik.cz + nike). Whatever returns no data gets cut. Order and inputs: [apify-pro-krystofa.md](apify-pro-krystofa.md) (Czech). |
| 0:45-2:00 | Skeleton + demo creator | repo, schema (Candidate, Criterion, Round, Claim, Evidence), cache. Find a creator who consents. |
| 1:00-3:00 | Search + rounds 1 and 2 | account list, basics, content topics |
| 3:00-4:30 | Chatbot + round 3 | conversation → criteria JSON, audience, refusing sensitive criteria |
| 4:30-6:00 | Round 4 | collaborations, claim vs. evidence, news |
| **6:00** | **Full run in the finished UI** | commit; main does not break from here on |
| 6:00-7:30 | Identity, skeptic, bringing candidates back | identity panel, elimination reasons |
| 7:30-8:30 | Goal switch, finalist comparison, outreach draft | the two goals differ in finalists |
| 8:30-9:30 | Validation + README | numbers, failures, limits |
| 9:30-end | Video + submission | max 90 s, cache labeled |

## 14. Questions for mentors

1. For finding Czech creators, is `instagram-search-scraper` (accounts) better, or hashtags with a place filter? And how do you see `influencer-discovery-agent` and `hypebridge/influencer-discovery-agent-instagram-tiktok`, given that we are building something similar?
2. Does `brand-collaboration-scraper` return Czech collaborations that the Meta Ad Library does not display without login? (Live test T8: no. Meta Branded Content is cut.)
3. Do we have credits for the hackathon? We estimate the Instagram core run at 2.8 USD and a full run at 6 to 7 USD; with development and tests, that is dozens of runs.
4. Is it enough to blur eliminated accounts in the public video and show the deep check only with consent?
