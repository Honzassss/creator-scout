#!/usr/bin/env bash
# Fallback English voice-over for the demo video, made with macOS `say` (no account, no network).
# One clip per shot, each fitted inside its shot (sped up with `say -r` only if needed), then laid on
# a timeline with exact silences so speech starts LEAD seconds after each shot boundary.
# Text: docs/video-script.md version A, adapted to docs/demo-setup.md (@kamvbrne cached replay +
# MOCK discovery funnel), in the shot order of scripts/record/fallback.sh.
#
# OUTPUT: <repo>/demo-output/narration/ (gitignored)
#   narration.m4a / narration.wav   full track, exactly as long as the video
#   narration.txt                   final lines with timestamps (for a human re-record)
#   clips/NN-slug.aiff              one clip per shot
#   creator-scout-fallback-narrated.mp4   preview: fallback video + this track (if the video exists)
#
# Usage: scripts/record/narrate.sh [--shots DIR] [--voice NAME] [--rate WPM] [--out DIR]
#   Shot durations come from <shots>/NN-slug.mp4 (default demo-output/fallback/shots) via ffprobe;
#   missing clips fall back to the durations measured on 9 Oct 2026, 05:06.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
SHOTS="$ROOT/demo-output/fallback/shots" OUT="$ROOT/demo-output/narration"
VOICE=${VOICE:-Samantha} RATE=${RATE:-180} MAX_RATE=${MAX_RATE:-215}
LEAD=${LEAD:-0.35} TAIL=${TAIL:-0.30}
while (($#)); do
  case "$1" in
    --shots) SHOTS=$2; shift 2 ;;
    --voice) VOICE=$2; shift 2 ;;
    --rate) RATE=$2; shift 2 ;;
    --out) OUT=$2; shift 2 ;;
    -h | --help) sed -n '2,17p' "$0"; exit 0 ;;
    *) echo "unknown option: $1" >&2; exit 2 ;;
  esac
done
FFMPEG=${FFMPEG:-$(command -v /opt/homebrew/bin/ffmpeg || command -v ffmpeg)}
FFPROBE=${FFPROBE:-$(command -v /opt/homebrew/bin/ffprobe || command -v ffprobe)}
say -v '?' | grep -q "^$VOICE " || { echo "voice not installed: $VOICE" >&2; exit 1; }

# shot | slug | default seconds | line. Claims: cached/MOCK said where it applies, only measured facts.
LINES=(
  "01|chat-opener|9.533|A Brno bakery wants a local creator. In Czechia, an unlabeled ad is her problem too. The guide says what it checks, and what it leaves out."
  "02|refusal|6.100|Religion, health, politics or origin: refused, with the reason."
  "03|subject-form|8.600|One real account in Brno, a bakery goal, two competitors she names. A cached replay of Apify data from October 9th."
  "04|identity|5.367|Is this the account she means? Likely. Each signal links its source."
  "05|competitor-check|10.867|Her check, no competitor collaboration: not met. Posts with both bakeries she named, in September. Three sources, each linking to the real post."
  "06|fact-inference-gap|7.333|Facts, inferences and gaps stay apart, each with its confidence and its basis."
  "07|goal-switch|9.233|Same data, new goal: a fitness studio. Nothing is fetched again, no language model is called. The report says what changed."
  "08|outreach-not-sent|6.000|The outreach is only a draft. The app has no send function."
  "09|mock-funnel|15.500|Discovery mode, shown on a mock example with fictional creators. Forty-eight accounts, narrowed in rounds to five. Every cut shows the round, the reason and the source, and can be restored."
  "11|end-card|4.000|Gaps are listed. No score. The owner decides."
)

dur() { "$FFPROBE" -v error -show_entries format=duration -of csv=p=0 "$1"; }
fmt() { python3 -c "import sys; t=float(sys.argv[1]); print('%d:%06.3f' % (t//60, t%60))" "$1"; }
calc() { python3 -c "print($1)"; }

mkdir -p "$OUT/clips"
rm -f "$OUT"/clips/*.aiff "$OUT"/clips/*.wav
TXT="$OUT/narration.txt"
{
  echo "Creator Scout · fallback voice-over (English)"
  echo "Voice: macOS say -v $VOICE · speech starts ${LEAD}s after each shot boundary"
  echo "Video: demo-output/fallback/creator-scout-fallback.mp4 (shot durations from $(basename "$(dirname "$SHOTS")")/shots)"
  echo "Re-record: read each line inside its window; speak '@kamvbrne' only if you want, the caption shows it."
  echo
  printf '%-3s %-20s %-19s %-19s %5s  %s\n' "#" "shot" "shot window" "speech" "rate" "line"
} >"$TXT"

T=0 FILTER="" N=0
INPUTS=()
for row in "${LINES[@]}"; do
  IFS='|' read -r id slug def text <<<"$row"
  clip="$SHOTS/$id-$slug.mp4"
  if [[ -f "$clip" ]]; then shot=$(dur "$clip"); else shot=$def; echo "warn: $clip missing, using ${def}s" >&2; fi
  budget=$(calc "$shot - $LEAD - $TAIL")
  rate=$RATE aiff="$OUT/clips/$id-$slug.aiff"
  while :; do
    say -v "$VOICE" -r "$rate" -o "$aiff" "$text"
    d=$(dur "$aiff")
    fits=$(calc "1 if $d <= $budget else 0")
    ((fits)) && break
    new=$(calc "int($rate * $d / $budget * 1.02) + 1")
    ((new > MAX_RATE)) && { echo "error: shot $id needs rate $new > $MAX_RATE (speech ${d}s, budget ${budget}s); shorten the line" >&2; exit 1; }
    rate=$new
  done
  start=$(calc "$T + $LEAD") end=$(calc "$T + $LEAD + $d")
  printf '%-3s %-20s %s-%s  %s-%s  %5s  %s\n' "$id" "$slug" "$(fmt "$T")" "$(fmt "$(calc "$T + $shot")")" \
    "$(fmt "$start")" "$(fmt "$end")" "$rate" "$text" >>"$TXT"
  printf '%s %-20s shot %6.3fs  speech %6.3fs  rate %s\n' "$id" "$slug" "$shot" "$d" "$rate"
  ms=$(calc "int(round($LEAD * 1000))")
  INPUTS+=(-i "$aiff")
  FILTER+="[$N:a]aresample=48000,aformat=channel_layouts=mono,adelay=${ms},apad,atrim=0:${shot},asetpts=N/SR/TB[a$N];"
  N=$((N + 1)) T=$(calc "$T + $shot")
done
for ((i = 0; i < N; i++)); do FILTER+="[a$i]"; done
FILTER+="concat=n=$N:v=0:a=1,loudnorm=I=-16:TP=-1.5:LRA=11,aresample=48000[out]"

"$FFMPEG" -y -v error "${INPUTS[@]}" -filter_complex "$FILTER" -map "[out]" -ac 1 -ar 48000 "$OUT/narration.wav"
"$FFMPEG" -y -v error -i "$OUT/narration.wav" -c:a aac -b:a 160k "$OUT/narration.m4a"
{
  echo
  echo "Total: $(fmt "$T") ($(printf '%.3f' "$T") s) · narration.m4a $(printf '%.3f' "$(dur "$OUT/narration.m4a")") s"
} >>"$TXT"

VIDEO="$(dirname "$SHOTS")/creator-scout-fallback.mp4"
if [[ -f "$VIDEO" ]]; then
  "$FFMPEG" -y -v error -i "$VIDEO" -i "$OUT/narration.m4a" -map 0:v -map 1:a -c:v copy -c:a copy -shortest \
    "$OUT/creator-scout-fallback-narrated.mp4"
  echo "preview: $OUT/creator-scout-fallback-narrated.mp4 (video $(dur "$VIDEO") s)"
fi
echo "total ${T}s -> $OUT/narration.m4a, $TXT"
