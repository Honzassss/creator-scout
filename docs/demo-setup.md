# Demo setup: real-data replay (@kamvbrne)

The video uses real public data recorded on 9 Oct 2026 and replayed from the cache: no Apify or LLM
cost, same result every time. The recording lives in `data/live-subject/` (gitignored, this machine only).

## Start the replay (zero cost)

From the repo root:

```bash
D=$(mktemp -d) && cp -R data/live-subject/cache data/live-subject/snapshots "$D"/
# backend, cache mode, keys forced empty (config.py would otherwise read them from .env)
PORT=8093 SOURCE_MODE=cache DATA_DIR="$D" APIFY_TOKEN= OPENROUTER_API_KEY= ANTHROPIC_API_KEY= scripts/dev-backend.sh
# frontend, second terminal
PORT=5223 API_TARGET=http://127.0.0.1:8093 scripts/dev-frontend.sh
```

Open http://127.0.0.1:5223/ (UI language: English; switch in the `…` menu). The header must read
`CACHED` and `LLM: rule-based`. Start from a fresh `$D` for each take, so the run list is empty.

## Inputs (Guide panel, "Already have a creator in mind?")

| Field | Value |
|---|---|
| Creator | `@kamvbrne` |
| Anchor | `Brno` |
| Goal | Bakery in Brno |
| Competitors (optional) | `William Thomas Bakery @william_thomas_bakery, SORRY pečeme jinak @sorrypecemejinak` |

Then press **Research**. The report is ready in under a second.

## Moments to show

1. **Identity verdict.** "Is this the account you mean?" says LIKELY: the bio names Brno and
   40 posts are located in or mention Brno, each with an IG source chip. It also says that 10 news
   results not about @kamvbrne were set aside.
2. **Competitor finding with sources.** In "Checks for this goal", the check "No competitor collaboration"
   is not met: @sorrypecemejinak (29 Sep 2026) and @william_thomas_bakery (13 and 17 Sep 2026), with
   3 sources linking to the real posts. Under Collaborations, the FACT row says
   "29 Sep 2026: sorrypecemejinak … competitor (co-authored post), platform label unknown" (high
   confidence, platform co-author field). The INFERENCE "worked with a competitor … most recently
   29 Sep 2026" is medium confidence and based on Finding 14. GAP rows state what could not be checked.
   Questions for the first meeting include "You worked with @sorrypecemejinak (29 Sep 2026). Is that
   still running, and does it include exclusivity?" The report states facts and makes no
   hidden-ad accusation.
3. **Goal switch.** Click **Fitness studio in Brno**, then **Bakery in Brno**. Nothing is fetched
   again and no LLM is called. The "What changed" panel shows:
   - going to fitness: "1 finding is no longer key, 1 moved to less relevant, … 1 check changed"
     (No competitor collaboration: not met becomes cannot verify);
   - going back to bakery: "4 findings became key (@sorrypecemejinak and @william_thomas_bakery are
     now competitors) …".
4. **Run log** (bottom bar, EXPAND): every line is English. The only Czech is quoted source text,
   such as the news query "Kam v Brně | …".

## Before recording: open issues

- **Moment 3 (fixed):** the one-click switch now sends the form's competitors with the form's preset
  and `competitors: []` with the other preset (`switchGoal` in `frontend/src/store.tsx`). Checked in
  the UI on the cache replay: to fitness "1 finding is no longer key, 1 moved to less relevant, ...
  1 check changed" (No competitor collaboration: not met -> cannot verify); back to bakery "4 findings
  became key (@sorrypecemejinak and @william_thomas_bakery are now competitors)". After a reload of
  `?run=` the page no longer knows the form's list, so start each take from the form.
- Collaboration timeline, 13 Sep 2026: the row is titled @toulkyspavlem with a COMPETITOR badge,
  because the post also tags @william_thomas_bakery. This is `groupByPost` in
  `frontend/src/components/CandidateDrawer.tsx`. Don't zoom in on that row until it is fixed.
