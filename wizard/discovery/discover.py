"""Kaynak keşfi — Faz 0, Tur 1 (wizard/README.md).

Verilen site adresini nazik tarayıcıyla (engine/sources/crawler.py) gezer ve
TASLAK bilgi paketi türetir. Çıktılar `brandpack/draft/` altına yazılır:

- ``facts.draft.json``   — facts.schema.json ile uyumlu taslak + aday kanıtları
- ``terms.draft.json``   — terms.schema.json ile uyumlu taslak terim sözlüğü
- ``open_questions.json``— Tur 2 (dinamik teyit) soru listesi: boşluklar + çelişkiler
- ``pages.json``         — (isteğe bağlı, --save-pages) ham tarama dökümü

İlkeler (docs/method.md):
- §6  Çelişkide motor SEÇMEZ, ORTALAMAZ — soru üretir.
- §9  Sıfır-başlangıç: bu kod marka bilgisi içermez; her şey siteden/kaynaktan
      aday olarak çıkarılır ve kullanıcı onayına sunulur. Taslak, onay olmadan
      ``brandpack/live/``e ASLA kopyalanmaz.

Kullanım::

    python -m wizard.discovery.discover https://www.example.com \
        --max-pages 30 --delay 3 --out brandpack/draft

Harici bağımlılık yok (saf stdlib).
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import re
import sys
from collections import Counter, defaultdict

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
from engine.sources.crawler import crawl  # noqa: E402

# --- Jenerik kalıplar (marka verisi değil, yöntem kuralı) --------------------

CERT_PATTERNS = [
    r"\bISO[ -]?\d{4,5}(?::\d{4})?\b",
    r"\bBRC(?:GS)?\b", r"\bFSC\b", r"\bPEFC\b", r"\bSEDEX\b", r"\bSMETA\b",
    r"\bHACCP\b", r"\bGMP\b", r"\bOEKO[- ]?TEX\b", r"\bFDA\b", r"\bTSE\b",
    r"\bCE\b(?=[\s,.;)]|$)", r"\bEcoVadis\b", r"\bGRS\b",
]
CERT_RE = re.compile("|".join(CERT_PATTERNS))

MOQ_RE = re.compile(
    r"(?:MOQ|minimum sipariş|asgari sipariş|minimum order(?: quantity)?)"
    r"[^0-9]{0,40}([\d.,]{3,12})",
    re.IGNORECASE,
)
LEADTIME_RE = re.compile(
    r"((?:\d+\s*[-–]\s*\d+|\d+)\s*(?:iş günü|gün|hafta|business days?|days?|weeks?))",
    re.IGNORECASE,
)
LEADTIME_CTX = re.compile(r"termin|teslim|üretim süre|lead time|delivery|turnaround", re.IGNORECASE)

PRODUCT_PATH = re.compile(r"/(urun|uerun|product|products|urunler|cozum|solution)", re.IGNORECASE)
SECTOR_PATH = re.compile(r"/(sektor|sector|industr|market)", re.IGNORECASE)
REFERENCE_PATH = re.compile(r"/(referans|reference|clients|musteri)", re.IGNORECASE)

# Terim adayları için küçük jenerik gürültü listeleri (dil kuralı, marka verisi değil)
STOP = {
    "tr": {"ve", "ile", "için", "bir", "bu", "da", "de", "olarak", "daha", "en", "gibi",
           "veya", "tüm", "her", "biz", "size", "sizin", "olan", "hakkında", "ana", "sayfa",
           "iletişim", "hakkımızda", "devamı", "detay", "tıklayın", "copyright", "tüm hakları"},
    "en": {"and", "the", "for", "with", "our", "your", "from", "that", "this", "are", "more",
           "all", "home", "about", "contact", "read", "learn", "us", "we", "you", "of", "in",
           "to", "on", "a", "an", "is", "or", "by", "at", "as", "be", "it", "its"},
}
WORD_RE = re.compile(r"[A-Za-zÇĞİÖŞÜçğıöşü][A-Za-zÇĞİÖŞÜçğıöşü-]{2,}")


def _today() -> str:
    return _dt.date.today().isoformat()


def _brand_name(pages: list[dict]) -> tuple[str, list[str]]:
    """Başlık soneklerinden marka adı adayı çıkar ('Sayfa | Marka' kalıbı)."""
    tails: Counter[str] = Counter()
    for p in pages:
        t = p.get("title") or ""
        parts = re.split(r"\s*[|•·–—-]\s+", t)
        if len(parts) >= 2 and parts[-1].strip():
            tails[parts[-1].strip()] += 1
    if not tails:
        for p in pages:
            if p.get("title"):
                return p["title"].strip()[:80], ["tek kaynak: ilk sayfa başlığı"]
        return "", ["site başlıklarından marka adı çıkarılamadı"]
    best, n = tails.most_common(1)[0]
    return best, [f"{n} sayfa başlığının sonekinde geçiyor"]


def _lang_of(page: dict, default: str) -> str:
    return (page.get("lang") or default or "und")[:2]


def _collect(pages: list[dict], default_lang: str) -> dict:
    """Sayfalardan aday olguları topla; her adaya kanıt (url) iliştir."""
    out: dict = {
        "products": defaultdict(set),      # ad -> kanıt url'leri
        "sectors": defaultdict(set),
        "references": defaultdict(set),
        "certificates": defaultdict(set),
        "moq": defaultdict(set),           # değer -> kanıt url'leri
        "lead_times": defaultdict(set),
        "languages": set(),
        "terms": defaultdict(Counter),     # lang -> Counter(kelime)
        "term_pages": defaultdict(lambda: defaultdict(set)),  # lang -> kelime -> url'ler
    }
    ok_pages = [p for p in pages if p.get("status") == 200 and not p.get("error")]
    for p in ok_pages:
        url = p["url"]
        lang = _lang_of(p, default_lang)
        out["languages"].add(lang)
        for hl in p.get("hreflang", {}):
            out["languages"].add(hl.split("-")[0])

        h1s = p.get("headings", {}).get("h1", [])
        if PRODUCT_PATH.search(url):
            for h in h1s or p.get("headings", {}).get("h2", [])[:1]:
                out["products"][h.strip()[:100]].add(url)
        if SECTOR_PATH.search(url):
            for h in h1s:
                out["sectors"][h.strip()[:100]].add(url)
        if REFERENCE_PATH.search(url):
            for h in p.get("headings", {}).get("h2", []) + p.get("headings", {}).get("h3", []):
                out["references"][h.strip()[:80]].add(url)
            for alt in p.get("images_alt", []):
                if 2 < len(alt) < 60:
                    out["references"][alt.strip()].add(url)

        blob = " ".join([p.get("title", ""), p.get("meta_description", ""),
                         " ".join(sum(p.get("headings", {}).values(), [])),
                         p.get("text", "")])
        for m in CERT_RE.finditer(blob):
            out["certificates"][m.group(0).upper().replace("  ", " ")].add(url)
        for m in MOQ_RE.finditer(blob):
            out["moq"][m.group(1).strip(".,")].add(url)
        for m in LEADTIME_RE.finditer(blob):
            s, e = max(0, m.start() - 60), m.end() + 20
            if LEADTIME_CTX.search(blob[s:e]):
                out["lead_times"][m.group(1).lower()].add(url)

        head_text = " ".join([p.get("title", "")] + sum(p.get("headings", {}).values(), []))
        stop = STOP.get(lang, set())
        for w in WORD_RE.findall(head_text):
            lw = w.lower()
            if lw not in stop and len(lw) > 3:
                out["terms"][lang][lw] += 1
                out["term_pages"][lang][lw].add(url)
    return out


def _ev(urls: set[str], cap: int = 3) -> list[str]:
    return sorted(urls)[:cap]


def build_drafts(pages: list[dict], site_url: str, default_lang: str = "") -> tuple[dict, dict, list[dict]]:
    """Tarama sonuçlarından (facts, terms, open_questions) taslaklarını üret."""
    today = _today()
    got = _collect(pages, default_lang)
    brand, brand_ev = _brand_name(pages)
    questions: list[dict] = []

    def q(topic: str, question: str, why: str, evidence: list[str] | None = None) -> None:
        questions.append({"topic": topic, "question": question, "why": why,
                          "evidence": evidence or []})

    # --- facts taslağı (facts.schema.json ile uyumlu; ek alanlar taslak meta) ---
    products = [{"name": name, "evidence": _ev(urls)}
                for name, urls in sorted(got["products"].items(), key=lambda kv: -len(kv[1]))
                if name][:40]
    moq_vals = sorted(got["moq"].items(), key=lambda kv: -len(kv[1]))
    moq: int | None = None
    if len(moq_vals) == 1:
        try:
            moq = int(re.sub(r"[.,]", "", moq_vals[0][0]))
        except ValueError:
            moq = None
        q("moq", f"Sitede MOQ olarak '{moq_vals[0][0]}' görünüyor. Doğru ve güncel mi?",
          "Tek kaynaklı aday — onaysız gerçek sayılamaz (§9).", _ev(moq_vals[0][1]))
    elif len(moq_vals) > 1:
        listing = " · ".join(f"'{v}' ({len(u)} sayfa)" for v, u in moq_vals[:4])
        q("moq", f"Sitede birbiriyle çelişen MOQ değerleri var: {listing}. Hangisi geçerli?",
          "ÇELİŞKİ — motor seçmez, ortalamaz (§6).",
          sum((_ev(u, 2) for _, u in moq_vals[:4]), []))
    else:
        q("moq", "Sitede MOQ (asgari sipariş adedi) bulunamadı. Nedir? (ürün bazında farklıysa belirtin)",
          "Boşluk — facts.json zorunlu bilgisi.")

    lead_times = {}
    lt_vals = sorted(got["lead_times"].items(), key=lambda kv: -len(kv[1]))
    if lt_vals:
        lead_times = {"aday": lt_vals[0][0]}
        if len(lt_vals) > 1:
            listing = " · ".join(f"'{v}' ({len(u)} sayfa)" for v, u in lt_vals[:5])
            q("lead_times", f"Sitede birden çok termin ifadesi geçiyor: {listing}. "
              "Hangi iş tipine hangisi ait? (standart / baskılı / yoğun sezon)",
              "ÇELİŞKİ/BELİRSİZLİK — iş tipine bağlanmadan kullanılamaz (§6).",
              sum((_ev(u, 2) for _, u in lt_vals[:5]), []))
        else:
            q("lead_times", f"Termin olarak '{lt_vals[0][0]}' görünüyor. Hangi iş tipi için geçerli, "
              "diğer iş tiplerinin terminleri neler?", "Tek aday — iş tipi eşlemesi eksik.",
              _ev(lt_vals[0][1]))
    else:
        q("lead_times", "Sitede termin (teslim süresi) bilgisi bulunamadı. İş tiplerine göre terminler neler?",
          "Boşluk — facts.json bilgisi.")

    certificates = sorted(got["certificates"], key=lambda k: -len(got["certificates"][k]))
    if certificates:
        q("certificates", f"Şu sertifika adayları bulundu: {', '.join(certificates)}. "
          "Hangileri güncel ve geçerli? Eksik olan var mı?",
          "Aday listesi — belge geçerliliği siteden doğrulanamaz.",
          sum((_ev(got["certificates"][c], 1) for c in certificates[:6]), []))
    else:
        q("certificates", "Sitede sertifika/belge bulunamadı. Varsa listeleyin.", "Boşluk.")

    references = [r for r in sorted(got["references"], key=lambda k: -len(got["references"][k]))
                  if r][:30]
    if references:
        q("named_references", "Referans sayfasından şu adaylar çıkarıldı: "
          + ", ".join(references[:15]) + (" …" if len(references) > 15 else "")
          + ". Hangileri İSİM VEREREK kullanılabilir (yazılı izin)?",
          "İsim verilebilirlik siteden anlaşılamaz — izin onayı gerekir.")
    else:
        q("named_references", "İsim verilebilir referans bulunamadı. Var mı; hangileri yazılı izinli?",
          "Boşluk.")

    q("not_offered", "YAPILMAYAN işler neler? (içerikte asla vaat edilmemesi gerekenler)",
      "Siteden çıkarılamaz — yalnız kullanıcı bilir; facts.json'un kritik alanı.")
    if products:
        q("products", "Üründen/hizmet adaylarının listesi doğru ve tam mı? "
          "(facts.draft.json → products) Eksik/yanlış olanları belirtin.",
          "H1 temelli otomatik çıkarım — onay gerekli.")
    else:
        q("products", "Ürün/hizmet sayfası deseni bulunamadı; ürün listenizi yazar mısınız?",
          "Boşluk — otomatik çıkarım sonuç vermedi.")

    facts = {
        "brand_name": brand,
        "approved_at": today,
        "products": products,
        "moq": moq,
        "lead_times": lead_times,
        "certificates": certificates,
        "named_references": [],  # izin onayı olmadan boş kalır — adaylar soruda
        "not_offered": [],       # yalnız kullanıcıdan gelir
        "_draft": {
            "status": "TASLAK — Tur 2 onayı olmadan geçerli değil",
            "generated_at": today,
            "source_site": site_url,
            "pages_crawled": len([p for p in pages if p.get("status") == 200]),
            "brand_name_evidence": brand_ev,
            "reference_candidates": references,
            "sector_candidates": [{"name": s, "evidence": _ev(u)}
                                  for s, u in sorted(got["sectors"].items(),
                                                     key=lambda kv: -len(kv[1]))][:20],
        },
    }

    # --- terms taslağı ---
    langs = sorted(l for l in got["languages"] if l and l != "und")
    terms = []
    for lang in langs or ["und"]:
        for word, n in got["terms"].get(lang, Counter()).most_common(25):
            if n < 2:
                continue
            terms.append({
                "lang": lang, "correct": word, "traps": [],
                "evidence": f"keşif adayı: {n} kez başlık/başlıklarda; onaysız — SERP doğrulaması Tur 2'de",
            })
    terms_draft = {
        "languages": langs,
        "terms": terms,
        "_draft": {"status": "TASLAK — SERP kanıtı ve tuzak terim çalışması Tur 2'de",
                   "generated_at": today},
    }
    if terms:
        q("terms", "Terim adayları başlıklardan sıklıkla çıkarıldı (terms.draft.json). "
          "Sektörünüzde YANLIŞ ürüne giden tuzak terimler var mı?",
          "Tuzak terimler ancak sektör bilgisiyle belirlenir; SERP doğrulaması Tur 2'de.")

    # sorulara tarih + kaynak etiketi
    for item in questions:
        item["date"] = today
        item["round"] = 2
    return facts, terms_draft, questions


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Kaynak keşfi: siteden taslak bilgi paketi türetir.")
    ap.add_argument("site_url", help="Marka web sitesi (https://...)")
    ap.add_argument("--max-pages", type=int, default=30)
    ap.add_argument("--delay", type=float, default=3.0)
    ap.add_argument("--lang", default="", help="Varsayılan dil (html lang yoksa)")
    ap.add_argument("--out", default="brandpack/draft", help="Çıktı klasörü")
    ap.add_argument("--save-pages", action="store_true", help="Ham tarama dökümünü de yaz (pages.json)")
    ap.add_argument("--kill-switch", default=".crawl-stop")
    args = ap.parse_args(argv)

    config = {
        "site": {"url": args.site_url},
        "crawler": {"delay_seconds": args.delay, "max_pages": args.max_pages,
                    "kill_switch_file": args.kill_switch},
    }
    pages = crawl(config)
    facts, terms, questions = build_drafts(pages, args.site_url, args.lang)

    os.makedirs(args.out, exist_ok=True)
    def w(name: str, obj) -> None:
        path = os.path.join(args.out, name)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(obj, f, ensure_ascii=False, indent=2)
        print(f"[discover] yazıldı: {path}", file=sys.stderr)

    w("facts.draft.json", facts)
    w("terms.draft.json", terms)
    w("open_questions.json", questions)
    if args.save_pages:
        w("pages.json", pages)

    print(f"[discover] {facts['_draft']['pages_crawled']} sayfa tarandı · "
          f"{len(facts['products'])} ürün adayı · {len(facts['certificates'])} sertifika adayı · "
          f"{len(terms['terms'])} terim adayı · {len(questions)} teyit sorusu", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
