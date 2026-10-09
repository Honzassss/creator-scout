#!/usr/bin/env python3
"""ElevenLabs narration for the final demo video (replaces the macOS `say` voice).

    lines.json (voice_cut.py) -> one ElevenLabs clip per line, fitted into its shot window
    -> demo-output/voice-el/voice_full.wav (full-video timeline, speech -16 LUFS)
    -> demo-output/final/creator-scout-90s-el.mp4: picture stream-copied from creator-scout-90s-music-only.mp4,
       music re-mixed from the same stems as assemble.py (hook audio, music_bed.wav, outro audio) with the
       bed ducked 9 dB by volume automation re-timed to the NEW lines (the music-only export already carries
       ducking at the old `say` line times, so ducking that again would double-duck), master -14 LUFS,
       true peak <= -1 dBTP after AAC encoding.

Fit rule per line: speech starts 0.3 s after its shot starts and must end within the line's budget
(>= 0.25 s before the shot ends, which is before the next line starts). Leading/trailing silence is
trimmed; if the speech is still too long the clip is regenerated with voice_settings.speed (<= 1.15).
Words are never cut.

Usage (needs python-dotenv + httpx, e.g. the backend venv):
    backend/.venv/bin/python scripts/video/voice_elevenlabs.py --list-voices
    backend/.venv/bin/python scripts/video/voice_elevenlabs.py [--voice-id ID] [--model eleven_multilingual_v2]
    backend/.venv/bin/python scripts/video/voice_elevenlabs.py --mix-only     # re-mix from cached clips
ELEVENLABS_API_KEY is read from .env and is never printed or written anywhere.
Clips are cached in demo-output/voice-el/clips/ by (voice, model, text, speed), so re-runs cost nothing.
"""
import argparse, hashlib, json, math, os, subprocess, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import assemble as A  # noqa: E402  (FFMPEG/FFPROBE, loudness(), dur(), duck_regions(), bed_volume_expr(), constants)

ROOT = A.ROOT
D = A.D
API = "https://api.elevenlabs.io/v1"
OUTFMT = "mp3_44100_128"
SR = A.SR
SPEECH_LUFS = -16.0
SPEED_MIN, SPEED_MAX = 0.9, 1.15
SEED = 1234
VOICE_SETTINGS = {"stability": 0.55, "similarity_boost": 0.75, "style": 0.0, "use_speaker_boost": True}
# TTS respellings (lines.txt: say 'Apify' as AY-pih-fy, 'Brno' as BUR-no)
RESPELL = {"Apify": "Aypify", "Brno": "Burno"}
# voices we prefer, in order, if the account has them as premade (calm, clear narrators)
PREFERRED = ["Matilda", "Sarah", "Alice", "George", "Brian", "Daniel", "Eric", "Jessica"]


def key():
    from dotenv import dotenv_values
    k = (dotenv_values(os.path.join(ROOT, ".env")).get("ELEVENLABS_API_KEY") or "").strip()
    if not k:
        raise SystemExit("ELEVENLABS_API_KEY missing in .env")
    return k


def client():
    import httpx
    return httpx.Client(base_url=API, headers={"xi-api-key": key()}, timeout=120)


def ff(*args, capture=False):
    r = subprocess.run([A.FFMPEG, "-hide_banner", "-y", *args], capture_output=True, text=True)
    if r.returncode != 0:
        sys.stderr.write(r.stderr[-3000:])
        raise SystemExit("ffmpeg failed")
    return r.stderr if capture else None


def list_voices(c):
    r = c.get("/voices")
    r.raise_for_status()
    return r.json()["voices"]


def pick_voice(voices, want=None):
    if want:
        v = next((v for v in voices if v["voice_id"] == want or v["name"].split(" ")[0] == want), None)
        if not v:
            raise SystemExit(f"voice {want} not on the account")
        return v
    premade = [v for v in voices if v.get("category") == "premade"]
    for name in PREFERRED:
        v = next((v for v in premade if v["name"].split(" ")[0].lower() == name.lower()), None)
        if v:
            return v
    return premade[0]


def chars_used(c):
    try:
        r = c.get("/user/subscription")
        r.raise_for_status()
        s = r.json()
        return s.get("character_count"), s.get("character_limit")
    except Exception:
        return None, None


def tts(c, voice_id, model, text, speed, dst):
    body = {"text": text, "model_id": model, "seed": SEED,
            "voice_settings": {**VOICE_SETTINGS, "speed": round(speed, 3)}}
    r = c.post(f"/text-to-speech/{voice_id}", params={"output_format": OUTFMT}, json=body)
    if r.status_code != 200:
        raise SystemExit(f"TTS failed {r.status_code}: {r.text[:300]}")
    open(dst, "wb").write(r.content)
    cc = r.headers.get("x-character-count") or r.headers.get("character-cost")
    return int(cc) if cc and cc.isdigit() else len(text)


def trimmed_wav(src, dst):
    """48 kHz mono float WAV, leading/trailing silence removed (keeps 30 ms before / 120 ms after speech)."""
    sil = "silenceremove=start_periods=1:start_threshold=-50dB:start_silence=0.03:detection=peak"
    ff("-i", src, "-af", f"aresample={SR},aformat=sample_fmts=flt:channel_layouts=mono,"
       f"{sil},areverse,{sil.replace('0.03', '0.12')},areverse", "-c:a", "pcm_f32le", dst)
    return A.dur(dst)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--voice-id")
    ap.add_argument("--model", default="eleven_multilingual_v2")
    ap.add_argument("--lines", default=D("voice", "lines.json"))
    ap.add_argument("--music-only", default=D("final", "creator-scout-90s-music-only.mp4"))
    ap.add_argument("--assembly", default=D("final", "assembly.json"))
    ap.add_argument("--out", default=D("final", "creator-scout-90s-el.mp4"))
    ap.add_argument("--list-voices", action="store_true")
    ap.add_argument("--mix-only", action="store_true", help="use cached clips + voice-el/fit.json, no API calls")
    a = ap.parse_args()

    vdir = D("voice-el")
    cdir = os.path.join(vdir, "clips")
    os.makedirs(cdir, exist_ok=True)
    meta = json.load(open(a.lines))
    tl = json.load(open(a.assembly))
    H = meta["hook_s"]
    lines = meta["lines"]
    total = tl["total_s"]
    fit_path = os.path.join(vdir, "fit.json")

    if a.list_voices:
        c = client()
        for v in list_voices(c):
            lab = v.get("labels") or {}
            print(f'{v["category"]:13s} {v["voice_id"]}  {v["name"]:40.40s} '
                  f'{lab.get("accent", "")}/{lab.get("gender", "")}/{lab.get("age", "")} '
                  f'{lab.get("use_case", "") or lab.get("description", "")}  {lab.get("descriptive", "")}')
        return

    if not a.mix_only:
        c = client()
        voices = list_voices(c)
        cloned = [v["name"] for v in voices if v.get("category") in ("cloned", "professional")]
        v = pick_voice(voices, a.voice_id)
        before, limit = chars_used(c)
        spent = 0
        fit = {"voice": {"name": v["name"], "id": v["voice_id"]}, "model": a.model, "cloned_available": cloned,
               "lines": []}
        for i, ln in enumerate(lines):
            start = ln["shot"][0] + meta["lead_s"]                      # cut time
            end_max = start + ln["budget"]
            if i + 1 < len(lines):
                end_max = min(end_max, lines[i + 1]["shot"][0] + meta["lead_s"] - 0.2)
            budget = end_max - start
            text = ln["text"]
            for k, r in RESPELL.items():
                text = text.replace(k, r)
            speed, tries = 1.0, []
            while True:
                h = hashlib.sha1(f'{v["voice_id"]}|{a.model}|{text}|{speed:.3f}|{SEED}|{VOICE_SETTINGS}'.encode()).hexdigest()[:10]
                mp3 = os.path.join(cdir, f'{ln["n"]:02d}-{h}.mp3')
                wav = mp3[:-4] + ".wav"
                if not os.path.exists(mp3):
                    spent += tts(c, v["voice_id"], a.model, text, speed, mp3)
                d = trimmed_wav(mp3, wav)
                tries.append({"speed": round(speed, 3), "speech_s": round(d, 3)})
                if d <= budget or speed >= SPEED_MAX - 1e-6:
                    break
                speed = min(SPEED_MAX, max(speed + 0.03, speed * d / budget * 1.03))
            fit["lines"].append({"n": ln["n"], "text": ln["text"], "tts_text": text, "wav": os.path.relpath(wav, ROOT),
                                 "speed": round(speed, 3), "speech_s": round(d, 3), "budget_s": round(budget, 3),
                                 "full": [round(H + start, 3), round(H + start + d, 3)],
                                 "fits": d <= budget, "tries": tries})
            print(f'{ln["n"]:02d} speed {speed:.2f} speech {d:5.2f}s / budget {budget:5.2f}s '
                  f'{"ok" if d <= budget else "OVER"}  {ln["text"][:50]}')
        after, _ = chars_used(c)
        fit["characters"] = {"requested": spent, "subscription_before": before, "subscription_after": after,
                             "limit": limit}
        json.dump(fit, open(fit_path, "w"), indent=1, ensure_ascii=False)
    fit = json.load(open(fit_path))

    # overlap check: each line ends before the next starts
    fl = fit["lines"]
    for x, y in zip(fl, fl[1:]):
        if x["full"][1] >= y["full"][0]:
            raise SystemExit(f'line {x["n"]} overlaps line {y["n"]}')

    # --- voice_full.wav: clips placed on the full-video timeline, one gain to SPEECH_LUFS ---
    raw = os.path.join(vdir, "voice_full_raw.wav")
    ins, parts = [], []
    for j, ln in enumerate(fl):
        ins += ["-i", os.path.join(ROOT, ln["wav"])]
        parts.append(f"[{j}:a]aformat=sample_fmts=fltp:channel_layouts=mono,"
                     f"adelay={int(round(ln['full'][0] * 1000))}:all=1[v{j}]")
    parts.append("".join(f"[v{j}]" for j in range(len(fl))) +
                 f"amix=inputs={len(fl)}:normalize=0:duration=longest,apad,atrim=0:{total:.3f},"
                 f"aformat=channel_layouts=stereo[out]")
    ff(*ins, "-filter_complex", ";".join(parts), "-map", "[out]", "-ar", str(SR), "-c:a", "pcm_f32le", raw)
    Lv = A.loudness(raw)
    voice = os.path.join(vdir, "voice_full.wav")
    ff("-i", raw, "-af", f"volume={SPEECH_LUFS - Lv['I']:.3f}dB", "-c:a", "pcm_f32le", voice)
    Lv2 = A.loudness(voice)
    print(f"voice_full.wav {A.dur(voice):.3f}s  speech {Lv2}")

    # --- music re-mixed from the stems with ducking re-timed to the new lines (same levels as assemble.py) ---
    m = tl["music"]
    bed_start, bed_end = m["bed_in"][0], m["bed_out"][1]
    bed_len = round(bed_end - bed_start, 3)
    outro_start = tl["outro"][0]
    regs = A.duck_regions([{"cut": [x["full"][0] - H, x["full"][1] - H]} for x in fl], H, total)
    fmt = f"aresample={SR},aformat=sample_fmts=fltp:channel_layouts=stereo"
    ms = lambda t: int(round(t * 1000))
    parts = [f"[0:a]{fmt},atrim=0:{H:.3f}[ha]",
             f"[2:a]{fmt},atrim=0:{bed_len:.3f},asetpts=PTS-STARTPTS,"
             f"volume='{A.bed_volume_expr(regs, bed_start)}':eval=frame,"
             f"afade=t=in:st=0:d={A.BED_FADE_IN},afade=t=out:st={bed_len - A.BED_FADE_OUT:.3f}:d={A.BED_FADE_OUT},"
             f"adelay={ms(bed_start)}:all=1[ba]",
             f"[3:a]{fmt},adelay={ms(outro_start)}:all=1[oa]",
             f"[1:a]{fmt}[va]",
             f"[ha][ba][oa][va]amix=inputs=4:normalize=0:duration=longest,apad,atrim=0:{total:.3f}[mix]"]
    work = os.path.join(vdir, "work")
    os.makedirs(work, exist_ok=True)
    pre = os.path.join(work, "premix_el.wav")
    src = tl["sources"]
    ff("-i", os.path.join(ROOT, src["hook"]), "-i", voice, "-i", os.path.join(ROOT, src["bed"]),
       "-i", os.path.join(ROOT, src["outro"]), "-filter_complex", ";".join(parts), "-map", "[mix]",
       "-c:a", "pcm_f32le", "-ar", str(SR), pre)
    L0 = A.loudness(pre)
    print(f"pre-master {L0}")

    gain, ceil = A.TARGET_LUFS - L0["I"], A.TP_CEIL
    mst = os.path.join(work, "master_el.wav")
    for attempt in range(5):
        lim = 10 ** (ceil / 20)
        ff("-i", pre, "-af", f"volume={gain:.3f}dB,aresample={SR * 4},"
           f"alimiter=limit={lim:.5f}:attack=3:release=60:level=false,aresample={SR}", "-c:a", "pcm_f32le", mst)
        ff("-i", a.music_only, "-i", mst, "-map", "0:v", "-map", "1:a", "-c:v", "copy", "-c:a", "aac",
           "-b:a", "256k", "-ar", str(SR), "-ac", "2", "-movflags", "+faststart", "-t", f"{total:.3f}", a.out)
        Lf = A.loudness(a.out)
        print(f"  pass {attempt + 1}: gain {gain:+.2f} dB, ceiling {ceil:.1f} -> {Lf}")
        ok_i, ok_tp = abs(Lf["I"] - A.TARGET_LUFS) <= 0.2, Lf["TP"] <= -1.0
        if ok_i and ok_tp:
            break
        if not ok_tp:
            ceil -= 0.5
        if not ok_i:
            gain += A.TARGET_LUFS - Lf["I"]

    fit["mix"] = {"out": os.path.relpath(a.out, ROOT), "duration_s": A.dur(a.out), "loudness": Lf,
                  "voice_speech": Lv2, "pre_master": L0, "master_gain_db": round(gain, 2),
                  "limiter_ceiling_dbfs": ceil, "ducked_regions": regs,
                  "bed_up_db": A.BED_UP_DB, "bed_duck_db": A.BED_DUCK_DB}
    json.dump(fit, open(fit_path, "w"), indent=1, ensure_ascii=False)
    print(json.dumps(fit["mix"], indent=1))


if __name__ == "__main__":
    main()
