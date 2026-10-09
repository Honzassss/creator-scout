#!/usr/bin/env python3
"""Final assembly of the demo video: hook + cut (with narration) + outro.

    hook.mp4 (brag lane, own music) -> cut.mp4 (render_cut.py, silent) + voice_cut.wav (voice_cut.py)
    -> optional hold on the cut's last frame -> outro.mp4 (brag lane, own music)

Video: 1920x1080, 30 fps, H.264 (crf 18) + AAC 256k 48 kHz. The hook dips to the background colour in
its last 0.3 s, the cut fades in from it in 0.25 s, and the cut's last frame is held and dipped out so
the outro starts on a bar line of the music. Nothing is crossfaded picture-on-picture, so two texts
never overlap.

Audio: the hook and outro keep their own music. music_bed.wav (100 BPM, 8-bar loop, D major, same as
hook/outro) starts on the hook's last bar line under its fade-out, so the music runs on as one piece,
and is ducked by volume automation built from lines.json (each spoken line, plus a short pre-roll and
release). The outro starts on the next bar line after the cut (hold = the gap, frozen last frame), so the
bed's groove hands over to the outro on a downbeat. Master: one linear gain to TARGET_LUFS, then a
4x-oversampled lookahead limiter for the true peak; re-measured on the encoded file and corrected.

OUTPUT (demo-output/final/, gitignored):
  creator-scout-90s.mp4             the video (voice + music)
  creator-scout-90s-music-only.mp4  same picture, same music and gain, no voice (for a human voice-over)
  contact.jpg                       1 frame per second, 10 per row (row r = seconds 10r..10r+9)
  assembly.json                     the resolved timeline (all times in the full video) + loudness
  work/                             silent video, pre-master and master WAVs

Usage: python3 scripts/video/assemble.py [--hook F] [--cut F] [--voice F] [--lines F] [--bed F]
       [--outro F] [--out DIR] [--no-bar-align]
Swap footage: re-render the cut (render_cut.py --footage ...), re-run voice_cut.py, then this.
"""
import argparse, json, math, os, re, subprocess, sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
FFMPEG = "/opt/homebrew/bin/ffmpeg" if os.path.exists("/opt/homebrew/bin/ffmpeg") else "ffmpeg"
FFPROBE = "/opt/homebrew/bin/ffprobe" if os.path.exists("/opt/homebrew/bin/ffprobe") else "ffprobe"
D = lambda *p: os.path.join(ROOT, "demo-output", *p)

SR, FPS = 48000, 30
BPM = 100.0
BAR = 4 * 60.0 / BPM            # 2.4 s; the hook's beat 0 is its first frame
BED_CHORDS = ["Dmaj9", "Dmaj9", "Bm9", "Bm9", "Gmaj7", "Gmaj7", "Asus4", "A"]  # brag-music.cjs bed loop
MAX_TOTAL = 90.0
TARGET_LUFS, TP_CEIL = -14.0, -1.5   # limiter ceiling; spec is <= -1.0 dBTP after encoding
BG = "0xF3F6F8"

# bed levels (dB on the raw bed, which is about -23.4 LUFS; the voice is -16 LUFS)
BED_UP_DB, BED_DUCK_DB = 2.0, -7.0   # between lines / under a line: 9 dB of ducking (bed ~14 dB under the voice)
PRE, POST, RAMP = 0.15, 0.20, 0.35   # duck starts PRE+RAMP before a line, releases POST after it
MERGE_GAP = 0.6                      # gaps shorter than this between ducked regions stay ducked
BED_FADE_IN, BED_FADE_OUT = 0.6, 1.2   # bed rises while the hook fades (16.8-17.4), then ducks for line 1
HOOK_DIP, CUT_FADE_IN = 0.30, 0.25


def run(cmd, capture=False):
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        sys.stderr.write(r.stderr[-4000:])
        raise SystemExit(f"command failed: {' '.join(cmd[:6])} ...")
    return r.stderr if capture else None


def dur(path):
    out = subprocess.run([FFPROBE, "-v", "error", "-show_entries", "format=duration", "-of",
                          "default=nw=1:nk=1", path], capture_output=True, text=True).stdout
    return float(out.strip())


def loudness(path):
    """Integrated LUFS, LRA, true peak dBTP (ebur128, 4x oversampled)."""
    err = run([FFMPEG, "-hide_banner", "-nostats", "-i", path, "-vn", "-af",
               "ebur128=peak=true:framelog=quiet", "-f", "null", "-"], capture=True)
    summ = err[err.rfind("Summary:"):]
    i = float(re.search(r"I:\s+(-?[\d.]+|-inf) LUFS", summ).group(1))
    lra = float(re.search(r"LRA:\s+(-?[\d.]+) LU", summ).group(1))
    tp = re.search(r"Peak:\s+(-?[\d.]+|-inf) dBFS", summ).group(1)
    return {"I": i, "LRA": lra, "TP": float(tp) if tp != "-inf" else -99.0}


def duck_regions(lines, offset, total):
    regs = []
    for ln in lines:
        a, b = ln["cut"][0] + offset - PRE, ln["cut"][1] + offset + POST
        if regs and a - RAMP - (regs[-1][1] + RAMP) < MERGE_GAP:
            regs[-1][1] = b
        else:
            regs.append([a, b])
    return [(round(a, 3), round(b, 3)) for a, b in regs]


def bed_volume_expr(regs, bed_start):
    """volume filter expression in bed-local time t: dB = UP - (UP-DUCK)*D(t), D = sum of trapezoids."""
    terms = []
    for a, b in regs:
        a0, b0 = a - bed_start - RAMP, b - bed_start   # ramp down ends at a, ramp up starts at b
        terms.append(f"min(1,max(0,(t-{a0:.3f})/{RAMP}))*min(1,max(0,({b0 + RAMP:.3f}-t)/{RAMP}))")
    dsum = "+".join(terms) if terms else "0"
    return f"pow(10,({BED_UP_DB}-({BED_UP_DB - BED_DUCK_DB})*min(1,{dsum}))/20)"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--hook", default=D("brag", "hook.mp4"))
    ap.add_argument("--outro", default=D("brag", "outro.mp4"))
    ap.add_argument("--bed", default=D("brag", "music_bed.wav"))
    ap.add_argument("--cut", default=D("cut", "cut.mp4"))
    ap.add_argument("--voice", default=D("voice", "voice_cut.wav"))
    ap.add_argument("--lines", default=D("voice", "lines.json"))
    ap.add_argument("--out", default=D("final"))
    ap.add_argument("--no-bar-align", action="store_true", help="join cut and outro with no hold")
    a = ap.parse_args()
    out, work = a.out, os.path.join(a.out, "work")
    os.makedirs(work, exist_ok=True)

    H, C, O = dur(a.hook), dur(a.cut), dur(a.outro)
    V = dur(a.voice)
    if abs(V - C) > 0.05:
        raise SystemExit(f"voice ({V:.3f}s) does not match the cut ({C:.3f}s): re-run voice_cut.py")
    lines = json.load(open(a.lines))["lines"]

    # --- timeline (all in full-video seconds) ---
    bed_start = math.floor(H / BAR + 1e-6) * BAR            # last bar line inside the hook (16.8)
    if H - bed_start < 0.3:
        bed_start -= BAR
    cut_end = H + C
    hold = 0.0 if a.no_bar_align else (math.ceil((cut_end - 1e-6) / BAR) * BAR - cut_end)
    if H + C + hold + O > MAX_TOTAL:
        print(f"! bar-aligned hold ({hold:.2f}s) would exceed {MAX_TOTAL}s; joining with no hold")
        hold = 0.0
    outro_start = cut_end + hold
    total = round(outro_start + O, 3)
    if total > MAX_TOTAL:
        raise SystemExit(f"total {total:.2f}s > {MAX_TOTAL}s: shorten holds in demo-output/cut/timeline.json")
    bar_at = lambda t: int(math.floor((t - bed_start) / BAR + 1e-6))
    outro_bar = (outro_start - bed_start) / BAR
    outro_chord = BED_CHORDS[bar_at(outro_start) % 8] if abs(outro_bar - round(outro_bar)) < 0.01 else "off-grid"
    bed_end = outro_start + BED_FADE_OUT * 0.75              # bed fades out under the outro's first beats
    bed_len = round(bed_end - bed_start, 3)
    if bed_len > dur(a.bed):
        raise SystemExit("music bed too short")
    regs = duck_regions(lines, H, total)
    cut_fade = min(1.0, 0.4 + hold)

    tl = {
        "total_s": total, "fps": FPS, "size": [1920, 1080],
        "hook": [0.0, round(H, 3)], "cut": [round(H, 3), round(cut_end, 3)],
        "hold_last_frame": [round(cut_end, 3), round(outro_start, 3)],
        "outro": [round(outro_start, 3), total],
        "video_transitions": {"hook_dip_to_bg": [round(H - HOOK_DIP, 3), round(H, 3)],
                              "cut_fade_in_from_bg": [round(H, 3), round(H + CUT_FADE_IN, 3)],
                              "cut_dip_to_bg": [round(outro_start - cut_fade, 3), round(outro_start, 3)]},
        "music": {"bpm": BPM, "bar_s": BAR, "bed_in": [round(bed_start, 3), round(bed_start + BED_FADE_IN, 3)],
                  "bed_out": [round(bed_end - BED_FADE_OUT, 3), round(bed_end, 3)],
                  "bed_chord_at_hook_join": BED_CHORDS[bar_at(H - 0.01) % 8] if H > bed_start else "-",
                  "bed_chord_where_outro_starts": outro_chord,
                  "bed_up_db": BED_UP_DB, "bed_duck_db": BED_DUCK_DB, "ducked_regions": regs},
        "voice_lines": [{"n": l["n"], "full": [round(l["cut"][0] + H, 3), round(l["cut"][1] + H, 3)],
                         "text": l["text"]} for l in lines],
        "sources": {k: os.path.relpath(getattr(a, k), ROOT) for k in ["hook", "cut", "voice", "lines", "bed", "outro"]},
    }
    print(f"hook {H:.2f} + cut {C:.2f} + hold {hold:.2f} + outro {O:.2f} = {total:.2f} s; "
          f"bed {bed_start:.2f}-{bed_end:.2f}; outro on bar {outro_bar:.2f} ({outro_chord})")

    # --- picture (encoded once, muxed twice) ---
    vid = os.path.join(work, "video.mp4")
    norm = f"fps={FPS},scale=1920:1080:flags=lanczos,setsar=1,format=yuv420p"
    vf = (f"[0:v]{norm},fade=t=out:st={H - HOOK_DIP:.3f}:d={HOOK_DIP}:color={BG}[hv];"
          f"[1:v]{norm},fade=t=in:st=0:d={CUT_FADE_IN}:color={BG},"
          f"tpad=stop_mode=clone:stop_duration={hold:.3f},"
          f"fade=t=out:st={C + hold - cut_fade:.3f}:d={cut_fade:.3f}:color={BG}[cv];"
          f"[2:v]{norm}[ov];[hv][cv][ov]concat=n=3:v=1:a=0[v]")
    run([FFMPEG, "-hide_banner", "-y", "-i", a.hook, "-i", a.cut, "-i", a.outro, "-filter_complex", vf,
         "-map", "[v]", "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-pix_fmt", "yuv420p",
         "-r", str(FPS), "-movflags", "+faststart", "-t", f"{total:.3f}", vid])

    # --- audio: pre-master mixes (with and without voice) ---
    fmt = f"aresample={SR},aformat=sample_fmts=fltp:channel_layouts=stereo"
    ms = lambda t: int(round(t * 1000))
    def premix(with_voice, dst):
        parts = [f"[0:a]{fmt},atrim=0:{H:.3f}[ha]",
                 f"[2:a]{fmt},atrim=0:{bed_len:.3f},asetpts=PTS-STARTPTS,"
                 f"volume='{bed_volume_expr(regs, bed_start)}':eval=frame,"
                 f"afade=t=in:st=0:d={BED_FADE_IN},afade=t=out:st={bed_len - BED_FADE_OUT:.3f}:d={BED_FADE_OUT},"
                 f"adelay={ms(bed_start)}:all=1[ba]",
                 f"[3:a]{fmt},adelay={ms(outro_start)}:all=1[oa]"]
        ins = "[ha][ba][oa]"
        if with_voice:
            parts.append(f"[1:a]{fmt},adelay={ms(H)}:all=1[va]")
            ins += "[va]"
        n = 4 if with_voice else 3
        parts.append(f"{ins}amix=inputs={n}:normalize=0:duration=longest,apad,atrim=0:{total:.3f}[mix]")
        run([FFMPEG, "-hide_banner", "-y", "-i", a.hook, "-i", a.voice, "-i", a.bed, "-i", a.outro,
             "-filter_complex", ";".join(parts), "-map", "[mix]", "-c:a", "pcm_f32le", "-ar", str(SR), dst])

    pre_v, pre_m = os.path.join(work, "premix_voice.wav"), os.path.join(work, "premix_music.wav")
    premix(True, pre_v)
    premix(False, pre_m)
    L0 = loudness(pre_v)
    print(f"pre-master (voice): {L0}")

    def master(src, dst, gain, ceil):
        lim = 10 ** (ceil / 20)
        run([FFMPEG, "-hide_banner", "-y", "-i", src, "-af",
             f"volume={gain:.3f}dB,aresample={SR * 4},alimiter=limit={lim:.5f}:attack=3:release=60:level=false,"
             f"aresample={SR}", "-c:a", "pcm_f32le", dst])

    def mux(wav, dst):
        run([FFMPEG, "-hide_banner", "-y", "-i", vid, "-i", wav, "-map", "0:v", "-map", "1:a", "-c:v", "copy",
             "-c:a", "aac", "-b:a", "256k", "-ar", str(SR), "-ac", "2", "-movflags", "+faststart",
             "-t", f"{total:.3f}", dst])

    final = os.path.join(out, "creator-scout-90s.mp4")
    gain, ceil = TARGET_LUFS - L0["I"], TP_CEIL
    for attempt in range(4):
        m_v = os.path.join(work, "master_voice.wav")
        master(pre_v, m_v, gain, ceil)
        mux(m_v, final)
        Lf = loudness(final)
        print(f"  pass {attempt + 1}: gain {gain:+.2f} dB, ceiling {ceil:.1f} -> {Lf}")
        ok_i, ok_tp = abs(Lf["I"] - TARGET_LUFS) <= 0.2, Lf["TP"] <= -1.0
        if ok_i and ok_tp:
            break
        if not ok_tp:
            ceil -= 0.5
        if not ok_i:
            gain += TARGET_LUFS - Lf["I"]

    music_only = os.path.join(out, "creator-scout-90s-music-only.mp4")
    m_m = os.path.join(work, "master_music.wav")
    master(pre_m, m_m, gain, ceil)        # same gain staging as the voiced mix, so hook/outro match
    mux(m_m, music_only)
    Lm = loudness(music_only)

    # --- contact sheet: 1 fps, 10 per row ---
    rows = math.ceil(math.floor(total) / 10 + 0.01)
    run([FFMPEG, "-hide_banner", "-y", "-i", final, "-vf",
         f"select='not(mod(n\\,{FPS}))',scale=384:216,tile=10x{rows}:padding=6:margin=6:color=white", "-frames:v", "1",
         "-q:v", "3", os.path.join(out, "contact.jpg")])

    tl["loudness"] = {"final": Lf, "music_only": Lm, "master_gain_db": round(gain, 2), "limiter_ceiling_dbfs": ceil,
                      "pre_master": L0}
    tl["duration_probe_s"] = {"final": dur(final), "music_only": dur(music_only)}
    json.dump(tl, open(os.path.join(out, "assembly.json"), "w"), indent=1, ensure_ascii=False)
    print(json.dumps({"final": final, "music_only": music_only, **tl["duration_probe_s"],
                      "loudness": tl["loudness"]}, indent=1))


if __name__ == "__main__":
    main()
