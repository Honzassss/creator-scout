# Creator Scout: HQ submission form (paste-ready)

One section per field of the HQ form, in form order. Paste the text inside each block. The comment under each block is its length, counted with Python `len()` (line breaks included). Sources: [submission.md](submission.md), [README.md](../README.md), [validation-results.md](validation-results.md), [demo-setup.md](demo-setup.md), [pitch.md](pitch.md). Measured numbers only.

## 01 Project · Project name *

```text
Creator Scout
```
<!-- 13 characters -->

## 01 Project · One-line pitch *

```text
A research agent that helps a small business owner check a social-media creator: every fact links to its source, gaps are stated, and there is no score.
```
<!-- 152 characters -->

## 02 Story · What it does *

```text
The problem. The owner of a small business, such as a bakery or a fitness studio in Brno, wants to work with a local Instagram or TikTok creator. She is not a marketer. She does not know whom to pick, by what rules, or what to check. Creator tools are built for marketers and give scores she cannot verify. Under Czech advertising law, the business that pays for a post shares liability with the creator if the post is an unlabeled ad, so she needs to know what the creator actually posted and with whom.

Who it is for. Owners of small local businesses who are not marketers.

How the agent solves it. She gives one account (an Instagram or TikTok @handle or profile link), one anchor (the city, the website or the Czech company ID) and a goal, such as "my bakery in Brno". The agent then:
- turns the goal into explicit criteria, each with a reason, that she can edit or switch off. Criteria about religion, politics, health, ethnicity, sexuality, looks or private life are refused.
- fetches public data through Apify actors: the Instagram profile and posts, post details with paid labels, co-authors and comments, TikTok and YouTube profiles, and Google News.
- decides whether this is the account she means (confirmed, likely, uncertain or not found), lists the signals for and against, and sets aside namesakes in the news and look-alike or fan accounts.
- checks collaborations, including with competitors she names, and sets the creator's own claims against their posts.
- writes a report split into facts, inferences and gaps. A fact carries its URL, fetch date, Apify actor, a live, cache or mock label and a quote from the fetched item. An inference cites the facts it rests on. A gap is stated and becomes a question for the first meeting. Each finding has a confidence and its basis.
- drafts an outreach message marked NOT SENT.

If she switches the goal, for example from bakery to fitness studio, the report is rebuilt from the stored data with no new fetch and no LLM request, and a "What changed" panel lists the differences. A "How this report was built" panel and a run log show what was fetched, what was filtered, and which steps used rules or an LLM.

A second entry point starts from a short chat and narrows public accounts in rounds (basics, content, audience signals). Every elimination shows its round, reason and source, and can be undone.

There is no overall score and no "best creator". Sensitive content is filtered before it is stored in a run, commenter identities are never stored, accounts detected as minors are dropped, and nothing is sent. The owner decides.
```
<!-- 2598 characters of max 3000 -->

## 02 Story · What works end-to-end *

```text
Scenario in the video. Input: @kamvbrne, anchor Brno, goal "Bakery in Brno", bakery competitors named. Output, replayed from the cache: identity "likely" (2 supporting signals), 10 news results not about the account set aside, the check "No competitor collaboration" not met with links to the co-authored posts, and questions for the first meeting. Switching to a fitness studio turns that check into "cannot verify", with no new fetch.

Definition of done, on 2 public Brno accounts (@kamvbrne, @foodguidebrno), replayed from the cache with no API keys:
- Subject + one anchor + goal: @handle + Brno + bakery gives a report for both.
- Every claim links to a source: 83 of 83 facts have a source URL. 134 of 134 quotes found word for word in the fetched items. 501 of 501 sources labeled live, cache or mock.
- Facts split from inferences, gaps stated: 83 facts, 4 inferences that cite their facts, 13 gaps that become questions. 0 of 100 findings lack a confidence and basis.
- Same subject, different goal, different report: bakery to fitness in under 0.4 s, 0 Apify calls, 0 LLM requests. Questions and the outreach draft change for both. A check result changes for 1 of 2 with no competitors named.
- A real subject researched live: both through Apify on 9 Oct 2026, 275 s and 326 s, about 0.19 and 0.16 USD.
- Namesakes and look-alikes handled: verdict "likely" on both. With a wrong anchor (Ostrava), @kamvbrne is "uncertain" and not matched. 10 and 3 unrelated news items set aside. Look-alike and fan accounts: set aside on MOCK only.
- The user sees how it was built: a "How this report was built" panel, a source chip on every fact, a run log naming the actor on every line.
- Out of scope: no score, no scraper of our own, public profiles only, outreach never sent; 0 score fields and 0 commenter identities stored.

Pass rules were fixed before measuring (scripts/validate_run.py). Refusal guard: 9 of 10 sensitive requests refused, 0 of 5 normal ones.
```
<!-- 1965 characters of max 2000 -->

## 02 Story · What is simulated, missing or fragile *

```text
- The video replays the 9 Oct live recordings from the cache, labeled CACHE. No live fetch on camera.
- The discovery funnel in the video is MOCK (fictional creators). On recorded real Brno data it ends with 0 or 1 finalist.
- Real discovery was not re-run live after the engine fixes, only replayed from the cache.
- The live demo link is a static MOCK replay: fictional data, no backend, no Apify or LLM calls. Real data runs locally from the cache.
- Meta Branded Content returned nothing for Czech brands, so we cut it. Collaborations come from paid labels, co-authored posts, ad hashtags and discount codes.
- On the 2 real subjects, 0 creator claims were checked against posts.
- Minors are caught only by a provider flag or a stated age under 18 in the bio; TikTok leaves its age flag empty. Age is a gap, not a filter.
- LLM: the OpenRouter free model wrote meeting questions and some vetting text, but claim extraction fell back to rules in both real runs; its output quality was not measured. No Anthropic key was used, so Claude was not run live. All validation numbers come from the rule-based fallback.
- The keyword sensitive filter misses paraphrases and slang: 16 of 20 sensitive and 2 of 20 harmless texts dropped on our own list (fail, the rule was 18 of 20). That list was used for tuning. A reviewer's held-out list gave 12 of 20 and 3 of 20.
- The refusal guard refused 9 of 10; it missed a Czech request to rank by "best overall".
- The goal-switch check passed for 1 of 2 subjects: with no competitors named, @kamvbrne got new questions and a new outreach draft but no changed check result.
- Both real accounts reach "likely", not "confirmed": with a city anchor, "confirmed" also needs a matched profile on another platform, and neither has one.
- Thin evidence: 2 real subjects, no repeat runs, no manual checks by a person, company ID anchor not tested.
- Apify spend (about 3.1 USD) is the app's estimate, not checked in the Apify console.
```
<!-- 1967 characters of max 2000 -->

## 02 Story · Stack and partner tools

```text
Apify for all platform data (Free plan, about 3.1 USD spent on 9 Oct 2026), called through apify-client. Actors:
- apify/instagram-search-scraper: discovery, user and place search
- apify/instagram-hashtag-scraper: discovery, authors of hashtag posts
- apify/instagram-scraper: discovery, authors of posts at Brno places
- apify/instagram-profile-scraper: profile and 12 latest posts
- apify/instagram-post-scraper: paid labels, places, co-authors, latest comments
- clockworks/tiktok-profile-scraper: cross-platform identity, TikTok posts
- clockworks/tiktok-scraper: TikTok user search (off by default)
- clockworks/tiktok-comments-scraper: TikTok comments (not live-tested)
- data_xplorer/google-news-scraper-fast: news about the creator, namesake check
- streamers/youtube-scraper: YouTube channel from a bio link
Tested and cut: apify/brand-collaboration-scraper (Meta Branded Content, empty for Czech brands). Not needed: apify/instagram-comment-scraper (the post scraper returns comments).

Backend: Python, FastAPI, Pydantic, httpx, lingua-language-detector, pytest. Frontend: React, TypeScript, Vite, Tailwind CSS. LLM: OpenRouter free tier (dots-studio/dots-3-note-preview:free) with a rule-based fallback for every task; the Anthropic Claude API is supported in code but was not run live. Static MOCK demo hosted on Vercel. Built with Claude Code.
```
<!-- 1358 characters -->

## 03 Code · GitHub repository *

```text
[PUBLIC REPO URL]
```
<!-- 17 characters -->

Note (do not paste): Replace with the public URL before submitting. The jury must be able to read it without access.

## 03 Code · Live demo link

```text
https://creator-scout-demo.vercel.app
```
<!-- 37 characters -->

Note (do not paste): Static MOCK demo replay in the browser: fictional data, no backend, no Apify or LLM calls. Said in the limitations field.

## 04 Video · Unlisted YouTube link *

```text
[YOUTUBE URL]
```
<!-- 13 characters -->

Note (do not paste): Upload with visibility Unlisted, max 90 s, then paste the link.

## 05 Showcase · ElevenLabs

```text
Not used. Do not tick.
```
<!-- 22 characters -->

Note (do not paste): The public results page checkbox is your call.
