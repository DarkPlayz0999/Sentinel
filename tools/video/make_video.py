"""Record the SIH demo video from the running product.

    python tools/video/make_video.py                  # tts + record + assemble
    python tools/video/make_video.py --only 05-lab    # re-record one section
    python tools/video/make_video.py --stage assemble # re-assemble only

Needs: the API on :8000 and the web console on :3000 (start_app.ps1), Chrome,
ffmpeg on PATH (or SENTINEL_FFMPEG), and `pip install edge-tts websockets`.

Pipeline, per section of narration.py:
  1. edge-tts speaks the narration (mp3) and returns sentence timings, which
     become burned-in captions (ASS).
  2. Chrome (headless, driven over DevTools) opens the page, then a screencast
     records while the section's actions run: a visible cursor moves to each
     control and clicks it with a real mouse event.
  3. ffmpeg turns the timestamped frames into video, lays the voice and the
     captions over it, and joins the sections.

Nothing on screen is staged: every click runs the real service.
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

import websockets

sys.path.insert(0, str(Path(__file__).resolve().parent))
import narration as N  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "var" / "video"
W, H = 1600, 900
FPS = 25
CHROME = os.environ.get("SENTINEL_CHROME", r"C:\Program Files\Google\Chrome\Application\chrome.exe")
FFMPEG = os.environ.get("SENTINEL_FFMPEG") or shutil.which("ffmpeg") or str(
    Path.home() / "AppData/Local/Microsoft/WinGet/Links/ffmpeg.exe")
FFPROBE = str(Path(FFMPEG).with_name("ffprobe" + Path(FFMPEG).suffix))
PRE_WAIT = {"05-lab": 5, "13-agents": 6, "03-results": 8, "14-close": 6}


# ------------------------------------------------------------------ 1. voice

async def tts(sec: dict, d: Path) -> None:
    import edge_tts
    comm = edge_tts.Communicate(sec["say"], N.VOICE, rate=N.RATE, boundary="SentenceBoundary")
    sents = []
    with open(d / "voice.mp3", "wb") as f:
        async for ch in comm.stream():
            if ch["type"] == "audio":
                f.write(ch["data"])
            elif ch["type"] == "SentenceBoundary":
                sents.append({"t": ch["offset"] / 1e7, "d": ch["duration"] / 1e7, "text": ch["text"]})
    (d / "sentences.json").write_text(json.dumps(sents, indent=1), encoding="utf-8")


def duration(path: Path) -> float:
    r = subprocess.run([FFPROBE, "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0",
                        str(path)], capture_output=True, text=True, check=True)
    return float(r.stdout.strip())


def ass_time(t: float) -> str:
    cs = int(round(t * 100))
    return f"{cs // 360000}:{cs // 6000 % 60:02d}:{cs // 100 % 60:02d}.{cs % 100:02d}"


def captions(d: Path, title: str, index: int, total: int) -> None:
    """Sentence timings -> short caption lines (<= 12 words), time split by length."""
    sents = json.loads((d / "sentences.json").read_text(encoding="utf-8"))
    lines = []
    for s in sents:
        words = s["text"].split()
        chunks, cur = [], []
        for w in words:
            cur.append(w)
            if len(cur) >= 12 or (len(cur) >= 7 and w.endswith((",", ";", ":"))):
                chunks.append(cur); cur = []
        if cur:
            if chunks and len(cur) <= 3:
                chunks[-1] += cur
            else:
                chunks.append(cur)
        total_chars = sum(len(" ".join(c)) for c in chunks) or 1
        t = s["t"]
        for c in chunks:
            txt = " ".join(c)
            dt = s["d"] * len(txt) / total_chars
            lines.append((t, t + dt, txt))
            t += dt
    head = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {W}
PlayResY: {H}
WrapStyle: 0

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Cap,Segoe UI,34,&H00FFFFFF,&H00FFFFFF,&H00000000,&H64101418,1,0,0,0,100,100,0,0,3,14,0,2,160,160,34,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    ev = [f"Dialogue: 0,{ass_time(a)},{ass_time(b)},Cap,,0,0,0,,{t.replace('{', '(').replace('}', ')')}"
          for a, b, t in lines]
    (d / "captions.ass").write_text(head + "\n".join(ev) + "\n", encoding="utf-8")


# -------------------------------------------------------------- 2. browser

OVERLAY_JS = r"""
(() => {
  if (window.__v) return;
  // The site scrolls smoothly by CSS; that fights the scripted glide below and makes
  // frames jump back to the top of the page (the landing header blinked). Off while recording.
  const css = `
  html,body{scroll-behavior:auto!important}
  #__vo{position:fixed;inset:0;pointer-events:none;z-index:2147483647;font-family:'Segoe UI',system-ui,sans-serif}
  #__vo .cur{position:absolute;left:0;top:0;width:30px;height:30px;transform:translate(800px,450px);
     transition:transform 700ms cubic-bezier(.45,.05,.25,1);filter:drop-shadow(0 2px 3px rgba(0,0,0,.45))}
  #__vo .rip{position:absolute;width:18px;height:18px;margin:-9px 0 0 -9px;border-radius:50%;
     border:3px solid #E0782F;animation:__rip 650ms ease-out forwards}
  @keyframes __rip{from{transform:scale(.4);opacity:1}to{transform:scale(3.2);opacity:0}}
  #__vo .chip{position:absolute;top:14px;right:18px;padding:8px 16px;border-radius:999px;
     background:rgba(16,20,24,.86);color:#fff;font-size:17px;font-weight:700;letter-spacing:.2px;
     box-shadow:0 4px 14px rgba(0,0,0,.25);opacity:0;transition:opacity 500ms}
  #__vo .chip b{color:#E0782F;margin-right:10px;font-weight:800}`;
  function ensure() {
    let root = document.getElementById('__vo');
    if (root) return root;
    const st = document.createElement('style'); st.textContent = css;
    root = document.createElement('div'); root.id = '__vo';
    root.innerHTML = `<div class="chip"></div><svg class="cur" viewBox="0 0 24 24"><path d="M3 2l7.2 19 2.6-7.6L20.5 11z" fill="#fff" stroke="#111" stroke-width="1.6" stroke-linejoin="round"/></svg>`;
    document.documentElement.appendChild(st); document.documentElement.appendChild(root);
    const p = window.__pos || [W0 / 2, H0 / 2];
    root.querySelector('.cur').style.transition = 'none';
    root.querySelector('.cur').style.transform = `translate(${p[0]}px,${p[1]}px)`;
    return root;
  }
  const W0 = innerWidth, H0 = innerHeight;
  const vis = (el) => { const r = el.getBoundingClientRect(); if (!r.width || !r.height) return false;
    const s = getComputedStyle(el); return s.visibility !== 'hidden' && s.display !== 'none' && s.opacity !== '0'; };
  const norm = (t) => (t || '').replace(/\s+/g, ' ').trim().toLowerCase();
  function find(q, exact) {
    if (q.startsWith('#') || q.includes('[')) return document.querySelector(q);
    const want = norm(q); let best = null, score = 1e12;
    for (const el of document.querySelectorAll('button,a,[role=tab],[role=button],summary,label,h1,h2,h3,h4,p,span,div,li,td,th,strong')) {
      if (el.closest('#__vo')) continue;
      const t = norm(el.innerText); if (!t) continue;
      if (exact ? t !== want : !t.includes(want)) continue;
      if (!vis(el)) continue;
      const inter = el.matches('button,a,[role=tab],[role=button],summary') ? 0 : 1;
      const s = inter * 1e9 + t.length;
      if (s < score) { score = s; best = el; }
    }
    return best;
  }
  function scroller() {
    const se = document.scrollingElement;
    if (se.scrollHeight > se.clientHeight + 10) return se;
    let best = se, area = 0;
    for (const el of document.querySelectorAll('main,div,section')) {
      const s = getComputedStyle(el);
      if (!/(auto|scroll)/.test(s.overflowY) || el.scrollHeight <= el.clientHeight + 10) continue;
      const a = el.clientWidth * el.clientHeight; if (a > area) { area = a; best = el; }
    }
    return best;
  }
  function glide(sc, target, ms) {
    return new Promise((res) => {
      const from = sc.scrollTop, max = sc.scrollHeight - sc.clientHeight;
      const to = Math.max(0, Math.min(max, target)); const t0 = performance.now();
      const step = (now) => { const k = Math.min(1, (now - t0) / ms); const e = k < .5 ? 2*k*k : 1 - Math.pow(-2*k + 2, 2) / 2;
        sc.scrollTop = from + (to - from) * e; if (k < 1) requestAnimationFrame(step); else res(to); };
      requestAnimationFrame(step);
    });
  }
  window.__v = {
    ensure,
    title(txt, n) { const c = ensure().querySelector('.chip'); c.innerHTML = n ? `<b>${n}</b>${txt}` : txt; c.style.opacity = 1; },
    move(x, y, ms) { window.__pos = [x, y]; const c = ensure().querySelector('.cur');
      c.style.transition = `transform ${ms}ms cubic-bezier(.45,.05,.25,1)`; c.style.transform = `translate(${x - 3}px,${y - 2}px)`; },
    ripple(x, y) { const r = document.createElement('div'); r.className = 'rip'; r.style.left = x + 'px'; r.style.top = y + 'px';
      ensure().appendChild(r); setTimeout(() => r.remove(), 700); },
    async locate(q, exact) {
      const el = find(q, exact); if (!el) return null; window.__el = el;
      const r0 = el.getBoundingClientRect();
      if (r0.top < 70 || r0.bottom > innerHeight - 90) {
        const sc = scroller(); await glide(sc, sc.scrollTop + r0.top - innerHeight / 2 + r0.height / 2, 900);
      }
      const r = el.getBoundingClientRect();
      return [r.left + Math.min(r.width / 2, 120), r.top + r.height / 2];
    },
    where() { const el = window.__el || window.__sel; if (!el || !el.isConnected) return null;
      const r = el.getBoundingClientRect(); return [r.left + Math.min(r.width / 2, 120), r.top + r.height / 2]; },
    async to(q, block) {
      const el = find(q, false); if (!el) return false;
      const sc = scroller(); const r = el.getBoundingClientRect();
      const off = block === 'center' ? innerHeight / 2 - r.height / 2 : 84;
      await glide(sc, sc.scrollTop + r.top - off, 1500); return true;
    },
    async scroll(dy, ms) { const sc = scroller(); await glide(sc, sc.scrollTop + dy, ms); return true; },
    async top() { const sc = scroller(); await glide(sc, 0, 1200); return true; },
    locateSelect(label) {
      const want = norm(label);
      for (const s of document.querySelectorAll('select')) {
        const al = norm(s.getAttribute('aria-label'));
        const lab = s.closest('label'); const lt = lab ? norm((lab.innerText || '').split('\n')[0]) : '';
        if (al.includes(want) || lt.startsWith(want)) {
          s.scrollIntoView({ block: 'nearest' }); window.__sel = s; window.__el = s;
          const r = s.getBoundingClientRect(); return [r.left + Math.min(r.width / 2, 120), r.top + r.height / 2];
        }
      }
      return null;
    },
    choose(opt) {
      const s = window.__sel; if (!s) return false; const want = norm(opt);
      const o = [...s.options].find((o) => norm(o.text).includes(want)); if (!o) return false;
      Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, 'value').set.call(s, o.value);
      s.dispatchEvent(new Event('change', { bubbles: true })); return o.text;
    },
    async type(css, text) {
      const el = document.querySelector(css); if (!el) return false; el.focus();
      const set = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set;
      for (let i = 1; i <= text.length; i++) { set.call(el, text.slice(0, i)); el.dispatchEvent(new Event('input', { bubbles: true }));
        await new Promise((r) => setTimeout(r, 90)); }
      return true;
    },
  };
  addEventListener('load', () => setTimeout(ensure, 1200));
})();
"""


class Browser:
    def __init__(self) -> None:
        self.n = 0
        self.pending: dict[int, asyncio.Future] = {}
        self.frames: list[tuple[float, Path]] | None = None
        self.frame_dir: Path | None = None
        self.errors: list[str] = []
        self.load_event = asyncio.Event()

    async def start(self) -> None:
        self.prof = tempfile.mkdtemp(prefix="sentinel_video_")
        port = 9344
        self.proc = subprocess.Popen(
            [CHROME, "--headless=new", f"--remote-debugging-port={port}", f"--user-data-dir={self.prof}",
             "--use-angle=swiftshader", "--enable-unsafe-swiftshader", "--ignore-gpu-blocklist",
             f"--window-size={W},{H}", "--hide-scrollbars", "--force-device-scale-factor=1",
             "--autoplay-policy=no-user-gesture-required", "about:blank"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        for _ in range(80):
            try:
                tabs = json.load(urllib.request.urlopen(f"http://127.0.0.1:{port}/json"))
                page = next(t for t in tabs if t["type"] == "page")
                break
            except Exception:
                await asyncio.sleep(0.25)
        self.ws = await websockets.connect(page["webSocketDebuggerUrl"], max_size=2**28)
        self.reader = asyncio.create_task(self._read())
        await self.cmd("Page.enable")
        await self.cmd("Runtime.enable")
        await self.cmd("Emulation.setDeviceMetricsOverride", width=W, height=H, deviceScaleFactor=1, mobile=False)
        await self.cmd("Page.addScriptToEvaluateOnNewDocument", source=OVERLAY_JS)

    async def _read(self) -> None:
        async for raw in self.ws:
            m = json.loads(raw)
            if "id" in m:
                fut = self.pending.pop(m["id"], None)
                if fut and not fut.done():
                    fut.set_result(m)
                continue
            meth = m.get("method")
            if meth == "Page.screencastFrame":
                p = m["params"]
                asyncio.create_task(self.cmd("Page.screencastFrameAck", sessionId=p["sessionId"]))
                if self.frames is not None and self.frame_dir is not None:
                    f = self.frame_dir / f"f{len(self.frames):06d}.jpg"
                    f.write_bytes(base64.b64decode(p["data"]))
                    self.frames.append((time.perf_counter(), f))
            elif meth == "Page.loadEventFired":
                self.load_event.set()
            elif meth == "Runtime.exceptionThrown":
                d = m["params"]["exceptionDetails"]
                self.errors.append((d.get("exception", {}).get("description") or d.get("text", ""))[:300])

    async def cmd(self, method: str, **params) -> dict:
        self.n += 1
        my = self.n
        fut = asyncio.get_running_loop().create_future()
        self.pending[my] = fut
        await self.ws.send(json.dumps({"id": my, "method": method, "params": params}))
        m = await asyncio.wait_for(fut, 90)
        if "error" in m:
            raise RuntimeError(f"{method}: {m['error']}")
        return m.get("result", {})

    async def js(self, expr: str):
        r = await self.cmd("Runtime.evaluate", expression=expr, awaitPromise=True, returnByValue=True)
        if "exceptionDetails" in r:
            raise RuntimeError(r["exceptionDetails"].get("exception", {}).get("description", "js error"))
        return r.get("result", {}).get("value")

    async def goto(self, url: str) -> None:
        self.load_event.clear()
        await self.cmd("Page.navigate", url=url)
        try:
            await asyncio.wait_for(self.load_event.wait(), 30)
        except asyncio.TimeoutError:
            pass

    async def mouse_to(self, x: float, y: float, ms: int = 750) -> None:
        await self.js(f"__v.move({x},{y},{ms})")
        await asyncio.sleep(ms / 1000 + 0.12)
        await self.cmd("Input.dispatchMouseEvent", type="mouseMoved", x=x, y=y)

    async def click_at(self, x: float, y: float) -> None:
        await self.mouse_to(x, y)
        # the page may have moved while the cursor travelled: aim at where the control is now
        for _ in range(3):
            now = await self.js("__v.where()")
            if not now or (abs(now[0] - x) < 6 and abs(now[1] - y) < 6):
                break
            x, y = now
            await self.mouse_to(x, y, 260)
        await self.js(f"__v.ripple({x},{y})")
        for t in ("mousePressed", "mouseReleased"):
            await self.cmd("Input.dispatchMouseEvent", type=t, x=x, y=y, button="left", clickCount=1)
        await asyncio.sleep(0.25)

    async def start_rec(self, d: Path) -> None:
        self.frame_dir = d / "frames"
        shutil.rmtree(self.frame_dir, ignore_errors=True)
        self.frame_dir.mkdir(parents=True)
        self.frames = []
        await self.cmd("Page.startScreencast", format="jpeg", quality=88, maxWidth=W, maxHeight=H, everyNthFrame=1)

    async def stop_rec(self) -> list[tuple[float, Path]]:
        await self.cmd("Page.stopScreencast")
        await asyncio.sleep(0.2)
        fr, self.frames = self.frames or [], None
        return fr

    async def close(self) -> None:
        try:
            await self.ws.close()
        finally:
            self.proc.kill()
            await asyncio.sleep(0.5)
            shutil.rmtree(self.prof, ignore_errors=True)


async def run_action(b: Browser, a: tuple, log: list[str]) -> None:
    kind = a[0]
    if kind == "wait":
        await asyncio.sleep(a[1])
    elif kind in ("click", "clickx"):
        pt = await b.js(f"__v.locate({json.dumps(a[1])},{'true' if kind == 'clickx' else 'false'})")
        if not pt:
            log.append(f"MISSING click target: {a[1]!r}")
            return
        await b.click_at(*pt)
    elif kind == "select":
        pt = await b.js(f"__v.locateSelect({json.dumps(a[1])})")
        if not pt:
            log.append(f"MISSING select: {a[1]!r}")
            return
        await b.click_at(*pt)
        got = await b.js(f"__v.choose({json.dumps(a[2])})")
        if not got:
            log.append(f"MISSING option {a[2]!r} in {a[1]!r}")
    elif kind == "type":
        pt = await b.js(f"(() => {{ const e = document.querySelector({json.dumps(a[1])}); if (!e) return null;"
                        f" const r = e.getBoundingClientRect(); return [r.left + 60, r.top + r.height / 2]; }})()")
        if not pt:
            log.append(f"MISSING input {a[1]!r}")
            return
        await b.js(f"window.__el = document.querySelector({json.dumps(a[1])}); true")
        await b.click_at(*pt)
        await b.js(f"__v.type({json.dumps(a[1])},{json.dumps(a[2])})")
    elif kind == "scroll":
        await b.js(f"__v.scroll({a[1]},{a[2]})")
    elif kind == "to":
        ok = await b.js(f"__v.to({json.dumps(a[1])},{json.dumps(a[2])})")
        if not ok:
            log.append(f"MISSING scroll target {a[1]!r}")
    elif kind == "top":
        await b.js("__v.top()")
    elif kind == "js":
        await b.js(a[1])
    elif kind == "until":
        t0 = time.perf_counter()
        while time.perf_counter() - t0 < a[2]:
            if await b.js(a[1]):
                return
            await asyncio.sleep(0.5)
        log.append(f"TIMEOUT waiting for {a[1]!r}")
    else:
        raise ValueError(kind)


async def record(b: Browser, sec: dict, d: Path, n: int, total: int, count: bool = False) -> None:
    audio = duration(d / "voice.mp3")
    await b.goto(sec["url"])
    await asyncio.sleep(PRE_WAIT.get(sec["id"], 4))
    await b.js("__v.ensure()")
    # The chip shows no "05/14" count by default. --chip-count restores it, only so a
    # re-recorded section matches frames that remaster.py later strips the count from.
    await b.js(f"__v.title({json.dumps(sec['title'])},{json.dumps(f'{n:02d}/{total}' if count else '')})")
    await b.mouse_to(W * 0.62, H * 0.55, 10)
    log: list[str] = []
    await b.start_rec(d)
    t0 = time.perf_counter()
    for a in sec["actions"]:
        try:
            await run_action(b, a, log)
        except Exception as e:   # keep recording; the log says what failed
            log.append(f"ERROR {a!r}: {e}")
    remain = audio + 0.9 - (time.perf_counter() - t0)
    if remain > 0:
        await asyncio.sleep(remain)
    t_end = time.perf_counter()
    frames = await b.stop_rec()
    meta = {"t0": t0, "t_end": t_end, "audio_s": audio, "video_s": t_end - t0,
            "frames": [(t - t0, f.name) for t, f in frames], "log": log, "js_errors": b.errors[-5:]}
    b.errors.clear()
    (d / "rec.json").write_text(json.dumps(meta, indent=1), encoding="utf-8")
    print(f"  {sec['id']}: audio {audio:.1f}s video {t_end - t0:.1f}s frames {len(frames)}"
          + (f"  !! {log}" if log else ""), flush=True)


# ---------------------------------------------------------------- 3. video

def assemble_section(d: Path) -> Path:
    meta = json.loads((d / "rec.json").read_text(encoding="utf-8"))
    frames = meta["frames"]
    total = meta["video_s"]
    lines = []
    for i, (t, name) in enumerate(frames):
        start = 0.0 if i == 0 else t
        nxt = frames[i + 1][0] if i + 1 < len(frames) else total
        lines.append(f"file 'frames/{name}'\nduration {max(nxt - start, 0.001):.4f}")
    lines.append(f"file 'frames/{frames[-1][1]}'")
    (d / "frames.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    out = d / "section.mp4"
    subprocess.run(
        [FFMPEG, "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", "frames.txt", "-i", "voice.mp3",
         "-filter_complex",
         f"[0:v]fps={FPS},scale={W}:{H}:flags=lanczos,setsar=1,format=yuv420p,subtitles=captions.ass,"
         f"fade=t=in:st=0:d=0.35[v];[1:a]apad,aresample=48000[a]",
         "-map", "[v]", "-map", "[a]", "-t", f"{total:.3f}",
         "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-r", str(FPS),
         "-c:a", "aac", "-b:a", "160k", "-ac", "2", "section.mp4"],
        cwd=d, check=True)
    return out


def assemble(ids: list[str]) -> Path:
    parts = [assemble_section(OUT / "sections" / i) for i in ids]
    lst = OUT / "sections" / "all.txt"
    lst.write_text("".join(f"file '{p.parent.name}/{p.name}'\n" for p in parts), encoding="utf-8")
    final = OUT / "sentinel_sih_demo.mp4"
    subprocess.run([FFMPEG, "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", "all.txt",
                    "-c", "copy", "-movflags", "+faststart", str(final)], cwd=lst.parent, check=True)
    # Same picture with Opus audio: VS Code's preview (and other players without an
    # AAC decoder) play the AAC file silently.
    subprocess.run([FFMPEG, "-y", "-loglevel", "error", "-i", str(final), "-map", "0:v", "-map", "0:a",
                    "-c:v", "copy", "-c:a", "libopus", "-b:a", "128k", "-movflags", "+faststart",
                    str(final.with_name(final.stem + "_opus.mp4"))], check=True)
    return final


# ------------------------------------------------------------------ script

def write_script() -> Path:
    out = ROOT / "tools" / "video" / "script.md"
    words = sum(len(s["say"].split()) for s in N.SECTIONS)
    rows = [f"# SENTINEL: SIH demo video script\n",
            f"Voice: `{N.VOICE}` at rate `{N.RATE}` (Microsoft Edge neural TTS). "
            f"{len(N.SECTIONS)} sections, {words} words, about {words / 150:.1f} minutes of speech.\n",
            "Every figure spoken below was read off the running product or its evaluation files; "
            "the source is noted under each section. Generated from `tools/video/narration.py` "
            "by `tools/video/make_video.py`.\n"]
    for i, s in enumerate(N.SECTIONS, 1):
        acts = []
        for a in s["actions"]:
            k = a[0]
            if k in ("click", "clickx"):
                acts.append(f"click **{a[1]}**")
            elif k == "select":
                acts.append(f"choose **{a[2]}** in *{a[1]}*")
            elif k == "type":
                acts.append(f"type `{a[2]}`")
            elif k == "to":
                acts.append(f"scroll to *{a[1]}*")
            elif k == "until":
                acts.append("wait for the live result")
        rows.append(f"\n## {i:02d}. {s['title']}\n\nScreen: `{s['url'].replace(N.WEB, '') or '/'}`"
                    + (f". On screen: {'; '.join(acts)}." if acts else ".") + f"\n\n> {s['say']}\n"
                    + (f"\nSource: {N.SOURCES[s['id']]}\n" if s["id"] in getattr(N, "SOURCES", {}) else ""))
    out.write_text("\n".join(rows), encoding="utf-8")
    return out


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--stage", choices=["all", "tts", "record", "assemble", "script"], default="all")
    ap.add_argument("--only", nargs="*", default=None)
    ap.add_argument("--chip-count", action="store_true", help="show the 05/14 count on the section chip")
    a = ap.parse_args()
    ids = [s["id"] for s in N.SECTIONS]
    todo = [s for s in N.SECTIONS if not a.only or s["id"] in a.only]
    print("script:", write_script())
    if a.stage == "script":
        return
    if a.stage in ("all", "tts"):
        for s in todo:
            d = OUT / "sections" / s["id"]
            d.mkdir(parents=True, exist_ok=True)
            await tts(s, d)
            captions(d, s["title"], ids.index(s["id"]) + 1, len(ids))
            print(f"  tts {s['id']}: {duration(d / 'voice.mp3'):.1f}s", flush=True)
    if a.stage in ("all", "record"):
        b = Browser()
        await b.start()
        try:
            for s in todo:
                await record(b, s, OUT / "sections" / s["id"], ids.index(s["id"]) + 1, len(ids), a.chip_count)
        finally:
            await b.close()
    if a.stage in ("all", "assemble"):
        final = assemble(ids)
        print(f"video: {final}  ({duration(final) / 60:.2f} min)")


if __name__ == "__main__":
    asyncio.run(main())
