#!/usr/bin/env python3
"""BlernsBoard: serve blernsboard.html together with a TensorBoard log directory.

    blernsboard --logdir runs/                 # http://localhost:6006/
    blernsboard --logdir runs/ --bind_all      # reachable from other machines
    blernsboard runs/ --port 8080 --open       # positional logdir, open a browser

Flags follow TensorBoard's names. The page alone also works with any static
server (copy blernsboard.html into the logdir and run python3 -m http.server);
this helper adds: no copying, HTTP Range so tailing a growing file only fetches
the tail, browser console errors echoed to this terminal via POST /__log, and
GET /__index, which lists every event file with its size in one response so the
page refreshes with a single request instead of one per directory and file.
"""
import argparse, gzip, json, os, sys, functools, time, threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

__version__ = "0.1.0"
HERE = os.path.dirname(os.path.abspath(__file__))
PAGE = os.path.join(HERE, "blernsboard.html")


class Handler(SimpleHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    _index_cache = {}
    _index_lock = threading.Lock()

    def send_index(self, prefix):
        """JSON list of tfevents files under prefix (a URL path), sizes included; cached 2 s."""
        base = self.translate_path(prefix if prefix.endswith("/") else prefix + "/")
        if not os.path.isdir(base):
            self.send_error(404, "not a directory")
            return
        now = time.time()
        with self._index_lock:
            hit = self._index_cache.get(base)
            if hit and now - hit[0] < 2:
                body = hit[1]
            else:
                files = []
                def walk(d, rel, depth):
                    try:
                        with os.scandir(d) as it:
                            for e in it:
                                if e.name.startswith("."):
                                    continue
                                try:
                                    if e.is_dir(follow_symlinks=False):
                                        if depth < 10:
                                            walk(e.path, rel + e.name + "/", depth + 1)
                                    elif "tfevents" in e.name and e.is_file():
                                        st = e.stat()
                                        files.append({"path": rel + e.name, "size": st.st_size, "mtime": st.st_mtime})
                                except OSError:
                                    pass
                    except OSError:
                        pass
                walk(base, "", 0)
                body = json.dumps({"files": files, "time": now}).encode()
                self._index_cache[base] = (now, body)
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = self.path.split("?")[0]
        if path.endswith("/__index"):
            return self.send_index(path[: -len("__index")])
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
        if not rng and os.path.isfile(path) and "tfevents" in os.path.basename(path) and "gzip" in self.headers.get("Accept-Encoding", ""):
            return self.send_gzipped(path)
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

    def send_gzipped(self, path):
        """Event files shrink ~3.5x with gzip level 1 at ~200 MB/s; files over 256 MB are sent plain."""
        try:
            size = os.path.getsize(path)
            if size > 256 << 20:
                return super().do_GET()
            with open(path, "rb") as f:
                data = gzip.compress(f.read(), compresslevel=1)
        except OSError:
            self.send_error(404, "File not found")
            return
        self.send_response(200)
        self.send_header("Content-Type", "application/octet-stream")
        self.send_header("Content-Encoding", "gzip")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Vary", "Accept-Encoding")
        self.end_headers()
        self.wfile.write(data)

    def end_headers(self):
        self.send_header("Accept-Ranges", "bytes")
        super().end_headers()

    def log_message(self, fmt, *args):
        if os.environ.get("BLERNS_QUIET"):
            return
        super().log_message(fmt, *args)


def main(argv=None):
    ap = argparse.ArgumentParser(prog="blernsboard", description="Serve BlernsBoard over a TensorBoard log directory.",
                                 epilog="Flags follow TensorBoard: --logdir, --port, --host, --bind_all.")
    ap.add_argument("logdir_pos", nargs="?", metavar="LOGDIR", help="log directory (same as --logdir)")
    ap.add_argument("--logdir", help="directory containing runs (default: current directory)")
    ap.add_argument("--port", type=int, default=6006, help="port to listen on (default 6006)")
    ap.add_argument("--host", default=None, help="address to bind (default localhost)")
    ap.add_argument("--bind_all", "--bind-all", action="store_true", help="listen on all interfaces (0.0.0.0)")
    ap.add_argument("--open", action="store_true", help="open the page in a browser")
    ap.add_argument("--quiet", action="store_true", help="do not print each request")
    ap.add_argument("--version", action="version", version="blernsboard " + __version__)
    a = ap.parse_args(argv)
    logdir = os.path.abspath(a.logdir or a.logdir_pos or ".")
    if not os.path.isdir(logdir):
        sys.exit(f"blernsboard: not a directory: {logdir}")
    if not os.path.isfile(PAGE):
        sys.exit(f"blernsboard: blernsboard.html not found next to {__file__}")
    if a.quiet:
        os.environ["BLERNS_QUIET"] = "1"
    host = a.host or ("0.0.0.0" if a.bind_all else "localhost")
    handler = functools.partial(Handler, directory=logdir)
    try:
        srv = ThreadingHTTPServer((host, a.port), handler)
    except OSError as e:
        sys.exit(f"blernsboard: cannot listen on {host}:{a.port}: {e.strerror}")
    shown = "localhost" if host in ("0.0.0.0", "::", "localhost") else host
    url = f"http://{shown}:{a.port}/"
    print(f"BlernsBoard {__version__}  {url}  logdir={logdir}" + ("  (all interfaces)" if host == "0.0.0.0" else ""), flush=True)
    if a.open:
        import webbrowser
        webbrowser.open(url)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print()


if __name__ == "__main__":
    main()
