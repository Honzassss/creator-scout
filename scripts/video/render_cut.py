#!/usr/bin/env python3
"""Render the demo cut (zoom/pan + kinetic captions) from a timeline file.

usage: python3 scripts/video/render_cut.py [--timeline demo-output/cut/timeline.json]
                                           [--footage demo-output/v2] [--out demo-output/cut/cut.mp4]
                                           [--only-assets] [--keep]

The footage folder must contain shots/NN-*.mp4 (the recorder's layout); each timeline segment picks
its shot by number, so a new recording with the same shots re-renders with no edits. Zoom rects are
in the timeline's ref_size (1440x900) and are scaled to the footage resolution.

Pipeline: (1) overlay PNGs (background, chips, caption pills) rendered by headless Chrome with a
transparent background, IBM Plex Sans from Google Fonts; (2) one 1440x900 clip per segment:
trim, speed, freeze-pad, 2x upscale, zoompan with smootherstep easing between rect keyframes;
(3) xfade chain; (4) composite onto the 1920x1080 frame with eased caption/chip fades and slides.
Writes cut.mp4 (no audio) and cut_start/cut_end back into the timeline.
"""
from __future__ import annotations

import argparse
import glob
import hashlib
import html
import json
import os
import shutil
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FFMPEG = shutil.which("ffmpeg") or "/opt/homebrew/bin/ffmpeg"
FFPROBE = shutil.which("ffprobe") or "/opt/homebrew/bin/ffprobe"
CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"

W, H = 1920, 1080
VX, VY, VW, VH = 240, 80, 1440, 900  # footage viewport inside the frame
ENC = ["-c:v", "libx264", "-preset", "medium", "-crf", "17", "-pix_fmt", "yuv420p", "-r", "30", "-an"]

# shared visual identity
BG, PANEL, TEXT, TEXT2, ACCENT, TINT, LINE = "#F3F6F8", "#FFFFFF", "#182C36", "#435965", "#086B68", "#E4F3F0", "#DCE4E8"
FONT_LINK = '<link href="https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:wght@500;600&family=IBM+Plex+Mono:wght@500;600&display=block" rel="stylesheet">'
BASE_CSS = (
    "html,body{margin:0;padding:0;background:transparent;overflow:hidden}"
    "body{font-family:'IBM Plex Sans',sans-serif;font-feature-settings:'tnum' 1;-webkit-font-smoothing:antialiased;color:%s}" % TEXT
)


def run(cmd: list[str], quiet: bool = True) -> None:
    r = subprocess.run(cmd, stdout=subprocess.DEVNULL if quiet else None, stderr=subprocess.PIPE, text=True)
    if r.returncode != 0:
        sys.stderr.write(r.stderr[-4000:])
        raise SystemExit(f"command failed: {' '.join(cmd[:6])} ...")


def probe_size(path: Path) -> tuple[int, int]:
    out = subprocess.run([FFPROBE, "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height",
                          "-of", "csv=p=0", str(path)], check=True, capture_output=True, text=True).stdout.strip()
    w, h = out.split(",")[:2]
    return int(w), int(h)


# ---------------------------------------------------------------- overlay PNGs (headless Chrome)

def page(body: str, css: str) -> str:
    return f"<!doctype html><html><head><meta charset='utf-8'>{FONT_LINK}<style>{BASE_CSS}{css}</style></head><body>{body}</body></html>"


def bg_html() -> str:
    css = (
        f"body{{background:{BG};width:{W}px;height:{H}px;position:relative}}"
        f".frame{{position:absolute;left:{VX-12}px;top:{VY-12}px;width:{VW+24}px;height:{VH+24}px;background:{PANEL};"
        f"border-radius:18px;box-shadow:0 0 0 1px {LINE},0 18px 48px rgba(24,44,54,.10),0 2px 6px rgba(24,44,54,.05)}}"
        f".well{{position:absolute;left:12px;top:12px;width:{VW}px;height:{VH}px;background:#10161a;border-radius:6px}}"
        f".mark{{position:absolute;left:{VX}px;top:17px;display:flex;align-items:center;gap:11px;font-weight:600;font-size:21px;letter-spacing:-.01em}}"
        f".logo{{width:30px;height:30px;border-radius:8px;background:{ACCENT};display:grid;place-items:center}}"
    )
    logo = ("<svg width='16' height='16' viewBox='0 0 16 16'><path d='M2 3h12l-4.5 5.2V13l-3 1V8.2z' fill='none' "
            "stroke='#fff' stroke-width='1.6' stroke-linejoin='round'/></svg>")
    return page(f"<div class='frame'><div class='well'></div></div><div class='mark'><div class='logo'>{logo}</div>Creator Scout</div>", css)


def step_html(num: str, label: str) -> str:
    css = (
        ".c{position:absolute;left:8px;top:8px;display:inline-flex;align-items:center;gap:10px;height:36px;padding:0 16px 0 6px;"
        f"background:{PANEL};border-radius:999px;box-shadow:0 0 0 1px {LINE},0 4px 12px rgba(24,44,54,.06);font-size:17px;font-weight:600}}"
        f".n{{display:grid;place-items:center;height:26px;min-width:34px;padding:0 6px;border-radius:999px;background:{TINT};color:{ACCENT};"
        "font-size:14px;font-weight:600;font-variant-numeric:tabular-nums}"
    )
    return page(f"<div class='c'><span class='n'>{html.escape(num)}</span>{html.escape(label)}</div>", css)


def label_html(kind: str) -> str:
    if kind == "mock":
        fg, bgc, dot, text = "#9B1D5F", "#FBE6F1", "#D6337F", "MOCK · fictional creators"
    else:
        fg, bgc, dot, text = ACCENT, TINT, ACCENT, "CACHED · real public data, 9 Oct 2026"
    css = (
        ".w{position:absolute;right:8px;top:8px;display:flex;justify-content:flex-end}"
        f".c{{display:inline-flex;align-items:center;gap:9px;height:36px;padding:0 16px;border-radius:999px;background:{bgc};color:{fg};"
        f"box-shadow:inset 0 0 0 1px {fg}33;font-family:'IBM Plex Mono',monospace;font-size:15px;font-weight:600;letter-spacing:.02em}}"
        f".d{{width:8px;height:8px;border-radius:50%;background:{dot}}}"
    )
    return page(f"<div class='w'><div class='c'><span class='d'></span>{html.escape(text)}</div></div>", css)


def caption_html(text: str) -> str:
    css = (
        ".p{position:absolute;left:12px;top:12px;display:inline-flex;align-items:center;gap:16px;height:58px;padding:0 26px 0 16px;"
        f"background:{PANEL};border-radius:14px;box-shadow:0 0 0 1px {LINE},0 10px 28px rgba(24,44,54,.12);"
        "font-size:27px;font-weight:600;letter-spacing:-.005em;white-space:nowrap}"
        f".b{{width:5px;height:30px;border-radius:3px;background:{ACCENT}}}"
    )
    return page(f"<div class='p'><span class='b'></span>{html.escape(text)}</div>", css)


ASSET_SIZES = {"bg": (W, H), "step": (640, 56), "label": (640, 56), "caption": (1380, 100)}


def render_png(kind: str, doc: str, cache: Path) -> Path:
    for attempt in range(3):
        try:
            return _render_png(kind, doc, cache)
        except SystemExit:
            if attempt == 2:
                raise
    raise AssertionError


def _render_png(kind: str, doc: str, cache: Path) -> Path:
    w, h = ASSET_SIZES[kind]
    key = hashlib.sha1((kind + doc).encode()).hexdigest()[:12]
    png = cache / f"{kind}-{key}.png"
    if png.exists():
        return png
    src = cache / f"{kind}-{key}.html"
    src.write_text(doc, encoding="utf-8")
    # Headless Chrome often hangs on teardown after writing the PNG: watch for the file, then kill it.
    prof = cache / ("profile-" + key)
    proc = subprocess.Popen([CHROME, "--headless=new", "--disable-gpu", "--hide-scrollbars", "--force-device-scale-factor=1",
                             f"--user-data-dir={prof}", "--no-first-run",
                             "--default-background-color=00000000", "--virtual-time-budget=4000", f"--window-size={w},{h}",
                             f"--screenshot={png}", src.as_uri()], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    t0, last = time.time(), -1
    while time.time() - t0 < 60:
        if proc.poll() is not None and not png.exists():
            break
        if png.exists():
            size = png.stat().st_size
            if size > 0 and size == last:
                break
            last = size
        time.sleep(0.4)
    proc.kill()
    proc.wait()
    shutil.rmtree(prof, ignore_errors=True)
    if not png.exists():
        raise SystemExit(f"chrome did not write {png}")
    return png


# ---------------------------------------------------------------- segment clips

def eased(keys: list[tuple[float, float]]) -> str:
    """ffmpeg expression of T (seconds) easing through (t, value) keyframes with smootherstep."""
    expr = f"{keys[0][1]:.3f}"
    for (t0, v0), (t1, v1) in zip(keys, keys[1:]):
        if abs(v1 - v0) < 1e-6:
            continue
        span = max(t1 - t0, 1e-3)
        p = f"clip((T-{t0:.3f})/{span:.3f},0,1)"
        expr += f"+({v1 - v0:.3f})*(st(1,{p})*ld(1)*ld(1)*(ld(1)*(6*ld(1)-15)+10))"
    return expr


def segment_clip(seg: dict, src: Path, ref: tuple[int, int], out: Path, fps: int) -> None:
    sw, sh = probe_size(src)
    kx = sw / ref[0]
    aspect = VH / VW
    keys = []
    for k in seg["zoom"]:
        x, y, w = k["rect"]
        x, y, w = x * kx, y * kx, w * kx
        w = min(w, sw)
        h = w * aspect
        x = min(max(x, 0), sw - w)
        y = min(max(y, 0), sh - h)
        keys.append((float(k["t"]), x, y, w))
    # upscale 2x before zoompan so its integer crop offsets move in half-pixels (less jitter)
    tx = "(on/%d)" % fps
    # zoompan works in the upscaled input space (iw = UW): visible width = UW / zoom.
    UW, UH = VW * 2, VH * 2
    s = UW / sw
    wexpr = eased([(t, w * s) for t, _, _, w in keys]).replace("T", tx)
    xexpr = eased([(t, x * s) for t, x, _, _ in keys]).replace("T", tx)
    yexpr = eased([(t, y * s) for t, _, y, _ in keys]).replace("T", tx)
    natural = (seg["out"] - seg["in"]) / seg["speed"]
    pad = max(0.0, seg["dur"] - natural) + 0.2
    vf = (
        f"trim=start={seg['in']}:end={seg['out']},setpts=(PTS-STARTPTS)/{seg['speed']},fps={fps},"
        f"tpad=stop_mode=clone:stop_duration={pad:.3f},trim=duration={seg['dur']},setpts=PTS-STARTPTS,"
        f"scale={UW}:{UH}:flags=lanczos,"
        f"zoompan=z='{UW}/({wexpr})':x='{xexpr}':y='{yexpr}':d=1:s={VW}x{VH}:fps={fps},"
        f"setsar=1,format=yuv420p"
    )
    script = out.with_suffix(".vf")
    script.write_text(vf, encoding="utf-8")
    run([FFMPEG, "-y", "-v", "error", "-i", str(src), "-filter_script:v", str(script), *ENC, str(out)])


# ---------------------------------------------------------------- main

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--timeline", default=str(ROOT / "demo-output/cut/timeline.json"))
    ap.add_argument("--footage", default=None, help="footage folder with shots/NN-*.mp4 (default: timeline 'footage')")
    ap.add_argument("--out", default=None)
    ap.add_argument("--only-assets", action="store_true")
    ap.add_argument("--keep", action="store_true", help="keep the work folder")
    a = ap.parse_args()

    tl_path = Path(a.timeline).resolve()
    tl = json.loads(tl_path.read_text(encoding="utf-8"))
    footage = Path(a.footage or tl["footage"])
    if not footage.is_absolute():
        footage = (ROOT / footage).resolve()
    out = Path(a.out).resolve() if a.out else tl_path.parent / "cut.mp4"
    work = tl_path.parent / "work"
    cache = work / "assets"
    cache.mkdir(parents=True, exist_ok=True)
    fps, xf = int(tl.get("fps", 30)), float(tl.get("xfade", 0.3))
    ref = tuple(tl.get("ref_size", [1440, 900]))
    segs = tl["segments"]

    # timing
    t = 0.0
    for s in segs:
        s["cut_start"] = round(t, 3)
        s["cut_end"] = round(t + s["dur"], 3)
        t += s["dur"] - xf
    total = round(segs[-1]["cut_end"], 3)
    print(f"cut: {len(segs)} segments, {total:.2f} s, footage {footage}")
    if total > 90.0:
        raise SystemExit("cut longer than 90 s")

    # overlay assets
    jobs = [("bg", bg_html())]
    for s in segs:
        jobs.append(("step", step_html(*s["step"])))
        jobs.append(("label", label_html(s.get("label", "cached"))))
        for c in s.get("captions", []):
            jobs.append(("caption", caption_html(c["text"])))
    with ThreadPoolExecutor(6) as ex:
        pngs = list(ex.map(lambda j: render_png(j[0], j[1], cache), jobs))
    png_of = {j[1]: p for j, p in zip(jobs, pngs)}
    if a.only_assets:
        print("\n".join(str(p) for p in dict.fromkeys(pngs)))
        return 0

    # segment clips
    def build(i_s):
        i, s = i_s
        cands = sorted(glob.glob(str(footage / "shots" / f"{s['shot']}-*.mp4")))
        if s.get("file"):
            cands = [str(footage / s["file"])]
        if not cands:
            raise SystemExit(f"no shot {s['shot']} in {footage}/shots")
        clip = work / f"seg{i:02d}-{s['id']}.mp4"
        segment_clip(s, Path(cands[0]), ref, clip, fps)
        return clip
    with ThreadPoolExecutor(4) as ex:
        clips = list(ex.map(build, enumerate(segs)))

    # xfade chain -> footage.mp4 (1440x900)
    footage_mp4 = work / "footage.mp4"
    inputs, chain, last, acc = [], [], "0:v", 0.0
    for i, c in enumerate(clips):
        inputs += ["-i", str(c)]
    for i in range(1, len(clips)):
        acc += segs[i - 1]["dur"] - xf
        outl = f"x{i}"
        chain.append(f"[{last}][{i}:v]xfade=transition=fade:duration={xf}:offset={acc:.3f}[{outl}]")
        last = outl
    fc = ";".join(chain) if chain else "[0:v]null[x0]"
    (work / "xfade.fc").write_text(fc, encoding="utf-8")
    run([FFMPEG, "-y", "-v", "error", *inputs, "-filter_complex_script", str(work / "xfade.fc"),
         "-map", f"[{last if chain else 'x0'}]", *ENC, str(footage_mp4)])

    # overlays: chips (grouped spans), captions
    overlays = []  # (png, start, end, x, y, slide)
    def spans(key):
        groups = []
        for s in segs:
            k = key(s)
            if groups and groups[-1][0] == k:
                groups[-1][2] = s["cut_end"]
            else:
                groups.append([k, s["cut_start"], s["cut_end"]])
        return groups
    for (num, lab), st, en in spans(lambda s: tuple(s["step"])):
        overlays.append((png_of[step_html(num, lab)], st + 0.15, min(en, total) - (xf if en < total else 0) + 0.05, 466 - 8, 16 - 8, 10))
    for kind, st, en in spans(lambda s: s.get("label", "cached")):
        overlays.append((png_of[label_html(kind)], st + 0.15, min(en, total) - (xf if en < total else 0) + 0.05, VX + VW + 8 - 640, 16 - 8, 10))
    for s in segs:
        for c in s.get("captions", []):
            st, en = s["cut_start"] + c["at"], s["cut_start"] + c["until"]
            overlays.append((png_of[caption_html(c["text"])], st, en, VX - 12, 1005 - 12, 18))
            c["cut_start"], c["cut_end"] = round(st, 3), round(en, 3)

    args = ["-loop", "1", "-framerate", str(fps), "-t", f"{total:.3f}", "-i", str(png_of[bg_html()]), "-i", str(footage_mp4)]
    fcs = [f"[0:v]format=rgba[bg]", f"[bg][1:v]overlay=x={VX}:y={VY}:shortest=1[b0]"]
    base = "b0"
    for n, (png, st, en, x, y, slide) in enumerate(overlays):
        d = max(en - st, 0.5)
        args += ["-loop", "1", "-framerate", str(fps), "-t", f"{d:.3f}", "-i", str(png)]
        idx = n + 2
        fcs.append(
            f"[{idx}:v]format=rgba,fade=t=in:st=0:d=0.35:alpha=1,fade=t=out:st={d - 0.25:.3f}:d=0.25:alpha=1,"
            f"setpts=PTS-STARTPTS+{st:.3f}/TB[o{n}]"
        )
        yexp = f"{y}+{slide}*pow(1-clip((t-{st:.3f})/0.45,0,1),3)"
        fcs.append(f"[{base}][o{n}]overlay=x={x}:y='{yexp}':eof_action=pass:eval=frame[b{n + 1}]")
        base = f"b{n + 1}"
    # progress rail along the bottom edge
    args += ["-f", "lavfi", "-t", f"{total:.3f}", "-i", f"color=c={ACCENT}:s={W}x4:r={fps}"]
    ridx = len(overlays) + 2
    fcs.append(f"[{base}][{ridx}:v]overlay=x='-W+W*t/{total:.3f}':y=H-4:shortest=1,format=yuv420p[vout]")
    (work / "composite.fc").write_text(";\n".join(fcs), encoding="utf-8")
    run([FFMPEG, "-y", "-v", "error", *args, "-filter_complex_script", str(work / "composite.fc"),
         "-map", "[vout]", "-t", f"{total:.3f}", *ENC, "-movflags", "+faststart", str(out)])

    tl["rendered"] = {"file": str(out.relative_to(ROOT)) if out.is_relative_to(ROOT) else str(out),
                      "footage": str(footage.relative_to(ROOT)) if footage.is_relative_to(ROOT) else str(footage),
                      "duration": total}
    tl_path.write_text(json.dumps(tl, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    if not a.keep:
        for p in work.glob("seg*.mp4"):
            p.unlink()
    print(f"wrote {out} ({total:.2f} s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
