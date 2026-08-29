"""Nazik site tarayıcısı (docs/method.md §8).

Jenerik motor kodu — marka bilgisi içermez. Kurallar:
- robots.txt'ye uyulur (User-agent: * kuralları).
- Düşük eşzamanlılık: sıralı tarama (tek istek), istekler arası bekleme.
- Acil durdurma anahtarı: ``config["crawler"]["kill_switch_file"]`` varsa tarama derhal durur.
- Sayfa tavanı: ``config["crawler"]["max_pages"]`` (varsayılan 30).
- Yalnız hedef alan adı (www'lu/www'suz aynı sayılır) taranır.
- Hedef sitenin önbellek/altyapı ayarlarına asla dokunulmaz; yalnız GET yapılır.

Harici bağımlılık yok — saf Python stdlib (urllib, html.parser).

Kullanım::

    from engine.sources.crawler import crawl
    pages = crawl({"site": {"url": "https://www.example.com"},
                   "crawler": {"delay_seconds": 3, "max_pages": 30}})

Dönen her kayıt: url, status, lang, title, meta_description, headings
(h1/h2/h3 listesi), text (görünür metin), links (aynı alan adındaki iç
bağlantılar), images_alt (alt metinleri), hreflang (dil -> url),
og_type (og:type meta değeri; WordPress yazılarda "article"),
published_time (article:published_time meta değeri, varsa),
ld_types (JSON-LD @type değerleri, küçük harf — og:type yanlış yapılandırılmış
sitelerde makale sinyali buradan gelir, ör. "article").
"""

from __future__ import annotations

import gzip
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import urllib.robotparser
from html.parser import HTMLParser

DEFAULT_UA = ("Mozilla/5.0 (compatible; ContentEngineDiscovery/0.1; "
              "+https://github.com/Karaca-Artas/content-engine)")

# İçerik taşımayan, taranması gereksiz yol kalıpları
SKIP_PATH = re.compile(
    r"\.(pdf|jpe?g|png|gif|webp|svg|ico|css|js|zip|rar|mp4|webm|woff2?|ttf|eot|xml|txt)($|\?)"
    r"|/wp-(admin|json|login)|/feed/?$|/tag/|/etiket/|\?(s|p|replytocom)=|#",
    re.IGNORECASE,
)


class _PageParser(HTMLParser):
    """Tek geçişte başlık, meta, h1-h3, görünür metin, bağlantı, alt ve hreflang toplar."""

    _SKIP_TAGS = {"script", "style", "noscript", "template", "svg", "head"}
    _BLOCK_TAGS = {"p", "div", "li", "br", "tr", "h1", "h2", "h3", "h4", "h5", "h6",
                   "section", "article", "header", "footer", "td", "th"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.title = ""
        self.meta_description = ""
        self.og_type = ""
        self.published_time = ""
        self.lang = ""
        self.headings: dict[str, list[str]] = {"h1": [], "h2": [], "h3": []}
        self.links: list[tuple[str, str]] = []  # (href, anchor metni)
        self.images_alt: list[str] = []
        self.hreflang: dict[str, str] = {}
        self.ld_types: list[str] = []
        self._in_ldjson = False
        self._ldjson_buf: list[str] = []
        self.text_parts: list[str] = []
        self._stack: list[str] = []
        self._cur_heading: str | None = None
        self._cur_link_href: str | None = None
        self._cur_link_text: list[str] = []
        self._in_title = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        a = dict(attrs)
        if tag == "html" and a.get("lang"):
            self.lang = (a["lang"] or "").split("-")[0].lower()
        elif tag == "meta":
            name = (a.get("name") or a.get("property") or "").lower()
            if name in ("description", "og:description") and a.get("content"):
                if not self.meta_description:
                    self.meta_description = a["content"].strip()
            elif name == "og:type" and a.get("content"):
                if not self.og_type:
                    self.og_type = a["content"].strip().lower()
            elif name == "article:published_time" and a.get("content"):
                if not self.published_time:
                    self.published_time = a["content"].strip()
        elif tag == "link":
            if (a.get("rel") or "").lower() == "alternate" and a.get("hreflang") and a.get("href"):
                self.hreflang[a["hreflang"].lower()] = a["href"]
        elif tag == "title":
            self._in_title = True
        elif tag in ("h1", "h2", "h3"):
            self._cur_heading = tag
            self.headings[tag].append("")
        elif tag == "a" and a.get("href"):
            self._cur_link_href = a["href"]
            self._cur_link_text = []
        elif tag == "img" and a.get("alt"):
            alt = a["alt"].strip()
            if alt:
                self.images_alt.append(alt)
        elif tag == "script" and (a.get("type") or "").lower() == "application/ld+json":
            self._in_ldjson = True
            self._ldjson_buf = []
        if tag in self._SKIP_TAGS:
            self._stack.append(tag)
        if tag in self._BLOCK_TAGS:
            self.text_parts.append("\n")

    def _flush_ldjson(self) -> None:
        """JSON-LD bloğundan @type değerlerini topla (bozuk JSON'da regex'e düş)."""
        raw = "".join(self._ldjson_buf).strip()
        self._in_ldjson = False
        self._ldjson_buf = []
        if not raw:
            return
        types: list[str] = []

        def walk(node):
            if isinstance(node, dict):
                t = node.get("@type")
                if isinstance(t, str):
                    types.append(t)
                elif isinstance(t, list):
                    types.extend(x for x in t if isinstance(x, str))
                for v in node.values():
                    walk(v)
            elif isinstance(node, list):
                for v in node:
                    walk(v)

        try:
            walk(json.loads(raw))
        except Exception:
            types.extend(re.findall(r'"@type"\s*:\s*"([^"]+)"', raw))
        for t in types:
            t = t.strip().lower()
            if t and t not in self.ld_types:
                self.ld_types.append(t)

    def handle_endtag(self, tag: str) -> None:
        if tag == "script" and self._in_ldjson:
            self._flush_ldjson()
        if tag == "title":
            self._in_title = False
        elif tag in ("h1", "h2", "h3"):
            self._cur_heading = None
        elif tag == "a" and self._cur_link_href is not None:
            self.links.append((self._cur_link_href, " ".join(self._cur_link_text).strip()))
            self._cur_link_href = None
            self._cur_link_text = []
        if self._stack and tag == self._stack[-1]:
            self._stack.pop()

    def handle_data(self, data: str) -> None:
        if self._in_title:  # <head> atlama yığınından ÖNCE — başlık head içindedir
            self.title += data
            return
        if self._in_ldjson:  # skip yığınından ÖNCE — script içeriği normalde atlanır
            self._ldjson_buf.append(data)
            return
        if self._stack:
            return
        if self._cur_heading and self.headings[self._cur_heading]:
            self.headings[self._cur_heading][-1] += data
        if self._cur_link_href is not None:
            self._cur_link_text.append(data.strip())
        self.text_parts.append(data)


def _norm_host(host: str) -> str:
    return host.lower().removeprefix("www.")


def _canon(url: str) -> str:
    """URL'yi karşılaştırma için sadeleştir (fragment ve sondaki / atılır)."""
    p = urllib.parse.urlsplit(url)
    path = p.path or "/"
    if path != "/" and path.endswith("/"):
        path = path[:-1]
    return urllib.parse.urlunsplit((p.scheme, p.netloc.lower(), path, p.query, ""))


def _fetch(url: str, timeout: int = 20) -> tuple[int, bytes, str]:
    req = urllib.request.Request(url, headers={
        "User-Agent": DEFAULT_UA,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.5",
        "Accept-Language": "tr,en;q=0.8",
    })
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        body = resp.read(2_500_000)  # sayfa başına ~2.5 MB tavan
        if resp.headers.get("Content-Encoding") == "gzip":
            body = gzip.decompress(body)
        ctype = resp.headers.get("Content-Type", "")
        return resp.status, body, ctype


def _decode(body: bytes, ctype: str) -> str:
    m = re.search(r"charset=([\w-]+)", ctype)
    for enc in ([m.group(1)] if m else []) + ["utf-8", "iso-8859-9", "latin-1"]:
        try:
            return body.decode(enc)
        except (UnicodeDecodeError, LookupError):
            continue
    return body.decode("utf-8", errors="replace")


def _sitemap_urls(base: str, timeout: int = 20, limit: int = 500,
                  extra: list[str] | None = None) -> list[str]:
    """Site haritalarını (ve indeks alt haritalarını) oku; bulunamazsa boş liste."""
    seen: list[str] = []
    queue = list(extra or []) + [
        urllib.parse.urljoin(base, "/sitemap.xml"),
        urllib.parse.urljoin(base, "/sitemap_index.xml"),
        urllib.parse.urljoin(base, "/sitemap-index.xml"),
        urllib.parse.urljoin(base, "/wp-sitemap.xml"),
    ]
    tried: set[str] = set()
    while queue and len(seen) < limit:
        sm = queue.pop(0)
        if sm in tried:
            continue
        tried.add(sm)
        try:
            status, body, ctype = _fetch(sm, timeout)
        except Exception:
            continue
        if status != 200:
            continue
        text = _decode(body, ctype)
        locs = re.findall(r"<loc>\s*([^<\s]+)\s*</loc>", text)
        if "<sitemapindex" in text:
            queue.extend(locs[:20])
        else:
            seen.extend(locs)
    return seen[:limit]


def crawl(config: dict, log=None) -> list[dict]:
    """Nazik tarama. ``config`` en az ``site.url`` içermeli.

    crawler alt anahtarları: delay_seconds (vars. 3), max_pages (vars. 30),
    kill_switch_file (vars. ".crawl-stop"), timeout (vars. 20),
    extra_seeds (ek başlangıç URL listesi).
    """
    log = log or (lambda msg: print(msg, file=sys.stderr))
    site_url = config["site"]["url"].rstrip("/")
    c = config.get("crawler", {})
    delay = float(c.get("delay_seconds", 3))
    max_pages = int(c.get("max_pages", 30))
    kill_file = c.get("kill_switch_file", ".crawl-stop")
    timeout = int(c.get("timeout", 20))

    root = urllib.parse.urlsplit(site_url)
    host = _norm_host(root.netloc)

    # robots.txt kendi UA'mızla okunur (varsayılan python UA bazı WAF'larca engellenir)
    rp: urllib.robotparser.RobotFileParser | None = urllib.robotparser.RobotFileParser()
    robots_sitemaps: list[str] = []
    try:
        st, body, ctype = _fetch(urllib.parse.urljoin(site_url, "/robots.txt"), timeout)
        if st == 200:
            text = _decode(body, ctype)
            rp.parse(text.splitlines())
            robots_sitemaps = re.findall(r"(?im)^sitemap:\s*(\S+)", text)
        else:
            rp = None
    except Exception as e:
        log(f"[crawler] robots.txt okunamadı ({e}) — nazik varsayılanlarla devam")
        rp = None

    queue: list[str] = [site_url + "/"]
    for u in _sitemap_urls(site_url, timeout, extra=robots_sitemaps):
        queue.append(u)
    queue.extend(c.get("extra_seeds", []))

    visited: set[str] = set()
    pages: list[dict] = []

    while queue and len(pages) < max_pages:
        if os.path.exists(kill_file):
            log(f"[crawler] acil durdurma anahtarı bulundu ({kill_file}) — tarama durdu.")
            break
        url = queue.pop(0)
        cu = _canon(url)
        if cu in visited:
            continue
        p = urllib.parse.urlsplit(url)
        if p.scheme not in ("http", "https") or _norm_host(p.netloc) != host:
            continue
        if SKIP_PATH.search(p.path + ("?" + p.query if p.query else "")):
            continue
        if rp is not None and not rp.can_fetch(DEFAULT_UA, url):
            visited.add(cu)
            continue
        visited.add(cu)
        try:
            status, body, ctype = _fetch(url, timeout)
        except urllib.error.HTTPError as e:
            log(f"[crawler] HATA {e.code} {url}")
            pages.append({"url": url, "status": e.code, "error": "http"})
            time.sleep(delay)
            continue
        except Exception as e:
            log(f"[crawler] HATA {url}: {str(e)[:120]}")
            pages.append({"url": url, "status": 0, "error": str(e)[:200]})
            time.sleep(delay)
            continue
        if "html" not in ctype:
            time.sleep(delay)
            continue

        parser = _PageParser()
        try:
            parser.feed(_decode(body, ctype))
        except Exception as e:
            pages.append({"url": url, "status": status, "error": f"parse: {e}"[:200]})
            time.sleep(delay)
            continue

        text = re.sub(r"[ \t]+", " ", "".join(parser.text_parts))
        text = re.sub(r"\s*\n\s*", "\n", text).strip()

        internal_links = []
        for href, anchor in parser.links:
            absu = urllib.parse.urljoin(url, href)
            ap = urllib.parse.urlsplit(absu)
            if ap.scheme in ("http", "https") and _norm_host(ap.netloc) == host:
                if not SKIP_PATH.search(ap.path):
                    internal_links.append({"url": _canon(absu), "anchor": anchor[:120]})
                    if _canon(absu) not in visited:
                        queue.append(absu)

        pages.append({
            "url": url,
            "status": status,
            "lang": parser.lang,
            "title": parser.title.strip(),
            "meta_description": parser.meta_description,
            "headings": {k: [h.strip() for h in v if h.strip()] for k, v in parser.headings.items()},
            "text": text[:20000],
            "links": internal_links[:200],
            "images_alt": parser.images_alt[:50],
            "hreflang": parser.hreflang,
            "og_type": parser.og_type,
            "published_time": parser.published_time,
            "ld_types": parser.ld_types[:20],
        })
        log(f"[crawler] {len(pages)}/{max_pages} {url} ({status})")
        time.sleep(delay)

    return pages
