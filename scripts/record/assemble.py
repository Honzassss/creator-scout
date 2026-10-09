#!/usr/bin/env python3
"""Cut and assemble the takes recorded by scripts/record-demo.sh.

usage: assemble.py <out_dir> <ffmpeg> <ffprobe> <video 0|1>

Reads <out>/markers.tsv (segment, shot, slug, wall time, script seconds, caption) and the raw takes
<out>/raw/<segment>.webm + <segment>.stop (wall time when `record stop` was called). The video start
is calibrated as stop - duration, so shot boundaries come from wall-clock markers.

Writes: shots/NN-slug.mp4 (real speed), creator-scout-demo.mp4 (all shots + end card),
storyboard.mp4 (one still per shot at the script durations), shots.tsv.
"""
from __future__ import annotations

import csv
import subprocess
import sys
from pathlib import Path

END_CARD_SECONDS = 4.0
LIMIT_SECONDS = 90.0  # submission video limit (docs/video-script.md)
LEAD = 0.15  # start each cut slightly before its marker
ENC = ["-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-pix_fmt", "yuv420p", "-r", "30", "-an"]


def run(cmd: list[str]) -> None:
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)


def duration(ffprobe: str, path: Path) -> float:
    out = subprocess.run(
        [ffprobe, "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
        check=True, capture_output=True, text=True,
    ).stdout.strip()
    return float(out)


def main() -> int:
    out, ffmpeg, ffprobe, video = Path(sys.argv[1]), sys.argv[2], sys.argv[3], sys.argv[4] == "1"
    rows = [r for r in csv.reader((out / "markers.tsv").open(encoding="utf-8"), delimiter="\t") if r]
    shots = [
        {"seg": r[0], "nn": r[1], "slug": r[2], "wall": float(r[3]), "script": float(r[4]), "caption": r[5]}
        for r in rows
    ]
    (out / "shots").mkdir(exist_ok=True)
    frames = out / "frames"
    end_png = frames / "11-end-card.png"

    clips: list[Path] = []
    if video:
        for seg in dict.fromkeys(s["seg"] for s in shots):
            webm, stop = out / "raw" / f"{seg}.webm", out / "raw" / f"{seg}.stop"
            if not webm.exists() or not stop.exists():
                print(f"assemble: missing take {webm.name}; skipping its shots", file=sys.stderr)
                continue
            d = duration(ffprobe, webm)
            vstart = float(stop.read_text().strip()) - d
            seg_shots = [s for s in shots if s["seg"] == seg]
            for i, s in enumerate(seg_shots):
                a = max(0.0, s["wall"] - vstart - LEAD)
                b = (seg_shots[i + 1]["wall"] - vstart - LEAD) if i + 1 < len(seg_shots) else d
                s["real"] = round(max(0.1, b - a), 2)
                clip = out / "shots" / f"{s['nn']}-{s['slug']}.mp4"
                run([ffmpeg, "-y", "-v", "error", "-ss", f"{a:.3f}", "-i", str(webm), "-t", f"{b - a:.3f}",
                     "-vf", "scale=1440:900:force_original_aspect_ratio=decrease,pad=1440:900:(ow-iw)/2:(oh-ih)/2",
                     *ENC, str(clip)])
                s["file"] = f"shots/{clip.name}"
                clips.append(clip)

    if end_png.exists():
        end_clip = out / "shots" / "11-end-card.mp4"
        run([ffmpeg, "-y", "-v", "error", "-loop", "1", "-t", str(END_CARD_SECONDS), "-i", str(end_png),
             "-vf", "scale=1440:900", *ENC, str(end_clip)])
        if clips:
            clips.append(end_clip)

    if clips:
        lst = out / "shots" / "concat.txt"
        lst.write_text("".join(f"file '{c.name}'\n" for c in clips))
        run([ffmpeg, "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", str(lst), "-c", "copy",
             "-movflags", "+faststart", str(out / "creator-scout-demo.mp4")])
        lst.unlink()

    # Storyboard: one still per shot at the script's shot durations (fallback if the takes are unusable).
    board = [(frames / f"{s['nn']}-{s['slug']}.png", s["script"]) for s in shots]
    if end_png.exists():
        board.append((end_png, END_CARD_SECONDS))
    board = [(p, t) for p, t in board if p.exists()]
    if board:
        lst = out / "storyboard.txt"
        body = "".join(f"file '{p}'\nduration {t}\n" for p, t in board) + f"file '{board[-1][0]}'\n"
        lst.write_text(body)
        total = sum(t for _, t in board)
        run([ffmpeg, "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", str(lst),
             "-vf", "scale=1440:900,fps=30", *ENC, "-t", f"{total}", "-movflags", "+faststart",
             str(out / "storyboard.mp4")])
        lst.unlink()

    with (out / "shots.tsv").open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f, delimiter="\t")
        w.writerow(["shot", "file", "real_seconds", "script_seconds", "frame", "script_caption"])
        for s in shots:
            w.writerow([s["nn"], s.get("file", ""), s.get("real", ""), s["script"],
                        f"frames/{s['nn']}-{s['slug']}.png", s["caption"]])
        if end_png.exists():
            w.writerow(["11", "shots/11-end-card.mp4" if clips else "", END_CARD_SECONDS, END_CARD_SECONDS,
                        "frames/11-end-card.png", "Creator Scout · public data · no score · the owner decides"])

    for name in ("creator-scout-demo.mp4", "storyboard.mp4"):
        p = out / name
        if p.exists():
            d = duration(ffprobe, p)
            print(f"{name}: {d:.1f} s, {p.stat().st_size / 1e6:.1f} MB")
            if d > LIMIT_SECONDS:
                print(f"warn: {name} is {d:.1f} s, over the {LIMIT_SECONDS:.0f} s limit; trim in the edit "
                      "(shot 2: jump-cut the typed answers, caption 'answers cut for time'; shots.tsv has real vs. script)")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except subprocess.CalledProcessError as e:
        print(f"assemble: ffmpeg failed: {' '.join(map(str, e.cmd))[:300]}\n{(e.stderr or b'').decode()[-800:]}",
              file=sys.stderr)
        sys.exit(1)
