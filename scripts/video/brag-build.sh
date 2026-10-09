#!/usr/bin/env bash
# Rebuild the brag hook + outro (video, music, mux) from brag-timeline.json.
# Swap footage:  BRAG_FOOTAGE=/path/to/v2/frames scripts/video/brag-build.sh   (re-measure crop boxes in the timeline first)
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
OUT="${BRAG_OUT:-/Users/honzik/Developer/creator-scout/demo-output/brag}"
FF=/opt/homebrew/bin/ffmpeg
export NODE_PATH=/opt/homebrew/lib/node_modules
mkdir -p "$OUT/work"
node "$HERE/brag-music.cjs" "$OUT"
for s in hook outro; do
  node "$HERE/brag-render.cjs" "$s" --out "$OUT/work"
  "$FF" -y -loglevel error -i "$OUT/work/$s-video.mp4" -i "$OUT/work/$s-music.wav" -map 0:v -map 1:a \
    -c:v copy -c:a aac -b:a 192k -ar 48000 -shortest "$OUT/$s.mp4"
done
"$FF" -y -loglevel error -ss 5.2 -i "$OUT/hook.mp4" -frames:v 1 -q:v 2 "$OUT/hook-poster.jpg"
for f in hook.mp4 outro.mp4 music_bed.wav; do
  printf '%s %s s\n' "$f" "$(/opt/homebrew/bin/ffprobe -v error -show_entries format=duration -of csv=p=0 "$OUT/$f")"
done
