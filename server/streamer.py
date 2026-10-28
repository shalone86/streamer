"""Control server: the Roku channel talks to this.

- /api/catalog   what's on, in genre rows; /api/search?q= finds titles
- /api/open      points the browser at a service (or any https URL; play=1 starts it)
- /api/stream/*  starts and stops the screen capture (ffmpeg -> HLS in /tmp/hls)
- /api/button    turns a Roku remote button into a key press or mouse action
- /hls/...       the video stream the Roku plays
- /              setup page (download the Roku channel, open the browser view)
- /start         the browser's own start page
"""

import io
import json
import os
import re
import shutil
import subprocess
import threading
import time
import urllib.request
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import websocket

import catalog
import play

APP = Path(__file__).resolve().parent
ROKU_DIR = Path(os.environ.get("ROKU_DIR", APP.parent / "roku"))
WEB_DIR = APP / "web"
CONFIG_DIR = Path(os.environ.get("CONFIG_DIR", "/config"))
HLS_DIR = Path(os.environ.get("HLS_DIR", "/tmp/hls"))
PORT = int(os.environ.get("PORT", "8080"))
DISPLAY = os.environ.get("DISPLAY", ":99")
CDP = os.environ.get("CDP_URL", "http://127.0.0.1:9222")

# The screen is 1920x1100; the stream is the 1920x1080 in its middle, so the pointer
# can hide in the 10px strips above and below (see park_pointer).
SCREEN_W, SCREEN_H, CAPTURE_TOP = 1920, 1100, 10

# Encoding. The defaults fit a CPU-only server at 1080p30; set RESOLUTION=1280x720
# or a faster PRESET (faster, superfast) if the CPU struggles.
RESOLUTION = os.environ.get("RESOLUTION", "1920x1080")
FPS = os.environ.get("FPS", "30")
BITRATE = os.environ.get("BITRATE", "6M")
PRESET = os.environ.get("PRESET", "veryfast")
HLS_TIME = os.environ.get("HLS_TIME", "0.5")
# The playlist only lists the newest few segments: the Roku starts at the oldest one
# listed, so a short list keeps it close to live (less delay after each button press).
HLS_LIST = os.environ.get("HLS_LIST", "4")
IDLE_STOP = int(os.environ.get("IDLE_STOP", "45"))  # seconds without a Roku request

SERVICES = {
    "netflix": "https://www.netflix.com/browse",
    "peacock": "https://www.peacocktv.com/",
    "tubi": "https://tubitv.com/",
    "sling": "https://watch.sling.com/dashboard/on_demand/on_demand_all",  # Freestream: free movies and shows
}

DEFAULT_KEYMAP = json.loads((APP / "keymap.json").read_text())


def load_keymap():
    """keymap.json in /config overrides the defaults, mode by mode, button by button."""
    keymap = {mode: dict(buttons) for mode, buttons in DEFAULT_KEYMAP.items()}
    custom = CONFIG_DIR / "keymap.json"
    if custom.exists():
        try:
            for mode, buttons in json.loads(custom.read_text()).items():
                keymap.setdefault(mode, {}).update(buttons)
        except (ValueError, AttributeError) as e:
            print(f"ignoring {custom}: {e}")
    return keymap


# ---------------------------------------------------------------- browser

def cdp_pages():
    with urllib.request.urlopen(f"{CDP}/json", timeout=5) as r:
        return [t for t in json.load(r) if t.get("type") == "page"]


def browser_open(url):
    """Load url in the browser's one tab, closing any others (popups, extension tabs)."""
    pages = cdp_pages()
    if not pages:
        raise RuntimeError("the browser has no open tab")
    page, others = pages[0], pages[1:]
    ws = websocket.create_connection(page["webSocketDebuggerUrl"], timeout=10, suppress_origin=True)
    try:
        ws.send(json.dumps({"id": 1, "method": "Page.navigate", "params": {"url": url}}))
        ws.recv()
    finally:
        ws.close()
    for other in others:
        urllib.request.urlopen(f"{CDP}/json/close/{other['id']}", timeout=5).close()
    urllib.request.urlopen(f"{CDP}/json/activate/{page['id']}", timeout=5).close()
    focus_browser()
    return page


def start_title(page, url):
    """Press the title's Watch button and make it full screen, in the background."""
    def run():
        try:
            print(f"play: {url}: {play.autoplay(page['webSocketDebuggerUrl'], catalog.service_of(url))}")
        except Exception as e:
            print(f"play: {url}: {e!r}")
    threading.Thread(target=run, daemon=True).start()


def xdotool(*args):
    subprocess.run(["xdotool", *args], env={**os.environ, "DISPLAY": DISPLAY},
                   timeout=5, check=False, capture_output=True)


def focus_browser():
    xdotool("search", "--onlyvisible", "--class", "google-chrome", "windowactivate", "--sync")


def park_pointer():
    """Move the pointer into the strip below the streamed area, out of sight."""
    xdotool("mousemove", str(SCREEN_W - 1), str(SCREEN_H - 1))


def unpark_pointer():
    """Bring a parked pointer back to the middle of the picture."""
    out = subprocess.run(["xdotool", "getmouselocation", "--shell"], capture_output=True, text=True,
                         env={**os.environ, "DISPLAY": DISPLAY}, timeout=5).stdout
    y = int(re.search(r"Y=(\d+)", out).group(1)) if "Y=" in out else 0
    if y >= CAPTURE_TOP + 1080 or y < CAPTURE_TOP:
        xdotool("mousemove", str(SCREEN_W // 2), str(SCREEN_H // 2))


def press(action, repeat=0):
    """Do one keymap action: {"key": "alt+Left"}, {"move": [dx, dy]}, {"click": 1}, or
    {"media": "toggle" | "seek", "by": seconds, "else": action} on the playing video
    (the "else" action when there's none). Returns a word for the Roku to show, or ""."""
    if "media" in action:
        pages = cdp_pages()
        shown = play.media(pages[0]["webSocketDebuggerUrl"], action["media"], action.get("by", 0)) if pages else ""
        if shown or "else" not in action:
            return shown
        return press(action["else"], repeat)
    if "key" in action:
        xdotool("key", "--clearmodifiers", action["key"])
    elif "move" in action:
        # Held arrows repeat; the pointer speeds up the longer they're held.
        speed = min(1 + repeat * 0.25, 4)
        dx, dy = (int(v * speed) for v in action["move"])
        xdotool("mousemove_relative", "--", str(dx), str(dy))
    elif "click" in action:
        xdotool("click", str(action["click"]))


# ---------------------------------------------------------------- stream

class Stream:
    def __init__(self):
        self.proc = None
        self.lock = threading.Lock()
        self.last_request = 0.0
        threading.Thread(target=self._watchdog, daemon=True).start()

    def running(self):
        return self.proc is not None and self.proc.poll() is None

    def start(self):
        with self.lock:
            self.last_request = time.time()
            if not self.running():
                self._spawn()
        return self._wait_ready()

    def _spawn(self):
        shutil.rmtree(HLS_DIR, ignore_errors=True)
        HLS_DIR.mkdir(parents=True, exist_ok=True)
        fps = int(FPS)
        gop = max(1, round(fps * float(HLS_TIME)))  # a keyframe starts every segment
        cmd = [
            "ffmpeg", "-hide_banner", "-loglevel", "warning",
            "-thread_queue_size", "512",
            "-f", "x11grab", "-framerate", FPS, "-video_size", "1920x1080", "-draw_mouse", "1",
            "-i", f"{DISPLAY}+0,{CAPTURE_TOP}",
            "-thread_queue_size", "1024",
            "-f", "pulse", "-ac", "2", "-ar", "48000", "-i", "stream.monitor",
            *(["-vf", f"scale={RESOLUTION.replace('x', ':')}"] if RESOLUTION != "1920x1080" else []),
            "-c:v", "libx264", "-preset", PRESET, "-tune", "zerolatency",
            "-profile:v", "high", "-level", "4.1", "-pix_fmt", "yuv420p",
            "-b:v", BITRATE, "-maxrate", BITRATE, "-bufsize", BITRATE,
            "-g", str(gop), "-keyint_min", str(gop),
            "-sc_threshold", "0",
            "-c:a", "aac", "-b:a", "160k", "-af", "aresample=async=1",
            "-f", "hls", "-hls_time", HLS_TIME, "-hls_list_size", HLS_LIST,
            "-hls_delete_threshold", "6",
            "-hls_flags", "delete_segments+independent_segments",
            "-hls_segment_filename", str(HLS_DIR / "seg%05d.ts"),
            str(HLS_DIR / "index.m3u8"),
        ]
        print("stream: starting")
        self.proc = subprocess.Popen(cmd)

    def _wait_ready(self, timeout=20):
        playlist = HLS_DIR / "index.m3u8"
        deadline = time.time() + timeout
        while time.time() < deadline:
            if not self.running():
                return False
            if playlist.exists() and playlist.read_text().count("#EXTINF") >= 2:
                return True
            time.sleep(0.2)
        return False

    def stop(self):
        with self.lock:
            if self.running():
                print("stream: stopping")
                self.proc.terminate()
                try:
                    self.proc.wait(5)
                except subprocess.TimeoutExpired:
                    self.proc.kill()
            self.proc = None

    def touch(self):
        self.last_request = time.time()

    def _watchdog(self):
        # The Roku re-reads the playlist every second or two while it plays; if it
        # stops (channel closed, TV off), stop encoding.
        while True:
            time.sleep(5)
            if self.running() and time.time() - self.last_request > IDLE_STOP:
                print("stream: no viewer, stopping")
                self.stop()


STREAM = Stream()
CATALOG = catalog.Catalog(CONFIG_DIR / "catalog.json", CDP)


# ---------------------------------------------------------------- Roku channel

def roku_zip(server_url):
    """The channel, ready to sideload, with this server's address built in."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for path in sorted(ROKU_DIR.rglob("*")):
            if path.is_dir():
                continue
            name = path.relative_to(ROKU_DIR).as_posix()
            data = path.read_bytes()
            if name == "components/config.brs":
                data = data.replace(b"__SERVER_URL__", server_url.encode())
            z.writestr(name, data)
    return buf.getvalue()


# ---------------------------------------------------------------- HTTP

class Handler(BaseHTTPRequestHandler):
    server_version = "streamer"

    def log_message(self, fmt, *args):
        if not self.path.startswith(("/hls/", "/api/button")):
            super().log_message(fmt, *args)

    def send(self, code, body=b"", ctype="application/json", headers=None):
        if isinstance(body, (dict, list)):
            body = json.dumps(body).encode()
        elif isinstance(body, str):
            body = body.encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def do_HEAD(self):
        self.do_GET()

    def do_POST(self):
        self.do_GET()

    def do_GET(self):
        url = urlparse(self.path)
        q = {k: v[-1] for k, v in parse_qs(url.query).items()}
        try:
            self.route(url.path, q)
        except Exception as e:  # report, don't kill the connection silently
            print(f"error on {self.path}: {e!r}")
            self.send(500, {"ok": False, "error": str(e)})

    def route(self, path, q):
        if path.startswith("/hls/"):
            return self.hls(path[len("/hls/"):])
        if path == "/api/status":
            return self.send(200, {"ok": True, "streaming": STREAM.running(),
                                   "services": sorted(SERVICES)})
        if path == "/api/open":
            target = SERVICES.get(q.get("service", ""), q.get("url", ""))
            if not re.match(r"https?://", target):
                return self.send(400, {"ok": False, "error": "unknown service"})
            page = browser_open(target)
            if q.get("play") == "1":
                start_title(page, target)
            return self.send(200, {"ok": True})
        if path == "/api/catalog":
            return self.send(200, CATALOG.rows())
        if path == "/api/search":
            return self.send(200, {"items": CATALOG.search(q.get("q", ""))})
        if path == "/api/stream/start":
            focus_browser()
            park_pointer()
            ok = STREAM.start()
            return self.send(200 if ok else 503, {"ok": ok, "url": "/hls/index.m3u8"})
        if path == "/api/stream/stop":
            STREAM.stop()
            return self.send(200, {"ok": True})
        if path == "/api/button":
            return self.button(q)
        if path == "/roku-channel.zip":
            server = q.get("server") or f"http://{self.headers.get('Host', f'localhost:{PORT}')}"
            return self.send(200, roku_zip(server.rstrip("/")), "application/zip",
                             {"Content-Disposition": 'attachment; filename="streamer-roku.zip"'})
        if path in ("/", "/start"):
            page = "index.html" if path == "/" else "start.html"
            return self.send(200, (WEB_DIR / page).read_bytes(), "text/html; charset=utf-8")
        self.send(404, {"ok": False, "error": "not found"})

    def button(self, q):
        STREAM.touch()
        mode = q.get("mode", "keys")
        if mode != self.server.last_mode:
            # Pointer appears when the Roku switches to mouse mode, hides again after.
            if mode == "mouse":
                unpark_pointer()
            else:
                park_pointer()
            self.server.last_mode = mode
        action = load_keymap().get(mode, {}).get(q.get("b", ""))
        if not action:
            return self.send(404, {"ok": False, "error": "no action for that button"})
        shown = press(action, int(q.get("n", "0") or 0))
        self.send(200, {"ok": True, "badge": shown or ""})

    def hls(self, name):
        if not re.fullmatch(r"[\w.-]+", name):
            return self.send(404)
        STREAM.touch()
        path = HLS_DIR / name
        if not path.exists():
            return self.send(404)
        body = path.read_bytes()
        if name.endswith(".m3u8"):
            # ffmpeg rounds sub-second segments down to a target duration of 0, which
            # players may reject; it must be at least the longest segment.
            body = body.replace(b"#EXT-X-TARGETDURATION:0\n", b"#EXT-X-TARGETDURATION:1\n")
        ctype = "application/vnd.apple.mpegurl" if name.endswith(".m3u8") else "video/mp2t"
        self.send(200, body, ctype)


def main():
    print(f"streamer: listening on :{PORT}")
    httpd = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    httpd.last_mode = "keys"
    threading.Timer(30, CATALOG.rows).start()  # once the browser is up (Sling needs it)
    httpd.serve_forever()


if __name__ == "__main__":
    main()
