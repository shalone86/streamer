"""What's on: titles from Netflix, Peacock, Tubi and Sling Freestream, in genre rows.

Netflix, Peacock and Tubi come from JustWatch (no key needed). Sling's free movies
and shows aren't in JustWatch, so they're read off Sling's own On Demand pages in
the server's browser. The rows are kept in /config/catalog.json and refreshed
twice a day.
"""

import json
import re
import threading
import time
import urllib.request
from urllib.parse import urlparse

import websocket

JUSTWATCH = "https://apis.justwatch.com/graphql"
IMAGES = "https://images.justwatch.com"
PER_SERVICE = 15  # titles per service per row
REFRESH = 12 * 3600

# JustWatch package -> service, best first: a title on several services opens in the first.
# Peacock is last: it refuses to play in this browser (its license server says no).
PACKAGES = {"nfx": "netflix", "tbv": "tubi", "pct": "peacock", "pcp": "peacock"}

GENRES = [
    ("Popular", None), ("Comedy", "cmy"), ("Action", "act"), ("Drama", "drm"),
    ("Thriller", "trl"), ("Horror", "hrr"), ("Sci-Fi", "scf"), ("Romance", "rma"),
    ("Crime", "crm"), ("Family", "fml"), ("Animation", "ani"), ("Documentary", "doc"),
    ("Reality", "rly"), ("Fantasy", "fnt"), ("History", "hst"), ("Western", "wsn"),
]

# Sling's row names -> our rows. Rows not listed here become rows of their own.
SLING_ROWS = {
    "action": "Action", "comedy": "Comedy", "comedy tv": "Comedy", "reality tv": "Reality",
    "animated": "Animation", "horror": "Horror", "romance": "Romance", "drama": "Drama",
    "thriller": "Thriller", "crime": "Crime", "crime tv": "Crime", "documentary": "Documentary",
    "documentaries": "Documentary", "kids": "Family", "family": "Family", "tiny tots": "Family",
    "bigger kids": "Family", "sci-fi": "Sci-Fi", "western": "Western", "popular movies": "Popular",
    "popular shows": "Popular", "must-see movies": "Popular",
}
SLING_TABS = ["on_demand_all", "on_demand_movies", "on_demand_tv_shows", "on_demand_kids"]

TITLE_FIELDS = """
  edges { node {
    objectType
    content(country: US, language: "en") {
      title originalReleaseYear posterUrl backdrops { backdropUrl }
    }
    offers(country: US, platform: WEB, filter: {packages: ["nfx", "pct", "pcp", "tbv"]}) {
      standardWebURL package { shortName }
    }
  } }
"""
QUERY = "query($f: TitleFilter, $first: Int!) { popularTitles(country: US, first: $first, filter: $f) {%s} }" % TITLE_FIELDS


def justwatch(filt, first=40):
    body = json.dumps({"query": QUERY, "variables": {"f": filt, "first": first}}).encode()
    req = urllib.request.Request(JUSTWATCH, body, {"content-type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        data = json.load(r)
    if data.get("errors"):
        raise RuntimeError(data["errors"][0].get("message", "JustWatch error"))
    return [t for t in map(jw_item, data["data"]["popularTitles"]["edges"]) if t]


def jw_item(edge):
    node = edge["node"]
    content = node["content"]
    offers = {}
    for offer in node["offers"]:
        service = PACKAGES.get(offer["package"]["shortName"])
        if service and service not in offers:
            offers[service] = offer["standardWebURL"]
    service = next((s for s in PACKAGES.values() if s in offers), None)
    if not service:
        return None
    if content["backdrops"]:
        img = IMAGES + content["backdrops"][0]["backdropUrl"].format(profile="s640", format="jpg")
    elif content["posterUrl"]:
        img = IMAGES + content["posterUrl"].format(profile="s332", format="jpg")
    else:
        img = ""
    return {
        "title": content["title"],
        "year": content["originalReleaseYear"] or "",
        "kind": "show" if node["objectType"] == "SHOW" else "movie",
        "img": img,
        "service": service,
        "url": play_url(offers[service]),
    }


def play_url(url):
    """Netflix's title page -> its player, which starts the title (or the next episode)."""
    m = re.match(r"https?://www\.netflix\.com/title/(\d+)", url)
    return f"https://www.netflix.com/watch/{m.group(1)}" if m else url


# ---------------------------------------------------------------- Sling

SLING_JS = r"""JSON.stringify([...document.querySelectorAll('[data-testid*="-screen-"][data-testid$="-title"]')]
  .map(t => {
    const m = t.dataset.testid.match(/-screen-(.+)-tile-\d+-title$/);
    const tile = t.closest('[data-testid$="-container"]') || t.parentElement;
    const a = t.closest('a') || tile.querySelector('a');
    const img = tile.querySelector('img[data-testid$="-image"]');
    return m && a && {row: m[1], title: t.innerText.trim(), url: a.href, img: img ? img.src : ''};
  }).filter(x => x && !/^\d+$/.test(x.row)))"""


def sling(cdp):
    """Read Sling Freestream's On Demand rows in a background tab of the server's browser."""
    with urllib.request.urlopen(f"{cdp}/json/version", timeout=5) as r:
        ws = websocket.create_connection(json.load(r)["webSocketDebuggerUrl"], timeout=30,
                                         suppress_origin=True)
    calls = iter(range(1, 10_000))

    def call(method, session=None, **params):
        msg = {"id": next(calls), "method": method, "params": params}
        if session:
            msg["sessionId"] = session
        ws.send(json.dumps(msg))
        while True:
            reply = json.loads(ws.recv())
            if reply.get("id") == msg["id"]:
                if "error" in reply:
                    raise RuntimeError(reply["error"].get("message"))
                return reply["result"]

    items = {}
    target = call("Target.createTarget", url="about:blank", background=True)["targetId"]
    try:
        session = call("Target.attachToTarget", targetId=target, flatten=True)["sessionId"]
        for tab in SLING_TABS:
            call("Page.navigate", session, url=f"https://watch.sling.com/dashboard/on_demand/{tab}")
            time.sleep(12)
            found = call("Runtime.evaluate", session, expression=SLING_JS)["result"].get("value")
            for t in json.loads(found or "[]"):
                if t["url"] in items or not t["title"]:
                    continue
                items[t["url"]] = {
                    "row": SLING_ROWS.get(t["row"].lower(), t["row"].title()),
                    "title": t["title"], "year": "", "kind": "show" if "/franchise/" in t["url"] else "movie",
                    "img": re.sub(r"/height=\d+$", "/height=360", t["img"].replace("http://", "https://", 1)),
                    "service": "sling", "url": t["url"],
                }
    finally:
        call("Target.closeTarget", targetId=target)
        ws.close()
    return list(items.values())


# ---------------------------------------------------------------- rows

def mix(*lists):
    """Interleave lists so a row shows every service, not one after another."""
    out, seen = [], set()
    for group in zip(*[l + [None] * (max(map(len, lists)) - len(l)) for l in lists]):
        for t in group:
            if t and (t["title"].lower(), t["kind"]) not in seen:
                seen.add((t["title"].lower(), t["kind"]))
                out.append(t)
    return out


def build(cdp):
    # Each service's popular titles separately, then taken in turns: one list of all
    # of them is mostly Netflix, with Tubi far down the row.
    services = {}
    for package, service in PACKAGES.items():
        services.setdefault(service, []).append(package)
    rows = {}
    for name, genre in GENRES:
        lists = []
        for packages in services.values():
            filt = {"packages": packages}
            if genre:
                filt["genres"] = [genre]
            try:
                lists.append(justwatch(filt, PER_SERVICE))
            except Exception as e:
                print(f"catalog: {name} {packages}: {e}")
        rows[name] = lists
    try:
        sling_items = sling(cdp)
    except Exception as e:
        print(f"catalog: sling: {e}")
        sling_items = []
    for t in sling_items:
        rows.setdefault(t["row"], [])
    by_row = {}
    for t in sling_items:
        by_row.setdefault(t.pop("row"), []).append(t)
    out = []
    for name, lists in rows.items():
        merged = mix(*lists, by_row.get(name, []))
        if merged:
            out.append({"title": name, "items": merged})
    return {"updated": int(time.time()), "rows": out, "sling": [t for l in by_row.values() for t in l]}


class Catalog:
    def __init__(self, path, cdp):
        self.path = path
        self.cdp = cdp
        self.lock = threading.Lock()
        self.refreshing = False
        try:
            self.data = json.loads(path.read_text())
        except (OSError, ValueError):
            self.data = {"updated": 0, "rows": [], "sling": []}

    def rows(self):
        if time.time() - self.data["updated"] > REFRESH:
            self.refresh()
        return {"rows": self.data["rows"], "loading": self.refreshing and not self.data["rows"]}

    def refresh(self):
        with self.lock:
            if self.refreshing:
                return
            self.refreshing = True
        threading.Thread(target=self._refresh, daemon=True).start()

    def _refresh(self):
        try:
            print("catalog: refreshing")
            data = build(self.cdp)
            if data["rows"]:
                self.data = data
                self.path.write_text(json.dumps(data))
            print(f"catalog: {sum(len(r['items']) for r in data['rows'])} titles in {len(data['rows'])} rows")
        finally:
            self.refreshing = False

    def search(self, query):
        query = query.strip()
        if not query:
            return []
        try:
            found = justwatch({"packages": list(PACKAGES), "searchQuery": query})
        except Exception as e:
            print(f"catalog: search: {e}")
            found = []
        words = query.lower().split()
        sling_found = [t for t in self.data.get("sling", []) if all(w in t["title"].lower() for w in words)]
        return mix(found, sling_found)


def service_of(url):
    host = urlparse(url).hostname or ""
    for name in ("netflix", "peacocktv", "tubitv", "sling"):
        if name in host:
            return {"peacocktv": "peacock", "tubitv": "tubi"}.get(name, name)
    return ""
