# Merge notes: redesign into main (branch integrate-redesign)

Merge commit `4988adb` on `integrate-redesign` = main `88d8f10` + redesign `934b40e`
(merge base `69eeaae`). The rule used everywhere: keep main's behaviour and markup
semantics (QA fixes, ids, aria, focus moves, new states and fields), wear them in the
redesign's visual system (tokens, utility classes, `LINK`/`box`/`FIELD` helpers) and
route them through the redesign's presentation queue (`push`).

## Conflict files (14) and how each was resolved

| File | Hunks | Resolution |
|---|---|---|
| `frontend/src/App.tsx` | 1 | `#board`: main's `overflow-x-clip` (keeps sticky children working) + redesign's `bg-[var(--bg)]`. |
| `components/GoalModal.tsx` | 1 | Redesign footer (it already has `flex-wrap`, main's only change). |
| `components/Report.tsx` | 1 | Redesign summary-line styling with main's `text` variable (`<RichText text={text} />`). |
| `components/primitives.tsx` | 1 | Imports: redesign's `useCountUp` + main's `Lang` type. |
| `components/Header.tsx` | 2 | Redesign menu (no theme toggle: light only). Re-applied main's `ref={menuWrap}` on the menu wrapper (tap-outside close) and `closeMenu()` after the language switch. Main's DataStatus tap fix auto-merged. |
| `components/CriteriaPanel.tsx` | 3 | Redesign layout (brief line + collapsed `<dl>` summary). Main's collapsed `relative` span fix is moot (redesign has no truncating span). Re-applied main's `focusSoon(toggleRef / #funnel-h)` on "Start run". Imports: `focusSoon` + redesign's `ResultsSummary`. |
| `components/Compare.tsx` | 3 | Imports: redesign set (`Handle`, `StatusTag`, no `CritIcon`) + `focusSoon`. "Show all" link: redesign classes + main's focus-to-switch handler. Mobile row: redesign grid + `<Handle>` + main's `title`. |
| `components/CandidateDrawer.tsx` | 3 | Main's "also named" brands line, news attribution and title through `RichText` (blur), all in redesign classes (`text-[13px] … var(--text-2)`, `text-[16px] font-semibold`). |
| `components/Funnel.tsx` | 3 | Imports merged (redesign `subjectCandidate`, `Lang`, `ResultStatus`, motion; main `vetStepLabel`, `focusSoon`; `Odometer` dropped as in redesign). EmptyFunnel: redesign markup + main's `composeChat(t('funnel.empty.subjectDraft'))` fallback. VetAction (main's restored-first defaults + focus) auto-merged. |
| `components/LiveLog.tsx` | 5 | Redesign header/row styling + main's semantics: one `aria-label` on the toggle, `aria-hidden` visual parts, `rowCount`, `RichText` for lines and the technical "detail" twin shown as a second line (no `title`). |
| `components/SubjectBoard.tsx` | 5 | Imports merged (`StatusTag`, `flash`, `itemDomId`, `SubjectEntry`). Stepper: redesign dot (no glyph for done) + main's `stopped` state (✕, `aria-current`). WhatChanged effect: `if (!rd \|\| rd.hidden) return` + redesign's flash. CheckRow: main's anchor `id`/`tabIndex`/`scroll-mt-16` + redesign grid. NotFound (retry form) and Interrupted (retry button) from main, restyled to tokens. |
| `components/SubjectEntry.tsx` | 5 | Main's props (`initialSubject`, `initialAnchor`, `title`), competitors field and no-`aria-live` anchor hint, rendered with redesign `LABEL`/`FIELD`/`HINT` and the redesign full-width submit button. |
| `components/Chat.tsx` | 10 | Redesign guide styling (`BODY`, `LINK`, `box`, `Paragraphs`, stacked composer) + main's: `MAX_CHAT` + too-long/length note, starters focus the composer, `empty` ignores the purge notice, `pick()` on subject notice anchor/goal, reportDiff link logic (`reportDiff.show`), vet-fail handles via `RichText`, message `lang` (now passed `Paragraphs -> RichText lang`). |
| `frontend/src/store.tsx` | 10 | Redesign presenter (`rawDispatch`, `dispatch` with `FLUSH_BEFORE`, `push`) kept; main's code kept everywhere else (`newChatId`, `AFFIRMATIVE`, `sendChat()` helper, report-diff batching, 404 run-gone, `checkInterrupted`, `streamEpoch`). Every event keeps main's `runId: id`; events/snapshots/notices/errors use `push`, resets use `dispatch` (flushes the queue first). `vet` does both `localChange.current = true` and `dispatch({type:'vet.requested'})`. Effect deps = union. |

## Follow-up edits outside conflict hunks (in the same merge commit)

- `Chat.tsx`: main's new blocks that auto-merged with legacy classes were restyled:
  failed `ToolLine` (`line` + ✕), `reportDiffs`, `subjectNotFound`, `interrupted`
  notices (`box`, `LINK`), the length note (`--bad` / `--text-2`).
- `store.tsx`: main's new `subjectNotFound` / `interrupted` notices and the chat-stream
  run events switched from `dispatch` to `push` (so they queue behind paced events).
- `SubjectEntry.tsx`: restored the `subject-entry` class on the form as a hook. The
  redesign had dropped it, which broke Funnel's "Check one creator" focus (it queries
  `.subject-entry input[name="subject"]`). Utilities still win over the old component CSS.

Auto-merged without edits: `i18n.ts`, `index.css` (main's `.is-stopped` stepper and
`.toc` mask landed in the redesign rules), `state.ts` (redesign `vetBatch`/`vet.requested`
next to main's `runId` guard and `reset.keepChat`), `DemoBar.tsx`, `DiffView.tsx`.

## Verified

- `npm run build` (tsc -b + vite) passes; backend `pytest -q`: 809 passed.
- agent-browser session `premerge`, mock backend: subject @kuba.jidlo.brno + Brno +
  competitors (stored in the brief, shown in round-4 criterion) -> report -> goal switch
  bakery/fitness -> What changed panel, Hide, chat "Show what changed" reopens and
  focuses `#changed-h`; not-found subject -> stopped stepper + retry form; discovery
  chat interview -> "Yes, start." -> rounds 0-3 -> Vet 5 (focus to `#funnel-h`) ->
  vet notice -> drawer -> compare (only-differences, Show all focus, sort); run log
  (English, detail twins); 375 px: no horizontal overflow, header menu, subject form
  with competitors, subject board, goal switch.

## Re-merging later commits fast

1. Late redesign commits (review/fix phase):
   `git -C <worktree> merge redesign` on `integrate-redesign`. Only hunks the late
   commits touch inside the 14 files above can conflict; resolve with the table above
   (behaviour/markup from main, classes/motion from redesign).
2. Newer main commits: `git merge main` on `integrate-redesign`. As of `67baa6c`
   main's commits after `88d8f10` touch backend, docs and scripts only and merge
   cleanly (checked with `git merge-tree`). If main adds `data-testid` attributes,
   expect small conflicts in the same 14 files: keep the attribute, take the
   redesign's className.
3. Re-doing the whole merge from scratch (for example redesign straight into a newer
   main): the resolutions are recorded in rerere (`rr-cache`, trained from `4988adb`).
   Run `git -c rerere.enabled=true merge redesign`; the 14 files resolve from the
   cache wherever the hunks are unchanged. Check `git diff` and finish the rest by hand.
4. After any re-merge: `npm run build`, backend `pytest -q`, and grep the merged
   components for legacy classes main may have added
   (`text-ink-2|font-display|bubble-|border-rule|bg-paper|btn-link text-sm`).

## Second redesign merge: `a5bc3da` (paced motion queue, review fixes)

Merge commit `4e01301` on `integrate-redesign` = `c890201` + redesign `a5bc3da`. Three files
conflicted; the other 17 redesign changes auto-merged. Resolutions are in rerere.

| File | Hunks | Resolution |
|---|---|---|
| `frontend/src/store.tsx` | 7 | Redesign's `pushEvent` (copy key per diff / report diff, second copy dropped, `seenCopies` cleared on each user change) gained an optional `runId` and replaces every `push({type:'event'})`: SSE handler and `onmessage` pass main's `runId: id`, `applyMutationResult` passes `id`, the chat-stream events stay without one (as on main). Report-diff notices: main's `rdLatest`/`rdAnnounced` batch effect kept (subject: one `reportDiff` line; discovery: one `reportDiffs` line naming each creator, which the redesign had dropped), wrapped in the redesign's pacing: window `max(500, DUR[3]+DUR[2])` ms, subject card polls `#what-changed` animations (max 2.5 s), both notices go out through `whenPresented`. `sendChat`: main's action + helper kept; `seenCopies.current.clear()` added in the helper and the helper's run events use `pushEvent`. `restore`: main's `awaitDiff` + redesign's clear. `applyMutationResult`: redesign order (funnel diff first, then report diffs); main's reducer keeps `pendingGoal` through discovery report diffs, so either order titles the goal diff. Stream effect deps = union with `pushEvent`. |
| `components/Funnel.tsx` | 2 | Imports: redesign's `motionInstant` + main's `focusSoon` and `vetStepLabel`. Vetting status line: the redesign's `vetProgressNow` / `vetProgress` / `vetStarting` (done = finished, no step, steadied by `useSteadyText`). Main's localized step (`vetStepLabel`) moved to where the step now lives: `CandidateCard` and `FinalistCard` (`funnel.vetting: {vetStepLabel(step, lang)}`; previously the raw step id). `funnel.status.vetting*` i18n keys are now unused. |
| `components/SubjectBoard.tsx` | 1 | Imports: redesign's `motionInstant`, `KindLabel` + main's `itemDomId`, `SubjectEntry`. |

Verified: `npm run build` passes; backend `pytest -q`: 812 passed. Not browser-tested.

Main's `e1a543c` (QA: offline not-found copy, restored notice after load, Czech goal text)
and `7dfb434` are not in this branch yet: `git merge main` next. `e1a543c` touches
`store.tsx` (restored notice, `subjectNotFound` notice fields), `Chat.tsx`, `CriteriaPanel.tsx`,
`SubjectBoard.tsx`; expect small conflicts there and route new notices through `push`.

## Third merge: main `7a1e547` (data-testids, QA fixes, ?run= restore, no invented competitors)

34 hunks in 12 frontend files; all resolved as redesign markup/classes + main's attributes and logic.

- `data-testid`s from `12d15f4`: every one of main's ids is on the redesign element that plays the same
  role (checked by diffing the per-file id sets against main). `Toggle` keeps `testId`; `EvidenceItem`
  gained `dataAttrs` so `FindingRow` carries `finding` / `data-kind` / `data-confidence` / `data-tier`.
  Funnel: `round-column` on each stage `<li>` and on `#round-4`; `round-counter` (`data-value` = remaining)
  on the stage count and the finalists count.
- `CriteriaPanel`: main's `focusToggle` flow (focus the toggle once the run exists) + `run-rounds`.
- `SubjectBoard` NotFound: main's offline-aware `body`; lang note restyled `text-text-2`.
- `CandidateDrawer`: main's `report-lang-note` (7503b00) in redesign type.
- `store.tsx`: goal switch keeps the redesign's `seenCopies.clear()` + main's `formGoal` competitors rule
  (0a7a922). Main's ?run= restore effect (`chat.restore` / restored notice) goes through `push`.
  Diff dedupe unchanged from the second merge: `pushEvent` copy key in front of the queue, main's reducer
  `reportDiffKey` check behind it.

Verified: `npm run build` passes; backend `pytest -q`: 819 passed. Not browser-tested.
