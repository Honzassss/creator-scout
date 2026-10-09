#!/usr/bin/env bash
# Deploy the frontend demo replay (?demo=1, MOCK data, no backend) to Vercel as a noindex preview:
# https://creator-scout-demo.vercel.app  ("/" redirects to /?demo=1&lang=en)
# Static only: no API, no keys, no scraped data. noindex via X-Robots-Tag, <meta robots> and robots.txt.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUT="${TMPDIR:-/tmp}/creator-scout-demo"

(cd "$ROOT/frontend" && npm run build)

# Refuse to publish if the bundle contains anything that looks like a key.
if grep -rqE "apify_api_[A-Za-z0-9]{10}|sk-or-v1-|sk-ant-" "$ROOT/frontend/dist"; then
  echo "refusing to deploy: key-like string in frontend/dist" >&2
  exit 1
fi

rm -rf "$OUT" && mkdir -p "$OUT"
cp -R "$ROOT/frontend/dist/." "$OUT/"
printf "User-agent: *\nDisallow: /\n" > "$OUT/robots.txt"
sed -i '' 's|<head>|<head>\n    <meta name="robots" content="noindex, nofollow, noarchive" />|' "$OUT/index.html"
cat > "$OUT/vercel.json" <<'JSON'
{
  "redirects": [
    {"source": "/", "missing": [{"type": "query", "key": "demo"}], "destination": "/?demo=1&lang=en", "permanent": false}
  ],
  "rewrites": [{"source": "/((?!assets/|robots.txt).*)", "destination": "/index.html"}],
  "headers": [{"source": "/(.*)", "headers": [{"key": "X-Robots-Tag", "value": "noindex, nofollow, noarchive"}]}]
}
JSON

cd "$OUT" && vercel deploy --prod --yes
