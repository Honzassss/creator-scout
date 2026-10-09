# Porting a Figma Make design into the app

The look can change. The behaviour, the data contract and the honesty rules cannot. If you are
unsure whether a change is allowed, it probably touches behaviour: ask first.

## You may change

- Markup inside `frontend/src/components/*.tsx`: element structure, wrappers, order of visual blocks, Tailwind classes.
- `frontend/src/index.css`: layout, spacing, type, radii, shadows, motion, and the token values
  (`--paper`, `--ink`, `--accent` and the rest), in light and dark mode.
- Fonts (Google Fonts only), icons, illustrations, empty states, copy tone in `i18n.ts`, provided the
  meaning stays the same in Czech and English.

## You must not change

- `frontend/src/store.tsx`, `frontend/src/state.ts`, `frontend/src/types.ts`, `frontend/src/lib/*`
  (API calls, SSE, presets, parsing) and `frontend/src/dev/*` (the `?demo=1` replay). Components
  read state through `useApp()` and call `actions.*`. Do not add your own `fetch` or a second store.
- Every `data-testid` attribute (and `data-kind`, `data-status`, `data-mode`, `data-round`, `data-value`
  next to it). `scripts/smoke.sh` relies on them. When you move markup, move the attribute with it.
- The hard UI rules:
  - No score, rank, percentage fit or "best creator" for a person. Never sort people by a made-up number.
  - Criterion results are the neutral glyphs ✓ ✕ ? in ink. Do not use red or green verdicts on people.
  - Green, orange and gray are reserved for fact, inference and gap (`--fact`, `--inference`, `--gap`).
    Do not use them for anything else. Magenta (`--mock`) is only for MOCK.
  - MOCK and CACHED labels stay visible wherever data appears: cards, report, header data-mode badge.
  - Every fact keeps a clickable source chip that opens the source.
  - The outreach draft keeps the NOT SENT label. There is a copy button, and never a send button.
  - Gaps stay listed ("what we could not check"). The "How this report is built" panel stays.
- Accessibility basics that exist today: labels, `aria-*`, focus handling, 44 px touch targets, and no
  horizontal scroll at 375 px.

## Run locally

```bash
python3 -m venv backend/.venv && backend/.venv/bin/pip install -r backend/requirements.txt   # once
cd frontend && npm install && cd ..                                                          # once
scripts/dev-backend.sh      # http://127.0.0.1:8000, SOURCE_MODE=mock by default, no keys needed
scripts/dev-frontend.sh     # http://127.0.0.1:5173 (proxies /api to :8000; API_TARGET=... to change)
```

Open `/?lang=en` or `/?lang=cs`. `/?demo=1` is the scripted replay and needs no backend.
To try a flow, type `Check @kuba.jidlo.brno for my bakery in Brno`, answer `Brno`, and then click
"Fitness studio in Brno". For discovery, answer the guide's four questions and say `yes` twice.

## Before you push

```bash
cd frontend && npm run build && cd ..   # typecheck + build
scripts/smoke.sh                        # 18 checks on MOCK data, ~40 s; must print "0 failed"
```

`smoke.sh` starts its own backend on :8066 and Vite on :5196 with no keys, then drives the page
headless with `agent-browser`.

## Publish the demo preview

```bash
scripts/deploy-demo.sh
```

This builds the frontend and deploys the static `?demo=1` replay to https://creator-scout-demo.vercel.app.
The replay has MOCK data only, no API and no keys. It is noindex (header, meta and robots.txt).
It refuses to deploy if the bundle contains a key-like string. Check the preview after every design merge.
