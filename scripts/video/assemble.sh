#!/usr/bin/env bash
# Final demo video: hook + cut (+ narration) + outro -> demo-output/final/ (see assemble.py for the mix).
#
#   scripts/video/assemble.sh                        assemble from what is already rendered (~20 s)
#   scripts/video/assemble.sh demo-output/v2         re-render the cut from new footage (render_cut.py),
#                                                    re-time the narration (voice_cut.py), then assemble
#   BRAG=1 BRAG_FOOTAGE=... scripts/video/assemble.sh demo-output/v2
#                                                    also rebuild hook/outro/music first (brag-build.sh;
#                                                    re-measure its crop boxes in brag-timeline.json first)
# Ends with the checks: duration <= 90.0 s, no black frames, loudness / true peak of both exports.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"
FFMPEG=/opt/homebrew/bin/ffmpeg; FFPROBE=/opt/homebrew/bin/ffprobe
OUT="$ROOT/demo-output/final"
FOOTAGE="${1:-}"

if [[ "${BRAG:-0}" == 1 ]]; then
  scripts/video/brag-build.sh
fi
if [[ -n "$FOOTAGE" ]]; then
  python3 scripts/video/render_cut.py --footage "$FOOTAGE"
  python3 scripts/video/voice_cut.py
fi

python3 scripts/video/assemble.py

echo "--- checks"
fail=0
for f in creator-scout-90s.mp4 creator-scout-90s-music-only.mp4; do
  d=$("$FFPROBE" -v error -show_entries format=duration -of csv=p=0 "$OUT/$f")
  s=$("$FFPROBE" -v error -select_streams v:0 -show_entries stream=width,height,r_frame_rate,codec_name -of csv=p=0 "$OUT/$f")
  a=$("$FFPROBE" -v error -select_streams a:0 -show_entries stream=codec_name,sample_rate,channels -of csv=p=0 "$OUT/$f")
  l=$("$FFMPEG" -hide_banner -nostats -i "$OUT/$f" -vn -af ebur128=peak=true -f null - 2>&1 \
      | awk '/Summary/{s=1} s&&/ I:/{i=$2} s&&/Peak:/{p=$2} END{print "I " i " LUFS, true peak " p " dBTP"}')
  printf '%-36s %6.2f s  video %s  audio %s  %s\n' "$f" "$d" "$s" "$a" "$l"
  awk -v d="$d" 'BEGIN{exit !(d <= 90.0)}' || { echo "  FAIL: longer than 90.0 s"; fail=1; }
done
blk=$("$FFMPEG" -hide_banner -nostats -i "$OUT/creator-scout-90s.mp4" -an -vf blackdetect=d=0.05:pix_th=0.10 -f null - 2>&1 | grep -c black_start || true)
echo "black segments (>=0.05 s): $blk"; [[ "$blk" == 0 ]] || fail=1
echo "contact sheet: $OUT/contact.jpg (1 frame per second, row r = seconds 10r..10r+9)"
exit $fail
