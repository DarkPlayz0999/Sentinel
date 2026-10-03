"""Serve the static web console build (web/out) with clean URLs.

    cd web && npm run build          # writes web/out (output: "export")
    python tools/serve_web.py        # http://localhost:3000

`next start` does not serve an `output: "export"` build. This maps
/console/lab to console/lab.html the way a static host would, with no extra
dependency. For development use `npm run dev` instead.
"""

from __future__ import annotations

import argparse
import functools
import http.server
from pathlib import Path

OUT = Path(__file__).resolve().parents[1] / "web" / "out"


class CleanURLHandler(http.server.SimpleHTTPRequestHandler):
    def translate_path(self, path: str) -> str:
        p = super().translate_path(path)
        fp = Path(p)
        # /console is both console.html and a folder of sub-pages: the page wins.
        if (not fp.exists() or fp.is_dir()) and fp.with_suffix(".html").exists():
            return str(fp.with_suffix(".html"))
        if fp.is_dir() and (fp / "index.html").exists():
            return str(fp / "index.html")
        return p

    def log_message(self, *args) -> None:   # quiet
        pass


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=3000)
    a = ap.parse_args()
    if not OUT.exists():
        raise SystemExit("web/out not found: run `npm run build` in web/ first")
    handler = functools.partial(CleanURLHandler, directory=str(OUT))
    with http.server.ThreadingHTTPServer(("127.0.0.1", a.port), handler) as httpd:
        print(f"serving {OUT} on http://localhost:{a.port}")
        httpd.serve_forever()


if __name__ == "__main__":
    main()
