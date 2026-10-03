"""Re-cut the recorded demo from its existing frames, without re-recording.

    python tools/video/remaster.py                       # -> var/video/sentinel_sih_demo_no_voice.mp4
    python tools/video/remaster.py --only 01-problem     # redo one section, re-join all

What it changes, and nothing else:
  * no voice track (captions stay, timed exactly as before);
  * the section chip at the top right loses its "05/14" count: the chip keeps
    its size and the original title glyphs are re-centred inside it.

The landing-page flicker (the header line blinking while the page scrolled) is
fixed at the source, not here: the site's `scroll-behavior: smooth` fought the
recorder's scripted scroll. make_video.py now turns it off while recording, and
sections 01 and 02 were re-recorded with `--chip-count` so this script treats
them exactly like the others.

Frames are read from var/video/sections/*/frames and written to frames_clean;
the originals are not modified.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent))
from make_video import FFMPEG, FPS, H, OUT, W  # noqa: E402
import narration as N  # noqa: E402


def chip_geometry(img: np.ndarray) -> dict:
    """Locate the chip (neutral dark pill, top right), its count and its title text."""
    rgb = img.astype(int)
    r, g, b = rgb[..., 0], rgb[..., 1], rgb[..., 2]
    neutral_dark = (np.maximum(np.maximum(r, g), b) < 110) & (abs(r - g) < 14) & (abs(g - b) < 14)
    band = neutral_dark[20:50, 1000:W]
    cols = np.where(band.sum(axis=0) >= 8)[0] + 1000
    # contiguous run ending at the right edge of the chip
    right = cols.max()
    left = right
    for c in cols[::-1]:
        if c >= left - 3:
            left = c
        else:
            break
    rows = np.where(neutral_dark[0:90, left + 20:right - 20].mean(axis=1) > 0.3)[0]
    top, bottom = rows.min(), rows.max()
    mid = (top + bottom) // 2
    # text = bright pixels inside the pill (white title, orange count); interior
    # only, because the rounded ends let the page background show at the corners
    bright = rgb[mid - 9:mid + 10, left + 12:right - 11].max(axis=2) > 150
    tcols = np.where(bright.any(axis=0))[0] + left + 12
    # the count ends at the first gap of >= 6 empty columns; the title follows
    ts = tcols[0]
    for a, c in zip(tcols, tcols[1:]):
        if c - a >= 6:
            ts = c
            break
    te = tcols.max()
    trows = np.where((rgb[top + 2:bottom - 1, left + 12:right - 11].max(axis=2) > 150).any(axis=1))[0] + top + 2
    ty0, ty1 = max(int(trows.min()) - 1, top + 5), min(int(trows.max()) + 1, bottom - 5)
    return {"left": int(left), "right": int(right), "top": int(top), "bottom": int(bottom),
            "mid": int(mid), "ts": int(ts), "te": int(te), "ty0": ty0, "ty1": ty1}


def clean_frame(args) -> None:
    src, dst, geo = args
    a = np.asarray(Image.open(src).convert("RGB")).astype(np.float32)
    L, R = geo["left"], geo["right"]
    ts, te, y0, y1 = geo["ts"], geo["te"], geo["ty0"], geo["ty1"]
    x0, x1 = L + 12, R - 11
    # 1. erase the text band: per column, blend the chip background just above and
    #    just below the text line, so whatever shows through the chip keeps its shape
    up = np.median(a[y0 - 4:y0, x0:x1], axis=0)
    dn = np.median(a[y1 + 1:y1 + 5, x0:x1], axis=0)
    k = np.linspace(0, 1, y1 - y0 + 1, dtype=np.float32)[:, None, None]
    bg = up[None] * (1 - k) + dn[None] * k
    # 2. lift the original title glyphs (white) as an alpha mask against that background
    c0, c1 = ts - 2 - x0, te + 3 - x0
    orig = a[y0:y1 + 1, ts - 2:te + 3].max(axis=2)
    base = bg[:, c0:c1].max(axis=2)
    alpha = np.clip((orig - base) / np.maximum(255 - base, 1), 0, 1)[..., None]
    out = a.copy()
    out[y0:y1 + 1, x0:x1] = bg
    # 3. put the title back, centred in the unchanged pill
    w = c1 - c0
    nx = L + ((R - L) - w) // 2 + 1
    dest = out[y0:y1 + 1, nx:nx + w]
    out[y0:y1 + 1, nx:nx + w] = dest * (1 - alpha) + 255 * alpha
    Image.fromarray(np.clip(out, 0, 255).astype(np.uint8)).save(dst, quality=93)


def section(sid: str, pool: ProcessPoolExecutor) -> Path:
    d = OUT / "sections" / sid
    meta = json.loads((d / "rec.json").read_text(encoding="utf-8"))
    frames = meta["frames"]
    probe = next(n for t, n in frames if t >= 1.0)
    geo = chip_geometry(np.asarray(Image.open(d / "frames" / probe).convert("RGB")))
    outdir = d / "frames_clean"
    outdir.mkdir(exist_ok=True)
    for old in outdir.glob("*.jpg"):
        old.unlink()
    list(pool.map(clean_frame, [(d / "frames" / n, outdir / n, geo) for _, n in frames], chunksize=16))
    total = meta["video_s"]
    lines = []
    for i, (t, name) in enumerate(frames):
        start = 0.0 if i == 0 else t
        nxt = frames[i + 1][0] if i + 1 < len(frames) else total
        lines.append(f"file 'frames_clean/{name}'\nduration {max(nxt - start, 0.001):.4f}")
    lines.append(f"file 'frames_clean/{frames[-1][1]}'")
    (d / "frames_clean.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    out = d / "section_no_voice.mp4"
    subprocess.run(
        [FFMPEG, "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", "frames_clean.txt",
         "-vf", f"fps={FPS},scale={W}:{H}:flags=lanczos,setsar=1,format=yuv420p,subtitles=captions.ass,"
                f"fade=t=in:st=0:d=0.35",
         "-t", f"{total:.3f}", "-an", "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-r", str(FPS),
         out.name], cwd=d, check=True)
    print(f"  {sid}: chip x {geo['left']}-{geo['right']}, title from x {geo['ts']}", flush=True)
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", nargs="*", default=None, help="sections to rebuild; the rest are reused")
    a = ap.parse_args()
    ids = [s["id"] for s in N.SECTIONS]
    parts = []
    with ProcessPoolExecutor() as pool:
        for i in ids:
            done = OUT / "sections" / i / "section_no_voice.mp4"
            parts.append(section(i, pool) if (not a.only or i in a.only or not done.exists()) else done)
    lst = OUT / "sections" / "all_no_voice.txt"
    lst.write_text("".join(f"file '{p.parent.name}/{p.name}'\n" for p in parts), encoding="utf-8")
    final = OUT / "sentinel_sih_demo_no_voice.mp4"
    subprocess.run([FFMPEG, "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", lst.name,
                    "-c", "copy", "-movflags", "+faststart", str(final)], cwd=lst.parent, check=True)
    print("video:", final)


if __name__ == "__main__":
    main()
