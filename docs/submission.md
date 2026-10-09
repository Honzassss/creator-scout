# Creator Scout: HQ submission text

Draft for the hackathon HQ form (Apify track), written 9 Oct 2026 at about 05:10 from [README.md](../README.md), [pitch.md](pitch.md), [validation-results.md](validation-results.md) and [demo-setup.md](demo-setup.md). Every number below is a measured one from those files. Character limits are noted per field; the field text is plain so it pastes cleanly.

## Project name

Creator Scout

## Tagline (max 80 characters)

Sourced creator checks for small businesses. No score: the owner decides.

## Short description (max 600 characters)

Creator Scout helps a small business owner, such as a bakery in Brno, decide which social-media creator to work with. She names an account, one anchor (city, website or company ID) and a goal. The app turns the goal into criteria she can edit, checks public data fetched through Apify actors, and writes a report in which every fact links to its source, inferences cite their facts and gaps become questions. Switch the goal and the report changes with no new fetch. No score, no "best creator".

## Longer description (max 1500 characters)

Definition of done. Input: an Instagram or TikTok @handle, one anchor and a goal; discovery starts from a short chat. Every fact carries its URL, fetch date, Apify actor and a live/cache/mock label; inferences cite their facts; gaps are stated and become first-meeting questions. A goal switch re-renders the report from stored data (0 Apify calls, 0 LLM requests) and shows what changed. An identity verdict lists signals for and against; namesake news is set aside. A "How this report was built" panel and the run log show every step. 2 public Brno accounts were researched live through Apify and replay from the cache, labeled CACHE.

Value: a non-marketer gets a sourced decision aid, not a ranked list. Originality: editable criteria with a reason each, sensitive criteria refused, every funnel cut with round, reason and source. Working end to end: subject mode ran live on 2 real subjects; discovery runs end to end on MOCK, on recorded real data it ends with 0 or 1 finalist. Technical: one provider protocol behind Apify, cache and mock, write-through cache, rule-based fallback for every LLM task, backend tests. Validation: pass rules fixed before measuring; on the 2 real subjects 83 of 83 facts sourced, 134 of 134 quotes found; refusal guard 9 of 10. 2 failures reported: the goal switch changed a check result for 1 of 2 subjects; the keyword sensitive filter dropped 16 of 20 on a tuned list, not held out.

## Links

- Repository: https://github.com/Honzassss/creator-scout (private; jury access to be granted)
- Online demo: https://creator-scout-demo.vercel.app (noindex). A static MOCK replay that runs in the browser with canned fictional data. It has no backend and makes no Apify or LLM calls. The real-data reports run locally from the cache, see `docs/demo-setup.md`.
- Video (max 90 s): TODO, add the link before submitting.

## What is real / cached / mocked / missing

- **Real (on `main`):** subject mode, the discovery funnel (rounds 0 to 4, undo), the goal switch with a diff, the refusal guard for sensitive criteria, the outreach draft marked NOT SENT, the English UI. The Apify provider was live-tested on 9 Oct 2026 (T1 to T12 except T7, about 1.11 USD).
- **Cached:** the 2 real subject runs, @kamvbrne and @foodguidebrno (anchor Brno, bakery then fitness studio), recorded live through Apify on 9 Oct 2026 (275 s and 326 s, about 0.19 and 0.16 USD) and replayed from the cache in under 0.4 s, labeled CACHE. The real Brno discovery runs are cached too; they were recorded before the engine fixes and not re-run live after them.
- **Mocked:** the online demo is a static MOCK replay. The repo ships 48 fictional MOCK candidates so the app runs with no keys; names end in "(MOCK)", URLs use `*.mock.invalid`, and the UI shows a MOCK badge.
- **LLM:** the OpenRouter free tier was used live in part (meeting questions, some vetting text); claim extraction fell back to rules in both real runs. The Claude path was not run live. Every validation number comes from the keyless rule-based fallback; LLM output quality was not measured.
- **Missing:** audience age, gender and origin (by design); TikTok region and under-18 flags (absent at the source); Meta Branded Content (empty for Czech brands, cut); company-ID anchor not validated; the 4 manual checks (M1 to M4) not measured; the held-out sensitive list not re-measured.

## Apify actors used

| Actor | Used for |
|---|---|
| `apify/instagram-search-scraper` | Discovery: user and place search |
| `apify/instagram-hashtag-scraper` | Discovery: authors of hashtag posts |
| `apify/instagram-scraper` | Discovery: authors of posts at Brno places |
| `apify/instagram-profile-scraper` | Profile and 12 latest posts |
| `apify/instagram-post-scraper` | Paid labels, places, co-authors, latest comments |
| `clockworks/tiktok-profile-scraper` | Cross-platform identity, TikTok posts |
| `clockworks/tiktok-scraper` | TikTok user search (off by default) |
| `clockworks/tiktok-comments-scraper` | TikTok comments (not live-tested) |
| `data_xplorer/google-news-scraper-fast` | News about the creator, namesake check |
| `streamers/youtube-scraper` | YouTube channel from a bio link |

Tested and cut: `apify/brand-collaboration-scraper` (Meta Branded Content, empty for Czech brands, off by default). Not needed: `apify/instagram-comment-scraper` (the post scraper returns comments).

Apify spend on 9 Oct 2026 (Free plan): about 3.1 USD in total. Live tests 1.11 USD, first real Brno discovery runs about 1.63 USD, 2 real subject runs about 0.35 USD. A goal switch or a cache replay costs 0. These are the app's own estimates from the run logs; the settled total in the Apify console was not checked.

## Validation (measured, for the description or a jury question)

Measured on `main` at `edacfa1` with `scripts/validate_run.py`, no API keys (0 Apify calls, 0 LLM requests). Real data = cache replay of the 2 live subject recordings. MOCK runs are not counted as validation.

- Every fact has a source: 83 of 83 (A1, pass).
- Quotes found word for word in the fetched item: 134 of 134 (A2, pass).
- Identity verdict on both real subjects; a wrong anchor (Ostrava) comes out "uncertain" and is not matched (A5, pass).
- 501 of 501 source references labeled; 0 score fields; 0 commenter identities in 71 stored comments (A6, A7, pass).
- Goal switch changes a check result: 1 of 2 real subjects (A4, fail for @kamvbrne).
- Refusal guard: 9 of 10 sensitive requests refused, 0 of 5 normal refused (R1, pass, our own phrasings).
- Keyword sensitive filter: 16 of 20 sensitive and 2 of 20 harmless dropped (S1, fail; the list was used for tuning, so it is not held out).

## Team

- Jan Štok (Honzík): product, build
- Kryštof: Apify actors and live tests
- Matyáš

Built with Claude Code.

## Side challenge

ElevenLabs: not entered.
