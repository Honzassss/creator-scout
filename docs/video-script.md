# Creator Scout: 90-second demo script

Two versions, both 88 seconds, 2 s under the 90-second limit. **Version A** is screen recording only. **Version B** opens with a 15 to 20 second launch clip made with the `/brag` skill (latent-spaces/brag), then switches to screen recording. `/brag` is not installed here. Use version B only if it is installed, reviewed and the clip is ready by 05:00. Default: version A, which spends all 88 s on the working product. Pitch and facts: [pitch.md](pitch.md).

Placeholders: **[SUBJECT]** is the one real public subject researched in subject mode. **[COMPETITOR]** is the competitor the owner names. **[DATE]**, **[N]** and anything marked **[TO CONFIRM]** come from tonight's runs. Do not fill a number that was not measured.

## Rules for the recording

- **English UI** throughout.
- **Label every cached shot on screen** for the whole shot: the app's header badge ("From cache") plus a burned-in caption "CACHED RUN · fetched [DATE]". The Run column below says which shots are cached.
- **At least one shot is live.** Planned: the subject-mode shots (5, 6, 8 in version A). If live fails at recording time, record them from cache, change the caption to CACHED, and show the live run during judging instead **[TO CONFIRM]**.
- **MOCK only if a source is unreachable**, and then with the MOCK badge visible and "MOCK example" in the voice-over. Meta Branded Content is cut, not mocked.
- **"Blur eliminated" on** (header toggle). It blurs only eliminated candidates. In shots 4 and 7, blur every other real handle and avatar except [SUBJECT] in the edit: remaining candidates, finalists and the goal-switch diff.
- **[SUBJECT] needs consent** or must be a team member's own public account or an organization's public account. A real person's report in a public video needs their consent (Czech Civil Code §§ 84 to 87). No new accounts, no fake posts.
- **No faked timing.** If the cached funnel finishes too fast to read, freeze-frame on the eliminated lane in the edit. Any speed change gets a caption ("sped up"). A live subject run does not fit in 12 s (T5 alone took 13.5 s for 9 profiles). In shot 5, show the start and the live log, then jump-cut to the report with the caption "live run, [MM:SS] cut", using the real duration from the log. In shot 2, caption the typed answers "answers cut for time".
- No tokens, terminals, bookmarks or notifications on screen.

## Before recording

1. Backend with the recorded Brno run: `SOURCE_MODE=cache`, `APIFY_TOKEN` set so the subject-mode shot can go live **[TO CONFIRM]**. LLM provider: **[TO CONFIRM: Claude or OpenRouter]**. If the header says "fallback", say so in the close.
   - Pick a [SUBJECT] whose data is not already in the recorded Brno cache. In cache mode only cache misses go live. Keep the take only if the live log says "live".
   - If the real Brno run is not cached by recording time, drop shot 4 rather than record the funnel on MOCK under "Real public accounts". Give its 12 s to shots 5 and 7.
   - If subject mode does not ship, shots 5, 6 and 8 use one finalist from the real cached run, deep-checked live with `POST /api/runs/{id}/vet` (consent needed).
2. Test the refusal phrase in English before recording (shot 3). It must produce a refusal and a gray "Not checked" chip **[TO CONFIRM]**.
3. Find the namesake case for shot 8 in the real data **[TO CONFIRM]**. If there is none, do not use a MOCK namesake: MOCK is only for unreachable sources. Either run the same handle with a wrong city ([validation-plan.md](validation-plan.md), A5) and show the "uncertain" or "different person or account" verdict, or cut the shot to 4 s and say "no namesake found for this subject".
4. Check that [SUBJECT] has a claim worth showing in shot 6. If the honest status is "Cannot verify" or "Supported", show that. Do not stage a conflict.
5. Browser 1920 x 1080, zoom so card text is readable, cursor highlight on. Record each shot separately. Record the voice-over separately and lay it over the edit.

## Version A: screen recording only (90 s)

Voice-over is 159 words over 88 seconds, with 2 s of margin before the 90-second limit.

| # | Time | Run | On screen | Voice-over | Caption |
|---|---|---|---|---|---|
| 1 | 0:00-0:07 | chat only | Empty app, English UI. Owner types: "I run a bakery in Brno. I want a local creator to bring more people into the shop." | "A Brno bakery wants a local creator. In Czechia, an unlabeled ad is her problem too." | Czech law: the advertiser shares liability for unlabeled ads (Act 40/1995 Coll., § 6b) |
| 2 | 0:07-0:15 | chat only | Guide asks the remaining questions; answers typed fast (who she sells to, the goal, rough budget, "competitor: [COMPETITOR]"). Criteria chips appear, grouped by round, each with its "why". | "A few plain questions become criteria she can see, edit or switch off." | Criteria with reasons. No score. |
| 3 | 0:15-0:21 | chat only | Owner types: "Only religious creators, please." Guide refuses in one sentence. A gray "Not checked" chip appears with the reason. | "Religion, health, politics or origin: refused, with the reason." | Refused: special-category data (GDPR Art. 9) |
| 4 | 0:21-0:33 | **CACHE** | Owner: "Yes, run it." Funnel columns fill, round 0 to round 3, counters "entered [N] → remaining [N]". Eliminated cards collapse into lanes with one-line reasons and source chips; names blurred. Hover one reason (e.g. "Round 1: last post [DATE]"). | "Real public accounts, narrowed in rounds. Every cut shows the round, the reason and the source. She can undo any of them." | CACHED RUN · fetched [DATE] via Apify · eliminated accounts blurred |
| 5 | 0:33-0:45 | **LIVE** [TO CONFIRM] | Subject mode: "@[SUBJECT]", anchor "Brno", goal "bakery: more people in the shop". Live log scrolls with actor names and "live". Report opens: green facts, orange inferences, gray gaps. | "Or start from one account: a handle, a city, a goal. Fetched live through Apify actors. Every line links to its source." | LIVE · subject mode: @[SUBJECT] + Brno + goal (if cached: CACHED · fetched [DATE]) |
| 6 | 0:45-0:55 | same as 5 | "Claims vs. record" card. Left "What the creator says": quote, place, date. Right "What the record shows": posts, label, discount code. Status chip and confidence. Click a source chip; the post opens. | "Left, what the creator says. Right, what the posts show. Status, confidence, source." | Claim vs. record: [STATUS], confidence [LEVEL] |
| 7 | 0:55-1:06 | **CACHE** | If subject mode ships (primary, the brief's exact test): on the [SUBJECT] report, "Change goal" → "Fitness studio in Brno"; the report re-renders from cache with a "what changed" list. Fallback: "Change goal" → "Fitness studio in Brno" → "What will change" → "Recompute for the new goal"; diff of who dropped out only for the bakery or only for the fitness studio, and why. | "Same data, new goal: a fitness studio. Nothing is fetched again. A different report, and a list of what changed." | Goal switch · recomputed from cache, no new fetch |
| 8 | 1:06-1:14 | same as 5 | Identity panel. The creator's other account: "same creator", with signals (bio links, same website). A news item about a namesake: "different person or account", signals against (different city, no link to the handle). | "Same name in the news. Different city, no link to the account. Rejected, not attributed." | Namesake rejected · signals shown, no percentage |
| 9 | 1:14-1:19 | n/a | Outreach draft with the "NOT SENT" badge. Cursor rests on "Copy". The line "clearly labelled as advertising" is visible. | "The outreach is a draft. Nothing is sent." | NOT SENT · the app has no send function |
| 10 | 1:19-1:28 | n/a | Header counts: live [N], cache [N], MOCK [N]. "What we did not check and why" (audience age, gender and origin) and the gray gap "No data from Meta's branded content library". End card: "Creator Scout · public data · no score · the owner decides". | "What was live, cached or mock is on screen. What we could not check is listed. No score. The owner decides." | Live [N] · Cache [N] · Mock [N] · Not checked: audience age, gender and origin · Gap: Meta Branded Content |

## Version B: /brag hook + screen recording (90 s)

`/brag` turns a project into a short launch video with music, motion and share copy. It is a third-party skill and is not installed here (see the note at the top): review it before installing, and review everything it outputs against the rules below.

### The hook clip (0:00-0:18)

Ask for an 18-second clip. Give it only this copy, word for word:

1. "Pick a local creator. See why."
2. "In Czechia, an unlabeled ad is the advertiser's problem too."
3. "Every claim has a source."
4. "Same creator, new goal, new report."
5. "No score. You decide."
6. "Creator Scout · built on Apify actors"

Rules for the clip:

- No numbers at all (no "10x", no "thousands of creators", no follower counts).
- No "best creator", no score, no "AI picks", no risk level.
- No platform logos (Instagram, TikTok, Meta). Text only.
- Screens only from the cached run with "Blur eliminated" on, plus the CACHED label. No unblurred real handles or faces. Do not use `/?demo=1`: it is a frontend-only scripted replay with canned data (README).
- Music: confirm the track may be used in a public video **[TO CONFIRM]**. Duck it under the voice-over from 0:18.
- Reject any share copy it writes that breaks these rules.

### Shot list

| # | Time | Run | On screen | Voice-over | Caption |
|---|---|---|---|---|---|
| B0 | 0:00-0:18 | clip | /brag clip with the six lines above. | none (music only) | burned into the clip |
| B1 | 0:18-0:25 | chat only | Owner types the bakery goal; criteria chips with reasons appear (shots 1 and 2 cut together). | "A bakery in Brno wants a local creator. Her goal becomes criteria she can edit." | Criteria with reasons. No score. |
| B2 | 0:25-0:30 | chat only | "Only religious creators, please." Refusal and gray "Not checked" chip. | "Religion or health: refused, with the reason." | Refused: GDPR Art. 9 |
| B3 | 0:30-0:40 | **CACHE** | Funnel fills; eliminated lanes with reasons and source chips; names blurred. | "Real public accounts, narrowed in rounds. Every cut has a reason and a source." | CACHED RUN · fetched [DATE] · eliminated accounts blurred |
| B4 | 0:40-0:50 | **LIVE** [TO CONFIRM] | Subject mode: @[SUBJECT] + Brno + goal; live log; report opens. | "Or start from one handle, a city and a goal. Fetched live, sourced line by line." | LIVE · subject mode: @[SUBJECT] |
| B5 | 0:50-0:58 | same as B4 | "Claims vs. record" card; click a source chip. | "What the creator says, next to what the posts show." | Claim vs. record: [STATUS], confidence [LEVEL] |
| B6 | 0:58-1:08 | **CACHE** | Change goal to fitness studio; diff and the re-rendered report. | "New goal, same data. Nothing is fetched again. The report changes." | Goal switch · from cache, no new fetch |
| B7 | 1:08-1:14 | same as B4 | Identity panel: namesake marked "different person or account" with signals. | "Same name, different person. Rejected, not attributed." | Namesake rejected · signals shown |
| B8 | 1:14-1:18 | n/a | Outreach draft, "NOT SENT", Copy. | "Drafted, never sent." | NOT SENT |
| B9 | 1:18-1:28 | n/a | Header counts live / cache / MOCK; "What we did not check and why" and the gray Meta Branded Content gap; end card. | "Live, cached and mock are labeled. Gaps are listed. No score. The owner decides." | Live [N] · Cache [N] · Mock [N] · Not checked: audience age, gender and origin · Gap: Meta Branded Content |

## What each requirement maps to

| Must show | Version A | Version B |
|---|---|---|
| Owner's goal in chat, in English | 1, 2 | B1 |
| Refusal of a sensitive criterion | 3 | B2 |
| Funnel with reasons | 4 (cached) | B3 (cached) |
| Subject mode on one real public subject | 5 | B4 |
| Claim vs. evidence | 6 | B5 |
| Goal switch changes the report | 7 (cached) | B6 (cached) |
| Identity panel rejects a namesake | 8 | B7 |
| Outreach NOT SENT | 9 | B8 |
| Honest close: what is cached or mocked | 10 | B9 |
| At least one live subject | 5, 6, 8 [TO CONFIRM] | B4, B5, B7 [TO CONFIRM] |
