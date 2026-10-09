# Motion audit and contract (redesign, 9 Oct 2026)

The teammate's note: animations sometimes make texts overlap, and they must run one after another,
never everything at once. This audit lists every animation, transition and timer-driven change
found in `frontend/src` at `HEAD` (69eeaae), the problem, the fix, and the file that owns the fix.

Contract: `src/motion.css` (tokens and classes) and `src/lib/motion.ts` (hooks and the presentation
queue). The API is documented at the top of `lib/motion.ts`.

## Rules

1. One region animates at a time. Board changes, guide messages and toasts take turns.
2. Order per round: `round.started` → eliminations, staggered → leaving cards removed → counters
   count → the guide's message about that round.
3. Only `transform` and `opacity` move. Width, height, top and left are never animated on text.
   `.m-flash` (a background pulse) is the one exception.
4. No two texts share a box at any moment. A changed string remounts with a key and enters
   (`.m-swap` or `.m-enter`). Two strings never crossfade in the same place unless the space is
   reserved.
5. Pacing never adds more than 1.2 s to anything (`LAG_MAX_MS`). With reduced motion, in a hidden
   tab, with `?instant=1`, or while a stream replays its history, nothing is paced and nothing
   moves.

Tokens: `--dur-1` 120 ms, `--dur-2` 200 ms, `--dur-3` 320 ms, `--ease cubic-bezier(.2,.7,.2,1)`,
`--stagger` 60 ms (capped at 8 items). The old names `--dur-fast`, `--dur-base` and `--dur-count`
are aliases of these values.

## Audit

| # | Place | Problem at HEAD | Fix | Owner file |
|---|---|---|---|---|
| 1 | `Odometer` (primitives.tsx) + `.odo-in/.odo-out` (index.css) | The old number rolled out while the new one rolled in, both drawn in the same box for 500 ms. With a different digit count (6 → 11) they overlapped visibly. | Count-up in one text node, tabular digits (`useCountUp`, or the equivalent inline in `Odometer`). `motion.css` hides `.odo-out` as a safety net. | primitives.tsx (done by its owner), motion.css (M) |
| 2 | Funnel round end | `round.finished` changed 4 counters while survivors remounted into the next column (every card ran `card-in` at once), eliminated cards were still in `card-drop`, and the guide's "Round N done" message entered at the same time. Four motions in two regions. | The presentation queue waits until the last card has left, removes the leaving cards, applies `round.finished` and holds 320 ms while the counters count. Only then does the guide message enter. Measured on `?demo=1&scenario=discovery`: the message enters 317–340 ms after the counters change, in each round. | store.tsx, lib/motion.ts (M) |
| 3 | `.ccard.dropping` 0.9 s + `anim.clear` at 1.4 s (polled every 500 ms) | Invisible cards kept their slot for up to 1.9 s. Columns jumped while the next eliminations were already falling. | Exit is `.m-exit` in `--dur-3`. The queue clears leaving cards right before `round.finished`, so the column closes once. A safety net clears flags older than 1.2 s, polled every 250 ms. | motion.css, store.tsx (M) |
| 4 | Live SSE (`store.tsx`) | Every event was dispatched as it arrived. A mock burst (26 eliminations, `round.finished`, the next `round.started`) landed in one frame. | All run events go through `present.push()`. `round.started` holds 200 ms, the first 8 eliminations of a round 60 ms each, then the rest at once. Bounded by `LAG_MAX_MS`. | store.tsx (M) |
| 5 | Snapshots (`refreshSnapshot`) | The snapshot was dispatched outside the event order. It could overtake queued events, so cards appeared already eliminated (no exit) and counters jumped. | Snapshots go through the queue, in arrival order. User actions (`reset`, `run.id`, `subject.start`, `criteria.local`, `restore.local`, `goal.submitted`, `recomputing`) flush the queue first, so a queued event never lands on top of them. | store.tsx (M) |
| 6 | Reload or reconnect (`?run=`) | The stream replays the whole history on connect. With pacing alone, it would replay ~1 s per round. | `present.catchUp(150)` applies the replay burst at once and paces only what arrives after 150 ms of quiet. Measured: a finished run is fully shown 322 ms after navigation. | store.tsx, lib/motion.ts (M) |
| 7 | Guide notices (vet done, goal change, report diff, subject ready, purge) | Dispatched in the same tick as the board change they describe, so the bubble entered while the board was animating. Two notices could enter together. | `chat.notice` goes through the queue and holds 320 ms each, so it follows the board and comes one at a time. | store.tsx (M) |
| 8 | Toasts (`Toasts` in DemoBar.tsx) | An action error and a snapshot error could stack in one frame. | `error` actions go through the queue, one per 320 ms. Each toast keeps its own `.m-enter`, which its owner has already done. | store.tsx (M); DemoBar.tsx (done) |
| 9 | Goal change, discovery (`goalSig` effect in store.tsx) | A smooth scroll to the top, a 1.4 s `flash-ring` and the `DiffView` panel entering all started within 60 ms. | Scroll after `--dur-2`, then `flash()`, a single background pulse. The `diff` and `report.diff` events hold 320 ms each. | store.tsx (M) |
| 10 | `reveal()` (store.tsx) | `flash-ring` (a 2 px ring for 1.4 s) on top of a smooth scroll and a focus move. | `flash()` instead of the ring. Scroll behaviour follows `motionInstant()`. | store.tsx (M) |
| 11 | Subject goal switch (demo `subjectGoalScript`, live `applyMutationResult`) | `report.diff`, the re-rendered report and `recomputing:false` were applied in one step. The "What changed" panel, the report list and the status line changed at once. | Queue: `report.diff` (holds 320 ms) → re-rendered report → `recomputing` off → guide notice. Measured: panel 4533 ms, pulse 4875 ms, guide 5181 ms. | store.tsx (M) |
| 12 | "What changed" (SubjectBoard.tsx) | All 8 rows ran `.m-enter` in the same frame. | Put `.m-stagger` on the rows container and `style={staggerStyle(i)}` on each row. | SubjectBoard.tsx (owner) |
| 13 | `.m-flash` on an element that also has `.m-enter` | The flash replaced the enter animation, so removing `.m-flash` re-ran `.m-enter`. The panel blinked out and back in about 1.3 s later. Found during verification. | `.m-enter.m-flash` and `.m-swap.m-flash` now run both animations. `flash()` uses the Web Animations API and never touches the element's CSS animation. | motion.css, lib/motion.ts (M) |
| 14 | Status line between rounds (Funnel.tsx, SubjectBoard.tsx) | When `round.finished` clears `currentRound`, the line falls back to "Starting the rounds…" (discovery) or "Looking up the public profile…" (subject) until the next `round.started`. The wrong text flashes every round, now for at least 320 ms. | While `runStatus === 'running'` and `currentRound == null`, show the last finished round ("Round N done, next: …"). | Funnel.tsx, SubjectBoard.tsx (owners) |
| 15 | Infinite indicators | The header `ping` dot, stepper `breathe`, `running-bar` sweep twice (status line and current column), chat caret `blink` and `work-dot` all ran at once. | Keep one running indicator per region: one bar in the funnel, not two. They are loops, not entrances, so they do not go through the queue. | Funnel.tsx, Header.tsx (owners) |
| 16 | `App.tsx` guide collapse | `grid-template-columns` was transitioned, so both columns reflowed text every frame. | No width transition. Already removed by its owner. | App.tsx (done) |
| 17 | Funnel cards on round change | Survivors remount into the next column and all run `card-in` together, up to 48 cards. | Use `.m-stagger` and `staggerStyle(i)` with the index in the new batch, capped at 8, so long lists do not wait. Done for the stage grid and the finalists grid. The candidate list inside an open stage still enters all at once. | Funnel.tsx (owner, partly done) |
| 18 | Demo replay (`?demo=1`) | The script dispatched straight into the reducer and ran its own timing only. | `createDemoReplay(push, …)`: the same queue as live. `&instant=1` makes the queue synchronous. | store.tsx (M) |
| 19 | Reduced motion | index.css set `*` animations to 0.01 ms, but JS timers (Odometer, flashes, smooth scroll) still ran. | `motionInstant()` covers reduced motion and hidden tabs. The queue, `useCountUp`, `useSequence` and `flash()` are instant, and every `--dur-*` is 0. Measured on demo discovery: 0 running animations, no pacing. | motion.css, lib/motion.ts (M) |
| 20 | Hidden tab | Timers are throttled, so paced events would pile up behind the hold. | On `visibilitychange` to hidden the queue flushes, and it applies instantly while hidden. | lib/motion.ts (M) |

Checked and fine: LiveLog auto-scroll (rAF, no animation on text), chat auto-scroll during
streaming, the DemoBar progress bar (`scaleX`), the drawer slide-in and scrim fade (one dialog
region), `useDialog` placement timers (position only, before it is shown), button and toggle
colour transitions (`--dur-1`).

## Debugging

In dev, `window.__motionTrace = []` in the console records `[ms, action type, event type]` for every
action the queue applies.
