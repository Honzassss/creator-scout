// Original music + SFX for the Creator Scout brag hook/outro and a loopable demo bed.
// One key (D major), one tempo (100 BPM), one reverb space. Pure JS synthesis, writes 48 kHz stereo WAV.
// Usage: node scripts/video/brag-music.cjs [outDir]   (reads brag-timeline.json for SFX times)
const fs = require('fs');
const path = require('path');
const OUT = process.argv[2] || '/Users/honzik/Developer/creator-scout/demo-output/brag';
const TL = JSON.parse(fs.readFileSync(path.join(__dirname, 'brag-timeline.json'), 'utf8'));
const SR = 48000, BPM = 100, BEAT = 60 / BPM, BAR = 4 * BEAT;
const mf = m => 440 * Math.pow(2, (m - 69) / 12);
const TAU = Math.PI * 2;

const CH = { // pad voicing, bass, arp tones
  Dmaj9: { pad: [50, 57, 61, 64, 66], bass: 38, arp: [74, 78, 81, 85, 76] },
  Bm9:   { pad: [47, 54, 57, 61, 62], bass: 35, arp: [71, 74, 78, 81, 73] },
  Gmaj7: { pad: [43, 55, 59, 62, 66], bass: 31, arp: [67, 71, 74, 78, 74] },
  Asus4: { pad: [45, 57, 62, 64, 69], bass: 33, arp: [69, 74, 76, 81, 76] },
  A:     { pad: [45, 57, 61, 64, 69], bass: 33, arp: [69, 73, 76, 81, 76] },
  Bm7:   { pad: [47, 54, 57, 62, 66], bass: 35, arp: [71, 74, 78, 81, 78] },
};

function makeBus(N) { return { dL: new Float32Array(N), dR: new Float32Array(N), sL: new Float32Array(N), sR: new Float32Array(N) }; }
let rng = 12345; const rnd = () => { rng = (rng * 1664525 + 1013904223) >>> 0; return rng / 4294967296 * 2 - 1; };

function add(bus, N, loop, t0, len, fn, gain, pan, send) {
  const i0 = Math.round(t0 * SR), n = Math.round(len * SR);
  const gl = gain * Math.cos((pan + 1) * Math.PI / 4), gr = gain * Math.sin((pan + 1) * Math.PI / 4);
  for (let k = 0; k < n; k++) {
    let i = i0 + k; if (loop) i = ((i % N) + N) % N; else if (i < 0 || i >= N) continue;
    const v = fn(k / SR);
    bus.dL[i] += v * gl; bus.dR[i] += v * gr; bus.sL[i] += v * gl * send; bus.sR[i] += v * gr * send;
  }
}
// ---- voices ----
function pad(bus, N, loop, t0, dur, notes, opt = {}) {
  const att = opt.att ?? 0.7, rel = opt.rel ?? 1.0, g = opt.gain ?? 0.05;
  notes.forEach((m, j) => {
    const f = mf(m); const ph = Math.random() * TAU;
    const fn = t => {
      const e = Math.min(1, t / att) * (t > dur ? Math.exp(-(t - dur) / (rel / 3)) : 1);
      let s = 0;
      for (const d of [-0.0023, 0.0023]) { const ff = f * (1 + d);
        s += Math.sin(TAU * ff * t + ph) + 0.32 * Math.sin(2 * TAU * ff * t) + 0.12 * Math.sin(3 * TAU * ff * t) + 0.05 * Math.sin(4 * TAU * ff * t); }
      return 0.5 * s * e * (1 + 0.04 * Math.sin(TAU * 0.23 * t + j));
    };
    add(bus, N, loop, t0, dur + rel, fn, g * (m < 50 ? 0.8 : 1), (j % 2 ? 0.25 : -0.25) * (j / notes.length), 0.35);
  });
}
function bass(bus, N, loop, t0, dur, m, g = 0.22) {
  const f = mf(m);
  add(bus, N, loop, t0, dur + 0.2, t => {
    const e = Math.min(1, t / 0.012) * (0.55 + 0.45 * Math.exp(-t / 0.35)) * (t > dur ? Math.exp(-(t - dur) / 0.06) : 1);
    return (Math.sin(TAU * f * t) + 0.28 * Math.sin(2 * TAU * f * t) + 0.08 * Math.sin(3 * TAU * f * t)) * e;
  }, g, 0, 0.0);
}
function pluck(bus, N, loop, t0, m, g = 0.06, pan = 0, tau = 0.22) {
  const f = mf(m);
  add(bus, N, loop, t0, tau * 6, t => {
    const e = Math.min(1, t / 0.004) * Math.exp(-t / tau);
    return (Math.sin(TAU * f * t) + 0.22 * Math.sin(2 * TAU * f * t) * Math.exp(-t / 0.05) + 0.06 * Math.sin(3 * TAU * f * t) * Math.exp(-t / 0.03)) * e;
  }, g, pan, 0.45);
}
function bell(bus, N, loop, t0, m, g = 0.06, pan = 0) {
  const f = mf(m);
  add(bus, N, loop, t0, 4.0, t => {
    const e = Math.min(1, t / 0.003);
    return e * (Math.sin(TAU * f * t) * Math.exp(-t / 1.4) + 0.35 * Math.sin(TAU * f * 2.756 * t) * Math.exp(-t / 0.5) + 0.12 * Math.sin(TAU * f * 5.404 * t) * Math.exp(-t / 0.18));
  }, g, pan, 0.55);
}
function kick(bus, N, loop, t0, g = 0.32) {
  add(bus, N, loop, t0, 0.5, t => {
    const ph = TAU * (46 * t + 70 * 0.035 * (1 - Math.exp(-t / 0.035)));
    return Math.sin(ph) * Math.exp(-t / 0.14) * Math.min(1, t / 0.002);
  }, g, 0, 0.02);
}
function hat(bus, N, loop, t0, g = 0.018, pan = 0.2) {
  let lp = 0;
  add(bus, N, loop, t0, 0.12, t => { const x = rnd(); lp += 0.35 * (x - lp); return (x - lp) * Math.exp(-t / 0.022); }, g, pan, 0.15);
}
function swish(bus, N, loop, tPeak, g = 0.05) { // filtered-noise swell that peaks on the cut
  const L = 0.5; let lp = 0, lp2 = 0;
  add(bus, N, loop, tPeak - L, L + 0.18, t => {
    const p = t / L; const cut = 0.02 + 0.25 * Math.min(1, p) ** 2;
    const x = rnd(); lp += cut * (x - lp); lp2 += cut * (lp - lp2);
    const e = p < 1 ? p * p : Math.exp(-(t - L) / 0.05);
    return lp2 * e * 3;
  }, g, 0, 0.5);
}
function tick(bus, N, loop, t0, m, g = 0.05, pan = 0.15) {
  const f = mf(m);
  add(bus, N, loop, t0, 0.4, t => Math.min(1, t / 0.002) * (Math.sin(TAU * f * t) * Math.exp(-t / 0.06) + 0.3 * Math.sin(TAU * f * 3.01 * t) * Math.exp(-t / 0.015)), g, pan, 0.6);
}

// ---- reverb (Schroeder/Freeverb-ish), wraps for loops ----
function reverb(inp, N, loop, offs) {
  const combs = [1557, 1617, 1491, 1422, 1277, 1356].map(d => Math.round((d + offs) * SR / 44100));
  const aps = [556, 441, 341].map(d => Math.round((d + offs) * SR / 44100));
  const passes = loop ? 2 : 1; const out = new Float32Array(N);
  const cb = combs.map(d => ({ buf: new Float32Array(d), i: 0, lp: 0 }));
  const ab = aps.map(d => ({ buf: new Float32Array(d), i: 0 }));
  for (let p = 0; p < passes; p++) for (let n = 0; n < N; n++) {
    const x = inp[n] * 0.2; let y = 0;
    for (const c of cb) { const o = c.buf[c.i]; c.lp = o * 0.62 + c.lp * 0.38; c.buf[c.i] = x + c.lp * 0.84; c.i = (c.i + 1) % c.buf.length; y += o; }
    for (const a of ab) { const o = a.buf[a.i]; const v = y + o * -0.5; a.buf[a.i] = v; a.i = (a.i + 1) % a.buf.length; y = o + v * 0.5; }
    if (p === passes - 1) out[n] = y;
  }
  return out;
}
function mixdown(bus, N, loop, opt) {
  const wl = reverb(bus.sL, N, loop, 0), wr = reverb(bus.sR, N, loop, 23);
  const L = new Float32Array(N), R = new Float32Array(N);
  let lp1 = 0, lp2 = 0; const a = 1 - Math.exp(-TAU * 9000 / SR);
  const passes = loop ? 2 : 1;
  for (let p = 0; p < passes; p++) for (let i = 0; i < N; i++) { lp1 += a * (bus.dL[i] + wl[i] * opt.wet - lp1); lp2 += a * (bus.dR[i] + wr[i] * opt.wet - lp2); if (p === passes - 1) { L[i] = lp1; R[i] = lp2; } }
  // loudness: scale to target RMS, gentle tanh limiter, optional fades
  let ss = 0; for (let i = 0; i < N; i++) ss += (L[i] * L[i] + R[i] * R[i]) / 2;
  const rms = Math.sqrt(ss / N), g = Math.pow(10, opt.rmsDb / 20) / rms;
  for (let i = 0; i < N; i++) {
    let f = 1; const t = i / SR;
    if (opt.fadeIn && t < opt.fadeIn) f *= t / opt.fadeIn;
    if (opt.fadeOut && t > opt.dur - opt.fadeOut) f *= Math.max(0, (opt.dur - t) / opt.fadeOut) ** 1.5;
    L[i] = 0.93 * Math.tanh(L[i] * g * f / 0.93); R[i] = 0.93 * Math.tanh(R[i] * g * f / 0.93);
  }
  return [L, R];
}
function writeWav(file, L, R) {
  const N = L.length, buf = Buffer.alloc(44 + N * 4);
  buf.write('RIFF', 0); buf.writeUInt32LE(36 + N * 4, 4); buf.write('WAVE', 8); buf.write('fmt ', 12);
  buf.writeUInt32LE(16, 16); buf.writeUInt16LE(1, 20); buf.writeUInt16LE(2, 22); buf.writeUInt32LE(SR, 24);
  buf.writeUInt32LE(SR * 4, 28); buf.writeUInt16LE(4, 32); buf.writeUInt16LE(16, 34); buf.write('data', 36); buf.writeUInt32LE(N * 4, 40);
  for (let i = 0; i < N; i++) { buf.writeInt16LE(Math.round(Math.max(-1, Math.min(1, L[i])) * 32767), 44 + i * 4); buf.writeInt16LE(Math.round(Math.max(-1, Math.min(1, R[i])) * 32767), 46 + i * 4); }
  fs.writeFileSync(file, buf); console.log(file, (N / SR).toFixed(2) + ' s');
}
// arpeggio helper: notes on a grid between t0 and t1
function arp(bus, N, loop, t0, t1, ch, step, g, pat = [0, 2, 1, 3, 2, 4, 1, 2]) {
  let k = 0; for (let t = t0; t < t1 - 1e-6; t += step, k++) pluck(bus, N, loop, t, CH[ch].arp[pat[k % pat.length]], g, (k % 2 ? 0.3 : -0.3));
}

// ================= BED: 8-bar loop x5 = 96 s, seamless =================
(function bed() {
  const loopBars = [['Dmaj9', 2], ['Bm9', 2], ['Gmaj7', 2], ['Asus4', 1], ['A', 1]];
  const LOOPS = 5, dur = LOOPS * 8 * BAR, N = Math.round(dur * SR), bus = makeBus(N);
  for (let L = 0; L < LOOPS; L++) {
    let t = L * 8 * BAR;
    for (const [c, bars] of loopBars) {
      const len = bars * BAR;
      pad(bus, N, true, t, len, CH[c].pad, { gain: 0.042, att: 0.9, rel: 1.2 });
      for (let b = 0; b < bars; b++) { const tb = t + b * BAR; bass(bus, N, true, tb, BEAT * 1.4, CH[c].bass, 0.16); bass(bus, N, true, tb + 2.5 * BEAT, BEAT * 1.2, CH[c].bass, 0.11); kick(bus, N, true, tb, 0.16); kick(bus, N, true, tb + 2 * BEAT, 0.1);
        for (let h = 0; h < 4; h++) hat(bus, N, true, tb + (h + 0.5) * BEAT, 0.008); }
      arp(bus, N, true, t, t + len, c, BEAT / 2, 0.028);
      t += len;
    }
  }
  const [Lc, Rc] = mixdown(bus, N, true, { wet: 0.4, rmsDb: -24, dur });
  writeWav(path.join(OUT, 'music_bed.wav'), Lc, Rc);
})();

// ================= HOOK =================
function sfxLayer(bus, N, list, chordAt) {
  for (const s of list) {
    const c = chordAt(s.t);
    if (s.type === 'swish') swish(bus, N, false, s.t, 0.035);
    if (s.type === 'tick') tick(bus, N, false, s.t, CH[c].arp[1] + 12, 0.035);
    if (s.type === 'hit') { bell(bus, N, false, s.t, CH[c].arp[0] + 12, 0.05); bass(bus, N, false, s.t, 2.0, CH[c].bass, 0.3); }
    if (s.type === 'bloom') { bell(bus, N, false, s.t, 86, 0.05, -0.2); bell(bus, N, false, s.t + 0.06, 93, 0.035, 0.2); swish(bus, N, false, s.t, 0.03); }
  }
}
(function hook() {
  const H = TL.hook, dur = H.duration, N = Math.round(dur * SR), bus = makeBus(N);
  const B = b => b * BEAT;
  const plan = [ // [chord, startBeat, endBeat, density]
    ['Bm9', 0, 5, 1], ['Gmaj7', 5, 12, 2], ['Asus4', 12, 15, 2], ['A', 15, 18, 2], ['Bm7', 18, 21, 2], ['A', 21, 24, 2], ['Dmaj9', 24, 29, 0],
  ];
  const chordAt = t => { for (const p of plan) if (t >= B(p[1]) - 0.05 && t < B(p[2]) - 0.05) return p[0]; return 'Dmaj9'; };
  for (const [c, b0, b1, dens] of plan) {
    const t0 = B(b0), t1 = B(b1);
    pad(bus, N, false, t0, t1 - t0 + (b1 >= 29 ? 2 : 0), CH[c].pad, { gain: c === 'Dmaj9' ? 0.05 : 0.04, att: b0 === 0 ? 0.03 : 0.35, rel: 0.9 });
    if (dens >= 1) arp(bus, N, false, t0, t1, c, dens === 1 ? BEAT : BEAT / 2, dens === 1 ? 0.03 : 0.034);
    if (b0 >= 5 && b0 < 24) for (let b = b0; b < b1; b++) { if (b % 2 === 1) kick(bus, N, false, B(b), 0.2); hat(bus, N, false, B(b + 0.5), b0 >= 12 ? 0.012 : 0.007); }
    if (b0 > 0) { bass(bus, N, false, t0, (t1 - t0) * 0.55, CH[c].bass, 0.17); if (b1 - b0 >= 3 && b0 < 24) bass(bus, N, false, t0 + 2.5 * BEAT, BEAT, CH[c].bass, 0.11); }
  }
  bass(bus, N, false, B(24), 3.0, 38, 0.2);
  [0, 1, 2, 3].forEach(i => pluck(bus, N, false, B(24) + i * BEAT * 0.5, CH.Dmaj9.arp[i], 0.03, i % 2 ? 0.3 : -0.3, 0.5));
  sfxLayer(bus, N, H.sfx, chordAt);
  const [L, R] = mixdown(bus, N, false, { wet: 0.38, rmsDb: -17.5, dur, fadeOut: 0.9 });
  writeWav(path.join(OUT, 'work', 'hook-music.wav'), L, R);
})();

// ================= OUTRO =================
(function outro() {
  const O = TL.outro, dur = O.duration, N = Math.round(dur * SR), bus = makeBus(N);
  const B = b => b * BEAT;
  pad(bus, N, false, 0, B(2), CH.Gmaj7.pad, { gain: 0.04, att: 0.05, rel: 0.6 });
  bass(bus, N, false, 0, B(1.6), CH.Gmaj7.bass, 0.17);
  arp(bus, N, false, 0, B(2), 'Gmaj7', BEAT / 2, 0.03);
  pad(bus, N, false, B(2), B(2), CH.A.pad, { gain: 0.04, att: 0.2, rel: 0.6 });
  bass(bus, N, false, B(2), B(1.6), CH.A.bass, 0.17);
  arp(bus, N, false, B(2), B(4), 'A', BEAT / 2, 0.03);
  pad(bus, N, false, B(4), dur - B(4), CH.Dmaj9.pad, { gain: 0.05, att: 0.25, rel: 1.5 });
  bass(bus, N, false, B(4), 2.5, 38, 0.2);
  bell(bus, N, false, B(4), 86, 0.05, -0.2); bell(bus, N, false, B(4) + 0.07, 93, 0.035, 0.2);
  swish(bus, N, false, 0.0 + 0.01, 0.02);
  const [L, R] = mixdown(bus, N, false, { wet: 0.42, rmsDb: -17.5, dur, fadeIn: 0.04, fadeOut: 1.6 });
  writeWav(path.join(OUT, 'work', 'outro-music.wav'), L, R);
})();
