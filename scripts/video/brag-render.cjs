// Render the brag hook/outro from brag-timeline.json, frame by frame, in headless Chrome.
// Usage: NODE_PATH=/opt/homebrew/lib/node_modules node scripts/video/brag-render.cjs <hook|outro> [--stills t1,t2,...] [--out DIR]
const puppeteer = require('puppeteer');
const path = require('path');
const fs = require('fs');
const { spawn } = require('child_process');

const args = process.argv.slice(2);
const section = args[0] || 'hook';
const stillsArg = args.includes('--stills') ? args[args.indexOf('--stills') + 1] : null;
const outDir = args.includes('--out') ? args[args.indexOf('--out') + 1] : '/Users/honzik/Developer/creator-scout/demo-output/brag/work';
const tlPath = process.env.BRAG_TIMELINE || path.join(__dirname, 'brag-timeline.json');
const tl = JSON.parse(fs.readFileSync(tlPath, 'utf8'));
if (process.env.BRAG_FOOTAGE) tl.footage_dir = process.env.BRAG_FOOTAGE;
const fps = tl.fps || 30;
const dur = tl[section].duration;

(async () => {
  fs.mkdirSync(outDir, { recursive: true });
  const browser = await puppeteer.launch({ headless: true, args: ['--allow-file-access-from-files', '--force-color-profile=srgb', '--font-render-hinting=none'] });
  const page = await browser.newPage();
  await page.setViewport({ width: 1920, height: 1080, deviceScaleFactor: 1 });
  await page.goto('file://' + path.join(__dirname, 'brag-scene.html'), { waitUntil: 'networkidle0' });
  await page.evaluate(() => document.fonts.ready);
  await page.evaluate((tl, s) => window.setup(tl, s), tl, section);
  // wait for every crop image to be decoded
  await page.evaluate(async () => {
    const urls = [...document.querySelectorAll('.crop')].map(e => getComputedStyle(e).backgroundImage.slice(5, -2));
    await Promise.all(urls.map(u => new Promise(r => { const i = new Image(); i.onload = i.onerror = r; i.src = u; })));
    await document.fonts.ready;
  });
  if (stillsArg) {
    for (const t of stillsArg.split(',').map(Number)) {
      await page.evaluate(t => window.render(t), t);
      await page.screenshot({ path: path.join(outDir, `${section}-still-${t.toFixed(2)}.png`) });
    }
    await browser.close();
    return;
  }
  const out = path.join(outDir, `${section}-video.mp4`);
  const ff = spawn('/opt/homebrew/bin/ffmpeg', ['-y', '-loglevel', 'error', '-f', 'image2pipe', '-framerate', String(fps), '-c:v', 'png', '-i', '-',
    '-c:v', 'libx264', '-preset', 'medium', '-crf', '15', '-pix_fmt', 'yuv420p', '-r', String(fps), '-movflags', '+faststart', out], { stdio: ['pipe', 'inherit', 'inherit'] });
  const n = Math.round(dur * fps);
  for (let f = 0; f < n; f++) {
    await page.evaluate(t => window.render(t), f / fps);
    const buf = await page.screenshot({ type: 'png' });
    if (!ff.stdin.write(buf)) await new Promise(r => ff.stdin.once('drain', r));
  }
  ff.stdin.end();
  await new Promise(r => ff.on('close', r));
  await browser.close();
  console.log(out, n, 'frames');
})().catch(e => { console.error(e); process.exit(1); });
