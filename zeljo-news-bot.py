"""
Objavljuje nove članke s lokalnih portala u Discord kanal preko webhooka.

Pokreće se jednom (GitHub Actions ga pokreće svakih 15 minuta):
provjeri izvore, objavi nove članke koji spominju ključne riječi i završi.
Objavljeni članci se pamte u vijesti_vidjene.json.
"""

import calendar
import json
import os
import re
import time
import unicodedata
from html import unescape
from html.parser import HTMLParser
from urllib.error import HTTPError
from urllib.parse import parse_qs, quote_plus, urljoin, urlsplit
from urllib.request import Request, urlopen

import feedparser

# ---------- podešavanja ----------

WEBHOOK = os.getenv("DISCORD_WEBHOOK", "")  # postavlja se u GitHub Secrets

# "sve": True znači da se objavljuje svaki članak, bez filtera ključnih riječi.
IZVORI = [
    # RSS
    {"naziv": "Klix.ba", "rss": "https://www.klix.ba/rss"},
    {"naziv": "FK Željezničar", "rss": "https://www.fkzeljeznicar.ba/feed/", "sve": True},
    {"naziv": "Sportske.ba", "sajt": "https://sportske.ba/"},
    {"naziv": "Reprezentacija.ba", "sajt": "https://reprezentacija.ba/"},
    {"naziv": "MeridianSport.ba", "sajt": "https://meridiansport.ba/"},
    {"naziv": "Oslobođenje", "sajt": "https://www.oslobodjenje.ba/"},
    {"naziv": "SportBC.ba", "sajt": "https://sportbc.ba/"},
    {"naziv": "SportskiPuls.ba", "sajt": "https://sportskipuls.ba/"},
    {"naziv": "Sport.ba", "sajt": "https://sport.ba/"},
    # čitanje stranice
    {"naziv": "SportSport.ba", "stranica": "https://sportsport.ba/fudbal",
     "uzorak": r"^https://sportsport\.ba/[a-z0-9-]+/[a-z0-9-]+/\d+$"},
    {"naziv": "SCsport.ba", "sajt": "https://scsport.raport.ba/"},
    {"naziv": "BHFudbal.ba", "stranica": "https://bhfudbal.ba/"},
    {"naziv": "Avaz.ba", "stranica": "https://avaz.ba/sport"},
]

# Članak se objavljuje ako naslov, link ili uvod (kod RSS-a) spominje nešto s ovih lista.
# - Svejedno je da li se piše sa ili bez kvačica, velikim ili malim slovima.
# - Traže se cijele riječi; * na kraju znači "bilo koji nastavak":
#   "grbavic*" hvata Grbavica, Grbavici, Grbavicu...
# - Za ljude uvijek piši ime I prezime ("amar* osim*"), jer samo "osim"
#   znači i "osim toga" i hvatalo bi svašta.

KLUB = [
    "zeljeznicar*",            # Željezničar, Željezničara, Željezničaru...
    "zeljo",                   # samo "Željo" ("željom", "želje" su obične riječi)
    "fkz", "fk zeljeznicar*",
    "grbavic*",                # stadion Grbavica
    "manijac*",                # navijači Manijaci
    "plavo bijel*", "plavo-bijel*",
]

LJUDI = [
    "ivic* osim*", "svabo",    # Ivica Osim, Švabo
    "amar* osim*",
    "muslera*",                # trener (prema Wikipediji, od jula 2026)
    # Dodaj igrače i ljude iz kluba, ime + prezime, npr.:
    # "sulejman* krpic*",
]

KLJUCNE_RIJECI = KLUB + LJUDI

MAX_STAROST_SATI = 48    # stariji članci se preskaču
PRVI_PUT_OBJAVI = 3      # pri prvom pokretanju objavi samo ovoliko najnovijih
SEEN_FILE = "vijesti_vidjene.json"
UA = ("Mozilla/5.0 (Linux; Android 14; SM-S911B) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/130.0 Mobile Safari/537.36")

# ---------- pamćenje objavljenih ----------

seen: dict[str, float] = {}


def load_seen() -> bool:
    """Vraća True ako je ovo prvo pokretanje."""
    global seen
    if not os.path.exists(SEEN_FILE):
        return True
    try:
        with open(SEEN_FILE, encoding="utf-8") as f:
            seen = json.load(f)
    except (json.JSONDecodeError, UnicodeDecodeError):
        print("⚠️ vijesti_vidjene.json je prazan ili oštećen, krećem ispočetka")
        seen = {}
        return True
    return not seen  # prazna lista = kao prvo pokretanje


def save_seen() -> None:
    granica = time.time() - 30 * 86400  # zaboravi starije od 30 dana
    for k in [k for k, t in seen.items() if t < granica]:
        del seen[k]
    with open(SEEN_FILE, "w", encoding="utf-8") as f:
        json.dump(seen, f)


# ---------- pomoćne ----------

def fold(text: str) -> str:
    """Mala slova, bez kvačica: 'Željezničar' -> 'zeljeznicar'."""
    text = text.lower().replace("đ", "dj")
    return "".join(c for c in unicodedata.normalize("NFKD", text)
                   if not unicodedata.combining(c))


def keyword_regex(k: str) -> str:
    """'ivic* osim*' -> cijele riječi, * = bilo koji nastavak, razmak = bilo kakav razmak/crtica."""
    parts = []
    for word in fold(k).replace("-", " ").split():
        star = word.endswith("*")
        word = re.escape(word.rstrip("*"))
        parts.append(word + ("[a-z0-9]*" if star else ""))
    return r"(?<![a-z0-9])" + r"[^a-z0-9]+".join(parts) + r"(?![a-z0-9])"


KLJUCNE = re.compile("|".join(keyword_regex(k) for k in KLJUCNE_RIJECI)) if KLJUCNE_RIJECI else None


def matches(text: str) -> bool:
    return KLJUCNE is None or bool(KLJUCNE.search(fold(text)))


def clean_url(url: str) -> str:
    p = urlsplit(url)
    return f"{p.scheme}://{p.netloc}{p.path}".rstrip("/")


def domain(url: str) -> str:
    return urlsplit(url).netloc.lower().removeprefix("www.")


HEADERS = {
    "User-Agent": UA,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "bs-BA,bs;q=0.9,hr;q=0.8,en;q=0.7",
    "Referer": "https://www.google.com/",
}


def fetch_page(url: str) -> tuple[str, str]:
    """Vraća (html, konačna adresa nakon preusmjeravanja)."""
    resp = urlopen(Request(url, headers=HEADERS), timeout=20)
    return resp.read().decode("utf-8", errors="replace"), resp.geturl()


def get_html(url: str) -> str:
    return fetch_page(url)[0]


def fetch_via_reader(url: str) -> str:
    """Rezerva za portale koji blokiraju GitHub: stranicu otvori besplatni servis r.jina.ai
    (s drugih servera i s pravim browserom, pa radi i za stranice na JavaScriptu)."""
    req = Request("https://r.jina.ai/" + url, headers={
        "User-Agent": UA, "X-Return-Format": "html", "X-Timeout": "25"})
    return urlopen(req, timeout=40).read().decode("utf-8", errors="replace")


REZERVA_UPIT = "Željezničar"


def read_search(izvor: dict) -> list[dict]:
    """Rezerva kad portal blokira bota: Bing News pretraga samo tog portala."""
    dom = domain(izvor.get("stranica") or izvor.get("sajt") or izvor.get("rss"))
    q = quote_plus(f"site:{dom} {REZERVA_UPIT}")
    feed = feedparser.parse(f"https://www.bing.com/news/search?q={q}&format=rss&setlang=bs", agent=UA)
    items = []
    for i, e in enumerate(feed.entries):
        link = e.get("link", "")
        if "bing.com" in link:  # Bing daje svoj link za praćenje, pravi je u parametru url=
            link = (parse_qs(urlsplit(link).query).get("url") or [""])[0]
        if not link or domain(link) != dom:
            continue
        ts = calendar.timegm(e.published_parsed) if e.get("published_parsed") else time.time() - i
        items.append({"title": unescape(e.get("title", "")).strip() or link, "link": link, "ts": ts,
                      "uvod": re.sub(r"<[^>]+>", " ", unescape(e.get("summary", "")))[:1000]})
    return items


class PageParser(HTMLParser):
    """Skuplja linkove (href + tekst) i RSS linkove iz <head>."""

    def __init__(self):
        super().__init__()
        self.links: list[tuple[str, str]] = []
        self.feeds: list[str] = []
        self._href = None
        self._text: list[str] = []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "a":
            self._href = a.get("href")
            self._text = []
        elif tag == "link" and "alternate" in (a.get("rel") or "") \
                and any(t in (a.get("type") or "") for t in ("rss", "atom")) and a.get("href"):
            self.feeds.append(a["href"])

    def handle_data(self, data):
        if self._href is not None:
            self._text.append(data)

    def handle_endtag(self, tag):
        if tag == "a" and self._href is not None:
            self.links.append((self._href, " ".join("".join(self._text).split())))
            self._href = None


def parse_page(url: str) -> PageParser:
    parser = PageParser()
    parser.feed(get_html(url))
    return parser


# ---------- čitanje izvora ----------

def read_rss(url: str) -> list[dict]:
    feed = feedparser.parse(url, agent=UA)
    items = []
    for i, e in enumerate(feed.entries):
        title, link = e.get("title", "").strip(), e.get("link")
        if not title or not link:
            continue
        ts = calendar.timegm(e.published_parsed) if e.get("published_parsed") else time.time() - i
        uvod = re.sub(r"<[^>]+>", " ", unescape(e.get("summary", "")))[:1000]
        items.append({"title": title, "link": link, "ts": ts, "uvod": uvod})
    return items


NIJE_CLANAK = re.compile(r"/(tag|tags|kategorija|category|autor|author|page|search|pretraga)/")


def looks_like_article(url: str, base: str) -> bool:
    if domain(url) != domain(base) or NIJE_CLANAK.search(url):
        return False
    path = urlsplit(url).path.strip("/")
    last = path.split("/")[-1] if path else ""
    return bool(re.search(r"\d{4,}", path)) or last.count("-") >= 3


def read_page(izvor: dict, preko_citaca: bool = False) -> list[dict]:
    url = izvor["stranica"]
    if preko_citaca:
        html = fetch_via_reader(url)
    else:
        html, url = fetch_page(url)  # url = konačna adresa (npr. scsport.ba -> scsport.raport.ba)
    parser = PageParser()
    parser.feed(html)
    uzorak = re.compile(izvor["uzorak"]) if izvor.get("uzorak") else None

    titles: dict[str, str] = {}  # isti članak zna imati više linkova (slika, naslov)
    for href, text in parser.links:
        link = clean_url(urljoin(url, href))
        ok = uzorak.match(link) if uzorak else looks_like_article(link, url)
        if ok and (link not in titles or len(text) > len(titles[link])):
            titles[link] = text

    now = time.time()
    items = []
    for i, (link, text) in enumerate(titles.items()):  # prvi na stranici je najnoviji
        slug = urlsplit(link).path.strip("/").split("/")[-1]
        from_slug = len(text) < 15
        title = re.sub(r"[-_]+", " ", re.sub(r"\d{4,}", "", slug)).strip() if from_slug else text
        items.append({"title": title or link, "link": link, "ts": now - i, "slug": from_slug})
    return items


TITLE_PATTERNS = [  # redom: og:title, twitter:title, <title>
    re.compile(r'<meta[^>]+(?:property|name)=["\']og:title["\'][^>]*content="([^"]+)"', re.I),
    re.compile(r'<meta[^>]+content="([^"]+)"[^>]*(?:property|name)=["\']og:title["\']', re.I),
    re.compile(r'<meta[^>]+name=["\']twitter:title["\'][^>]*content="([^"]+)"', re.I),
    re.compile(r'<title[^>]*>([^<]+)</title>', re.I),
]


def real_title(url: str) -> str | None:
    """Pravi naslov sa stranice članka (kad ga sa naslovne nije bilo moguće pročitati)."""
    try:
        html = get_html(url)
    except Exception:
        try:
            html = fetch_via_reader(url)  # portal blokira GitHub
        except Exception:
            return None
    for pattern in TITLE_PATTERNS:
        m = pattern.search(html)
        if m and m.group(1).strip():
            return unescape(m.group(1)).strip()
    return None


rss_cache: dict[str, str | None] = {}  # naziv -> pronađeni RSS (None = nema, čitaj stranicu)


def discover_rss(sajt: str) -> str | None:
    try:
        for href in parse_page(sajt).feeds:
            return urljoin(sajt, href)
    except Exception:
        pass
    for path in ("feed/", "rss", "rss.xml", "feed", "index.rss"):
        url = urljoin(sajt, path)
        if feedparser.parse(url, agent=UA).entries:
            return url
    return None


def read_source(izvor: dict) -> list[dict]:
    if "rss" in izvor:
        return read_rss(izvor["rss"])
    if "stranica" in izvor:
        return read_page(izvor)

    naziv = izvor["naziv"]
    if naziv not in rss_cache:
        rss_cache[naziv] = discover_rss(izvor["sajt"])
        found = rss_cache[naziv] or "nije nađen, čitam stranicu"
        print(f"🔎 {naziv}: RSS {found}")
    if rss_cache[naziv]:
        items = read_rss(rss_cache[naziv])
        if items:
            return items
    return read_page({"stranica": izvor["sajt"]})


def fetch_all() -> list[dict]:
    items, status = [], []
    for izvor in IZVORI:
        try:
            found = read_source(izvor)
        except Exception as e:
            found = []
            print(f"⚠️ {izvor['naziv']}: {e}")
        stranica = izvor.get("stranica") or izvor.get("sajt")
        if not found and stranica:  # blokiran ili prazan: probaj preko čitača
            try:
                found = read_page({**izvor, "stranica": stranica}, preko_citaca=True)
                print(f"↪️ {izvor['naziv']}: preko čitača {len(found)}")
            except Exception as e:
                print(f"⚠️ {izvor['naziv']} (čitač): {e}")
        if not found and not izvor.get("sve"):  # i dalje ništa: Bing News pretraga
            try:
                found = read_search(izvor)
                print(f"↪️ {izvor['naziv']}: preko pretrage {len(found)}")
            except Exception as e:
                print(f"⚠️ {izvor['naziv']} (pretraga): {e}")
        for it in found:
            it["source"] = izvor["naziv"]
            it["sve"] = izvor.get("sve", False)
        status.append(f"{izvor['naziv']} {len(found)}")
        items.extend(found)
    print("Izvori: " + " · ".join(status))
    return items


def new_items(items: list[dict]) -> list[dict]:
    fresh = []
    now = time.time()
    for it in sorted(items, key=lambda x: x["ts"]):
        key = clean_url(it["link"])
        title_key = "t:" + fold(it["title"])  # isti članak na dva mjesta objavi jednom
        if key in seen or title_key in seen:
            continue
        seen[key] = seen[title_key] = now
        tekst = " ".join((it["title"], it["link"], it.get("uvod", "")))
        if (it["sve"] or matches(tekst)) \
                and now - it["ts"] <= MAX_STAROST_SATI * 3600:
            fresh.append(it)
    return fresh


# ---------- objava na Discord ----------

def escape_md(text: str) -> str:
    return re.sub(r"([*_`~|>\\])", r"\\\1", text)


def post(content: str) -> None:
    body = json.dumps({"content": content, "username": "Vijesti",
                       "allowed_mentions": {"parse": []}}).encode()
    for _ in range(5):
        req = Request(WEBHOOK, data=body, headers={"Content-Type": "application/json",
                                                   "User-Agent": "vijesti-bot"})
        try:
            urlopen(req, timeout=20)
            time.sleep(1)  # da ne prekoračimo Discordov limit
            return
        except HTTPError as e:
            if e.code != 429:
                raise
            wait = json.loads(e.read() or b"{}").get("retry_after", 2)
            time.sleep(float(wait) + 0.5)
    raise RuntimeError("Discord stalno odbija poruke (429)")


def main() -> None:
    if not WEBHOOK.startswith("https://"):
        raise SystemExit("Nedostaje DISCORD_WEBHOOK (GitHub → Settings → Secrets → Actions).")

    first_run = load_seen()
    fresh = new_items(fetch_all())
    if first_run:  # ne zatrpavaj kanal svim starim člancima
        fresh = fresh[-PRVI_PUT_OBJAVI:]

    try:
        for it in fresh:
            if it.get("slug"):  # naslov je bio samo iz linka, uzmi pravi sa stranice članka
                it["title"] = real_title(it["link"]) or it["title"]
            post(f"📰 **{escape_md(it['title'])}**\n_{it['source']}_\n{it['link']}")
    finally:
        save_seen()  # sačuvaj i ako objava pukne na pola
    print(f"{time.strftime('%d.%m. %H:%M')} objavljeno {len(fresh)}")


if __name__ == "__main__":
    main()
