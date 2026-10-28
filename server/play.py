"""After a title's page opens: press its Watch button and make the video fill the screen.

Each service is different: Tubi plays at once in a small player, Peacock and Sling
show a details page with a Watch button, Netflix's /watch/ page plays full window.
"""

import json
import time

import websocket

# A Watch/Play button on the title's details page, per service.
WATCH_BUTTON = {
    "peacock": '[data-testid="watch-button"]',
    "sling": '[data-testid="PLAY_CONTENT-button"]',
}

# The playing video, if it isn't already as big as the window, made full screen.
FULLSCREEN_JS = """(() => {
  const v = [...document.querySelectorAll('video')].find(v => !v.paused && v.clientWidth > 0);
  if (!v) return 'no video';
  if (document.fullscreenElement) return 'already';
  if (v.clientWidth >= innerWidth - 4 && v.clientHeight >= innerHeight - 4) return 'fills window';
  let box = v;
  while (box.parentElement && box.parentElement !== document.body
         && box.parentElement.clientWidth <= v.clientWidth + 4) box = box.parentElement;
  box.requestFullscreen();
  return 'fullscreen';
})()"""

PLAYING_JS = "[...document.querySelectorAll('video')].some(v => !v.paused && v.currentTime > 0.5 && v.clientWidth > 200)"


class Page:
    def __init__(self, ws_url):
        self.ws = websocket.create_connection(ws_url, timeout=15, suppress_origin=True)
        self.n = 0

    def call(self, method, **params):
        self.n += 1
        self.ws.send(json.dumps({"id": self.n, "method": method, "params": params}))
        while True:
            reply = json.loads(self.ws.recv())
            if reply.get("id") == self.n:
                return reply.get("result", {})

    def js(self, expression, gesture=False):
        result = self.call("Runtime.evaluate", expression=expression, userGesture=gesture,
                           returnByValue=True)
        return result.get("result", {}).get("value")

    def click(self, selector):
        """A real mouse click in the middle of the first visible match. True if clicked."""
        find = "[...document.querySelectorAll(%s)].find(e => e.offsetParent)" % json.dumps(selector)
        if not self.js(f"""(() => {{
          const el = {find};
          if (el) el.scrollIntoView({{block: 'center', behavior: 'instant'}});
          return !!el;
        }})()"""):
            return False
        time.sleep(0.8)  # pages with smooth scrolling are still moving
        box = self.js(f"""(() => {{
          const r = {find}.getBoundingClientRect();
          return [r.x + r.width / 2, r.y + r.height / 2];
        }})()""")
        x, y = box
        for kind in ("mousePressed", "mouseReleased"):
            self.call("Input.dispatchMouseEvent", type=kind, x=x, y=y, button="left", clickCount=1)
        return True

    def close(self):
        self.ws.close()


def autoplay(ws_url, service, timeout=40):
    """Get the title playing full screen. Returns what happened, for the log."""
    page = Page(ws_url)
    try:
        start = time.time()
        selector = WATCH_BUTTON.get(service)
        # Details pages can play a muted preview behind the page, so press Watch first
        # (if the button doesn't show up, it may already be the player).
        while selector and time.time() - start < 15:
            time.sleep(1.5)
            if page.click(selector):
                time.sleep(3)
                break
        while time.time() - start < timeout:
            if page.js(PLAYING_JS):
                time.sleep(1)
                return page.js(FULLSCREEN_JS, gesture=True)
            time.sleep(1.5)
        return "not playing"
    finally:
        page.close()
