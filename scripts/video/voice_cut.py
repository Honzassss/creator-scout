#!/usr/bin/env python3
"""Narration for the demo cut (macOS `say`, no account, no network).

Reads the cut timeline (demo-output/cut/timeline.json, written back by render_cut.py), renders one
clip per segment, starts each line LEAD s after its segment starts in the cut, keeps it inside the
segment (speeds up with `say -r` only if needed, up to MAX_RATE), and lays all clips on one track
exactly as long as the cut. One linear gain brings the speech to TARGET_LUFS (no compressor).

OUTPUT (demo-output/voice/, gitignored):
  voice_cut.wav          48 kHz stereo s16, exactly the cut length, speech only
  lines.txt              text + timestamps in the cut AND in the full video (hook + cut), for a re-record
  lines.json             same, machine-readable (for the mix)
  clips/NN-<segment>.wav one trimmed clip per line
  cut_with_voice.mp4     preview: cut.mp4 + this track (no music)

Usage: python3 scripts/video/voice_cut.py [--timeline FILE] [--hook FILE|SECONDS] [--voice NAME]
       [--rate WPM] [--out DIR]
Swap footage: re-render the cut (render_cut.py), then re-run this; times come from the timeline.
"""
import argparse, array, json, math, os, re, subprocess, sys, wave

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
FFMPEG = "/opt/homebrew/bin/ffmpeg" if os.path.exists("/opt/homebrew/bin/ffmpeg") else "ffmpeg"
FFPROBE = "/opt/homebrew/bin/ffprobe" if os.path.exists("/opt/homebrew/bin/ffprobe") else "ffprobe"
SR = 48000
LEAD, TAIL = 0.30, 0.25          # speech starts LEAD after the segment starts, ends TAIL before it ends
MAX_RATE, TARGET_LUFS, MAX_TP = 215, -16.0, -1.5

# segment id -> line. Claims only from the cached real run r_309c4df8c2 (v1 recording) and the brief;
# the funnel is MOCK and the line says so. No narration over the hook or the outro (own copy + music).
LINES = {
    "a-form": "A real run, replayed from cache. She names one creator, her goal, "
              "and the two bakeries she competes with.",
    "b-identity": "Is it the right account? Likely. The bio and forty posts point to Brno.",
    "c1-check": "Her rule: no competitor deals. Not met.",
    "c2-sources": "Three September posts mention both bakeries she named. Each links to the public post, "
                  "with the fetch time and the Apify actor behind it.",
    "d-fact-inference-gap": "Facts, inferences and gaps stay apart. Even what it could not check is on the page.",
    "e-goal-switch": "Same creator, new goal: a fitness studio. Nothing is fetched again. "
                     "Bakeries aren't rivals now, so the check flips to met.",
    "f-outreach": "The outreach is rewritten too, and it stays a draft. The app sends nothing.",
    "h-refusal": "Filter by religion? It refuses, and says why.",
    "g-mock-funnel": "Discovery mode, on mock data with fictional creators: forty-eight accounts, "
                     "narrowed in three rounds to five.",
    "g2-reasons": "Every cut has a reason, and can be restored. No scores.",
}


def run(cmd, **kw):
    return subprocess.run(cmd, check=True, capture_output=True, text=True, **kw)


def dur(path):
    return float(run([FFPROBE, "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", path]).stdout)


def fmt(t):
    return "%d:%06.3f" % (t // 60, t % 60)


def render(text, voice, rate, wav):
    aiff = wav[:-4] + ".aiff"
    run(["say", "-v", voice, "-r", str(rate), "-o", aiff, text])
    trim = "silenceremove=start_periods=1:start_threshold=-55dB"
    run([FFMPEG, "-y", "-v", "error", "-i", aiff, "-af",
         f"{trim},areverse,{trim},areverse,aresample={SR}", "-ac", "1", "-c:a", "pcm_s16le", wav])
    os.remove(aiff)
    return dur(wav)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--timeline", default=os.path.join(ROOT, "demo-output/cut/timeline.json"))
    ap.add_argument("--cut", default=os.path.join(ROOT, "demo-output/cut/cut.mp4"))
    ap.add_argument("--hook", default=os.path.join(ROOT, "demo-output/brag/hook.mp4"),
                    help="hook video (its length offsets the full-video times) or a number of seconds")
    ap.add_argument("--voice", default="Samantha")
    ap.add_argument("--rate", type=int, default=180)
    ap.add_argument("--out", default=os.path.join(ROOT, "demo-output/voice"))
    a = ap.parse_args()

    tl = json.load(open(a.timeline))
    segs = tl["segments"]
    total = dur(a.cut) if os.path.exists(a.cut) else max(s["cut_end"] for s in segs)
    try:
        hook = float(a.hook)
    except ValueError:
        hook = dur(a.hook) if os.path.exists(a.hook) else 17.4
    os.makedirs(os.path.join(a.out, "clips"), exist_ok=True)

    nsamp = int(round(total * SR))
    track = array.array("h", bytes(2 * nsamp))
    rows = []
    for i, s in enumerate(segs):
        text = LINES.get(s["id"])
        if not text:
            continue
        start = s["cut_start"] + LEAD
        end = s["cut_end"] - TAIL
        if i + 1 < len(segs):  # never run into the next line
            end = min(end, segs[i + 1]["cut_start"] + LEAD - TAIL)
        budget = end - start
        wav = os.path.join(a.out, "clips", "%02d-%s.wav" % (len(rows) + 1, s["id"]))
        rate = a.rate
        d = render(text, a.voice, rate, wav)
        while d > budget:
            new = int(math.ceil(rate * d / budget * 1.02))
            if new > MAX_RATE:
                sys.exit(f"error: {s['id']} needs rate {new} > {MAX_RATE} ({d:.2f}s in {budget:.2f}s); shorten it")
            rate = new
            d = render(text, a.voice, rate, wav)
        with wave.open(wav) as w:
            clip = array.array("h", w.readframes(w.getnframes()))
        o = int(round(start * SR))
        n = min(len(clip), nsamp - o)
        track[o:o + n] = clip[:n]
        rows.append(dict(n=len(rows) + 1, segment=s["id"], step=" ".join(s.get("step", [])),
                         label=s.get("label", ""), shot=[s["cut_start"], s["cut_end"]],
                         cut=[round(start, 3), round(start + d, 3)],
                         full=[round(hook + start, 3), round(hook + start + d, 3)],
                         budget=round(budget, 3), rate=rate, text=text))
        print(f"{s['id']:<22} speech {d:5.2f}s / {budget:5.2f}s  rate {rate}")

    raw = os.path.join(a.out, "voice_raw.wav")
    with wave.open(raw, "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(SR); w.writeframes(track.tobytes())
    # one linear gain to TARGET_LUFS, capped so true peak stays <= MAX_TP
    st_raw = os.path.join(a.out, "voice_raw_st.wav")  # dual mono at full level, measured as delivered
    run([FFMPEG, "-y", "-v", "error", "-i", raw, "-af", "pan=stereo|c0=c0|c1=c0", "-c:a", "pcm_s16le", st_raw])
    os.replace(st_raw, raw)
    m = run([FFMPEG, "-v", "info", "-i", raw, "-af", "loudnorm=print_format=json", "-f", "null", "-"]).stderr
    st = json.loads(re.search(r"\{[^{}]*\"input_i\"[^{}]*\}", m).group(0))
    gain = min(TARGET_LUFS - float(st["input_i"]), MAX_TP - float(st["input_tp"]))
    out = os.path.join(a.out, "voice_cut.wav")
    run([FFMPEG, "-y", "-v", "error", "-i", raw, "-af", f"volume={gain:.2f}dB,atrim=end_sample={nsamp}",
         "-ar", str(SR), "-c:a", "pcm_s16le", out])
    os.remove(raw)
    m2 = run([FFMPEG, "-v", "info", "-i", out, "-af", "loudnorm=print_format=json", "-f", "null", "-"]).stderr
    st2 = json.loads(re.search(r"\{[^{}]*\"input_i\"[^{}]*\}", m2).group(0))

    meta = dict(voice=a.voice, hook_s=hook, cut_s=total, lead_s=LEAD, tail_s=TAIL,
                speech_lufs=float(st2["input_i"]), true_peak_db=float(st2["input_tp"]), lines=rows)
    json.dump(meta, open(os.path.join(a.out, "lines.json"), "w"), indent=1, ensure_ascii=False)
    with open(os.path.join(a.out, "lines.txt"), "w") as f:
        f.write("Creator Scout · demo-cut narration (English)\n")
        f.write(f"Voice: macOS say -v {a.voice} · speech starts {LEAD}s after each cut segment starts, "
                f"ends >= {TAIL}s before it ends\n")
        f.write(f"FULL = full video time = hook ({hook:.2f}s) + cut time, assuming hook, cut, outro are "
                f"butted with no overlap. CUT = time inside cut.mp4 ({total:.2f}s).\n")
        f.write(f"Track: voice_cut.wav, {total:.2f}s, speech {st2['input_i']} LUFS, true peak "
                f"{st2['input_tp']} dBTP. Re-record: read each line inside its FULL window.\n")
        f.write("Say 'Apify' as AY-pih-fy; 'Brno' as BUR-no. '@kamvbrne' is never spoken (on screen).\n\n")
        f.write("%-3s %-17s %-23s %-21s %-21s %4s  %s\n" % ("#", "FULL speech", "FULL shot window",
                                                         "CUT speech", "CUT shot", "rate", "line"))
        for r in rows:
            f.write("%02d  %s-%s  %s-%s  %s-%s  %s-%s  %4d  %s\n" % (
                r["n"], fmt(r["full"][0]), fmt(r["full"][1]),
                fmt(hook + r["shot"][0]), fmt(hook + r["shot"][1]),
                fmt(r["cut"][0]), fmt(r["cut"][1]), fmt(r["shot"][0]), fmt(r["shot"][1]),
                r["rate"], r["text"]))
            f.write("    segment %s · %s · %s\n" % (r["segment"], r["step"], r["label"].upper()))
    if os.path.exists(a.cut):
        run([FFMPEG, "-y", "-v", "error", "-i", a.cut, "-i", out, "-map", "0:v", "-map", "1:a",
             "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-shortest",
             os.path.join(a.out, "cut_with_voice.mp4")])
    print(f"voice_cut.wav {dur(out):.3f}s (cut {total:.3f}s), {st2['input_i']} LUFS, tp {st2['input_tp']} dBTP")


if __name__ == "__main__":
    main()
