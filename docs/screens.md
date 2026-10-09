# Screens and features

Short version for design and the demo. English version of [kostra-aplikace-cz.md](kostra-aplikace-cz.md) (plan version 6, 2026-10-08), with the subject mode entry point added on 2026-10-09.

- Plan with all details (Czech): [brand-fit-cz.md](brand-fit-cz.md)
- Fact check of the plan: [verification.md](verification.md)
- Apify actors, live test results and data notes (Czech): [apify-pro-krystofa.md](apify-pro-krystofa.md)
- Models, API and hard lines: [architecture.md](architecture.md)

**Status labels in this file.** "Built" means it is in the code now. "Planned" means it is being built tonight and is not done. Numbers marked "design estimate" come from the plan and are not measured yet.

**One sentence.** A small business owner tells a chatbot who they are looking for. The app finds candidate creators, drops them in several rounds based on content and audience, and checks the finalists in depth. Every step shows why and which source it used.

**Who it is for.** The owner of a bakery, a cafe or an online shop who does not know which creator to pick or how to judge one. Second: marketing and PR agencies.

## 0. Two ways in

Both use the same screen (chat + board) and the same report format.

**A. Find creators (discovery mode).** Built. The owner describes the business. The app finds candidates and narrows them down (sections 1 to 7). Without an Apify token it runs on fictional MOCK data, labeled MOCK in the UI. With a token it fetches live through Apify actors; the provider was live-tested on 2026-10-09, and the first real Brno run is being recorded into the cache.

**B. Research one subject (subject mode).** Planned, not done. This is the input shape of the official brief.
- Input: one subject (an @handle), one anchor (a city, a website or a company ID; the company ID is matched only as text in public data, with no registry lookup) and a goal (for example "bakery in Brno, more people in the shop").
- The app skips the funnel and goes straight to the subject report. Same layout as the finalist report (section 5): every claim links to a source, fact is split from inference, gaps are stated.
- The anchor tells the subject apart from namesakes, fan accounts and look-alikes. The identity panel shows which accounts were matched and which were set aside, with the reason.
- "Change goal" re-renders the report from the cache, with no new fetch, and shows what changed between the two goals.

## Layout: chat + board

One screen, two parts:
- **Left: chat** (the guide). It asks, explains, proposes criteria, runs rounds and answers "why was X dropped?".
- **Right: board** (what is happening). Criteria, the funnel with its rounds, candidate cards, finalists.

On a phone, tabs switch between Chat and Board.

UI language: English by default is planned. The current build defaults to Czech with an English toggle.

## 1. Opening interview

The chat walks a non-expert through it step by step:
- "What do you sell, and where?" → a bakery, Brno
- "Who do you want to sell to?" → families, young people in Brno
- "What should the campaign do?" → more people in the shop, a new product
- "Roughly how much can you spend?" → a rough figure, used to size the creator
- "Do you have competitors the creator should not work with?"

Then it proposes **criteria** in plain words and gives a reason for each: "For a bakery in Brno, a local food creator with 5,000 to 50,000 followers makes sense. Smaller creators often have a closer relationship with their audience and are easier to afford."

**Refusal.** If the owner asks for a criterion based on religion, politics, health, sexuality or origin, the chat politely refuses and explains why. This is a good moment for the video.

## 2. Criteria panel

Chips that can be edited with a click or in the chat:
- **Content type:** food, recipes, local tips, family, lifestyle. Format: reels, photos, videos.
- **Audience:** language (Czech), location (Brno and around), size (5,000 to 50,000), audience activity (minimum interactions).
- **Collaborations:** no work with competitors, labels ads, no more than X % of posts are ads.
- **Gray chips** with an explanation: criteria we do not check (religion, politics, a person's "values").

## 3. Funnel with elimination rounds

The main element of the board. Candidates are cards that drop aside round by round.

| Round | What is checked | Typically left (design estimate) |
|---|---|---|
| 0. Search | hashtags, keywords and places → list of accounts | 40 to 60 |
| 1. Basics | public account, Czech, size, active in the last 30 days | 20 to 30 |
| 2. Content | what they post about, share of relevant posts, format, frequency | 10 to 15 |
| 3. Audience | interactions, comment language, local signals, audience authenticity | 5 to 8 |
| 4. Deep check | collaborations, competitors, ad labeling, news | 3 to 5 finalists |

- Each round has a counter: "entered 48 → kept 22".
- An **eliminated card** shows the round and the reason with its source: "Round 2: only 2 of 12 posts are about food".
- When data is missing (empty profile, login wall, no labeled collaborations found), the candidate is not dropped. The criterion gets "cannot verify".
- Clicking an eliminated card brings the candidate back ("this criterion does not apply to them").
- Round 4 costs more, so the chat asks first: "Deep-check these finalists?"

## 4. Candidate card

- Avatar, account name, followers, category, link.
- **Content type:** topic bar (for example 60 % food, 25 % family, 15 % other), format, posting frequency.
- **Audience:** median publicly visible interactions per post (likes and comments), interactions relative to followers, share of comments in Czech, local signals (places in posts, mentions of Brno), authenticity signals (for example "38 % of comments are emoji only"). Label: "estimate from public data, not demographics".
- **Criteria:** each one met / not met / cannot verify, with its source. **No overall score.**

## 5. Finalist report (round 4)

The same report is the output of subject mode (planned).

- **Collaboration timeline:** brand, date, platform, labeled yes/no. Competitors highlighted.
- **Claim card:** a pair "what the creator claims" ↔ "what their posts show", a status (Supported / Conflicts with record / Unsupported / Cannot verify), confidence, source and date.
- **Commercial saturation:** what % of posts are ads.
- **News:** article, outlet, date, tag "allegation" or "confirmed".
- **Questions for the first meeting** with the creator.
- **Outreach draft:** tag NOT SENT, only a Copy button. No send function exists.
- **What we did not check, and why.**
- **Colors:** green = fact with a source, orange = inference, gray = gap.

## 6. Comparing finalists

- Finalists side by side by criterion. Every cell clicks through to its source.
- Sorting only by a criterion the user picks (for example by interactions). No "best creator". The owner decides.

## 7. Different goal = different result

- "Change goal" button: same candidate list, a different business or campaign (bakery vs. fitness studio).
- Different criteria → different eliminations → different finalists. Show the difference: who dropped out only for one goal, and why.
- In subject mode (planned), the same button re-renders the one subject report from the cache and shows what changed.

## 8. Live run

- Steps and a log with sources: "Instagram: 48 accounts", "TikTok: 20 accounts". Every object is labeled **live**, **cache** or **MOCK**.
- A first real Brno run is being recorded into the cache now (planned). When the demo replays it, it is labeled cache.
- The chat comments as it goes: "I removed 14 accounts that post mostly in English."
- **Sensitive filter counter:** "4 items skipped (sensitive categories)".

## 9. Bonus, only if time is left

- **Voice guide (ElevenLabs):** the chat speaks, or a 30-second summary of the finalists.

## Design rules

- An elimination is always **criterion + reason + source**, never "unsuitable person".
- No overall score, no traffic lights, no "Not recommended". The owner decides.
- Nothing about the creator's opinions, private life, diet, or photos posted by other people.
- About the audience, only estimates from public data. We do not estimate audience age, gender or origin.
- Neutral words: "does not meet the criterion", "conflicts with the record", "allegation".
- Every value clicks through to its source.
- Works on a narrow screen.

## Behind the scenes (for development)

| Function | What it does |
|---|---|
| Chat | Claude with tools: propose criteria, run a round, explain an elimination, write an outreach draft. An OpenRouter path is being finished now (planned). Without a key, every LLM task has a deterministic fallback, labeled in the UI. |
| Search | hashtags, keywords and places on IG and TikTok → list of accounts |
| Rounds 1 to 3 | profiles and the last ~12 posts in one batch, numbers computed in code, LLM only for content topics. The paid-partnership label is not in the profile data. Ads are read from captions; labels can come from an optional second post-scraper run (the IG paid-partnership label came back true on 3 of 3 labeled test posts on 2026-10-09; not yet seen on a Czech post, so false means unknown). |
| Sensitive filter | drops sensitive criteria and sensitive content before storage |
| Round 4 | deep check of finalists: collaborations, claim vs. evidence, news. Meta Branded Content was cut after the live test (nothing for Czech brands); collaborations come from platform labels, ad hashtags and discount codes. |
| Identity | namesakes, fan accounts, the same creator on IG and TikTok. In subject mode (planned), the anchor decides which account is the subject. |
| Age | no reliable age signal in public data. TikTok region and under-18 fields came back empty in the live test. An explicit age under 18 in the bio drops the account; otherwise age is a gap, not a filter. |
| Cache + live stream | rounds from the cache in seconds, live only for new queries |
| Delete data | deletes the cache, runs and LLM outputs in the backend's data folder. Raw live-test items (`data/live-tests/`) are deleted separately with `scripts/live_tests.py --purge`. |
