#!/usr/bin/env python3
"""Optional helper: serve blernsboard.html together with a log directory.

    python3 serve.py LOGDIR [--port 6006] [--bind 0.0.0.0]

Not required. `python3 -m http.server` inside the logdir works too, once
blernsboard.html is copied there. This helper adds three conveniences:

  * the page is served at / without copying it into the logdir
  * HTTP Range requests, so tailing a growing event file only fetches the tail
  * POST /__log accepts console errors from the page and prints them here,
    so problems seen in a remote browser show up in this terminal
"""
import argparse, json, os, sys, functools
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
PAGE = os.path.join(HERE, "blernsboard.html")


class Handler(SimpleHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def do_GET(self):
        # "/" is both the page (for a browser navigation) and the log root (for the
        # page's own fetch() calls, which send Accept: */*). Navigations ask for HTML.
        wants_page = "text/html" in self.headers.get("Accept", "") and self.headers.get("Sec-Fetch-Dest", "document") == "document"
        if self.path == "/blernsboard.html" or (self.path.split("?")[0] == "/" and wants_page):
            return self.send_file(PAGE)
        return self.send_ranged()

    def do_HEAD(self):
        if self.path == "/__log":
            self.send_response(200)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        super().do_HEAD()

    def do_POST(self):
        if self.path != "/__log":
            self.send_error(404)
            return
        n = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(n)
        try:
            for entry in json.loads(body or b"[]"):
                sys.stderr.write(f"[browser {entry.get('level','log')}] {entry.get('msg','')}\n")
        except Exception as e:
            sys.stderr.write(f"[browser ?] {body[:500]!r} ({e})\n")
        self.send_response(204)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def send_file(self, path):
        try:
            with open(path, "rb") as f:
                data = f.read()
        except OSError:
            self.send_error(404, "blernsboard.html not found next to serve.py")
            return
        # tell the page where to send console errors (see do_POST)
        data = data.replace(b"<head>", b'<head>\n<meta name="blernsboard-log" content="/__log">', 1)
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def send_ranged(self):
        path = self.translate_path(self.path)
        rng = self.headers.get("Range")
        if not rng or not os.path.isfile(path):
            return super().do_GET()
        size = os.path.getsize(path)
        try:
            unit, _, spec = rng.partition("=")
            start_s, _, end_s = spec.partition("-")
            start = int(start_s) if start_s else 0
            end = int(end_s) if end_s else size - 1
        except ValueError:
            self.send_error(400, "bad Range")
            return
        if start >= size:
            self.send_response(416)
            self.send_header("Content-Range", f"bytes */{size}")
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        end = min(end, size - 1)
        self.send_response(206)
        self.send_header("Content-Type", "application/octet-stream")
        self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        self.send_header("Content-Length", str(end - start + 1))
        self.send_header("Accept-Ranges", "bytes")
        self.end_headers()
        with open(path, "rb") as f:
            f.seek(start)
            remaining = end - start + 1
            while remaining > 0:
                chunk = f.read(min(1 << 20, remaining))
                if not chunk:
                    break
                self.wfile.write(chunk)
                remaining -= len(chunk)

    def end_headers(self):
        self.send_header("Accept-Ranges", "bytes")
        super().end_headers()

    def log_message(self, fmt, *args):
        if os.environ.get("BLERNS_QUIET"):
            return
        super().log_message(fmt, *args)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("logdir")
    ap.add_argument("--port", type=int, default=6006)
    ap.add_argument("--bind", default="0.0.0.0")
    a = ap.parse_args()
    logdir = os.path.abspath(a.logdir)
    if not os.path.isdir(logdir):
        sys.exit(f"not a directory: {logdir}")
    handler = functools.partial(Handler, directory=logdir)
    srv = ThreadingHTTPServer((a.bind, a.port), handler)
    print(f"BlernsBoard  http://{a.bind}:{a.port}/   logdir={logdir}", flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
