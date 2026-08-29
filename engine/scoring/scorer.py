"""Kalite cetveli uygulayıcı — v1 (Faz 1 ilk gerçek deneme).

Cetveller engine/scoring/rubrics/ altındaki jenerik ŞABLONLARDAN gelir; sihirbaz bunları
markaya uyarlayıp brandpack'e yazar. Puanlama her zaman brandpack'teki uyarlanmış cetvelle
yapılır ve cetvel sürümü çıktıya damgalanır (sürüm değişirse tüm sayfalar yeniden puanlanır).
NOT (v1): uyarlanmış cetvel henüz üretilmediği için şablon cetvel OLDUĞU GİBİ kullanılır ve
çıktı "şablon cetvel, uyarlanmamış" olarak damgalanır.

İki tip kriter:
- otomatik ölçülen: bu sürümde PUANLANIR (aşağıdaki AUTO_CHECKS; bir kısmı vekil/proxy
  ölçümdür ve notunda belirtilir).
- model yargısı gerektiren (auto: false): bu sürümde PUANLANMAZ; "değerlendirilmedi"
  olarak işaretlenir ve ağırlığı unassessed_weight'e yazılır. Toplam puan asla bu
  kriterler doluymuş gibi gösterilmez (docs/method.md dürüstlük kuralı).

Canlı paket kullanımı:
- terms.json: doğru terimler sınıflandırma ve alt-metin kontrolünde; tuzak terimler
  (traps) sayfa metninde mekanik olarak aranır → bulgu listesi.
- facts.json: sayfada geçen MOQ sayısı onaylı MOQ ile çelişiyorsa motor SEÇMEZ (§6),
  çelişkiyi bulgu olarak raporlar.

Jenerik motor kodu — marka bilgisi içermez (docs/method.md §9).
"""

from __future__ import annotations

import re

# URL yol kalıpları (sınıflandırma ve yönlendirme kontrolü ortak kullanır; jenerik)
PRODUCT_PATH = re.compile(r"/(urun|uerun|product|products|urunler|cozum|solution)", re.IGNORECASE)
SECTOR_PATH = re.compile(r"/(sektor|sector|industr|market|uygulama|application)", re.IGNORECASE)
BLOG_PATH = re.compile(r"/(blog|haber|news|makale|article|rehber|guide|20\d{2}/)", re.IGNORECASE)
# Arşiv/liste sayfaları: içerik cetveliyle puanlanmaz (kategori, yazar, sayfalama, blog dizini)
ARCHIVE_PATH = re.compile(
    r"/(category|kategori|categories|author|yazar)(/|$)"
    r"|/page/\d+(/|$)"
    r"|/blog(/\d+)?/?$",
    re.IGNORECASE,
)

# ---------------------------------------------------------------- yardımcılar

_MEASURE_RE = re.compile(r"\d+[.,]?\d*\s*(mm|cm|ml|cl|lt|gr?|kg|mikron|micron|gsm|oz)\b",
                         re.IGNORECASE)
_MOQ_RE = re.compile(
    r"(?:MOQ|minimum sipariş|asgari sipariş|minimum order(?: quantity)?)"
    r"[^0-9]{0,40}([\d.,]{3,12})",
    re.IGNORECASE,
)
_LEADTIME_RE = re.compile(
    r"((?:\d+\s*[-–]\s*\d+|\d+)\s*(?:iş günü|gün|hafta|business days?|days?|weeks?))",
    re.IGNORECASE,
)
_LEADTIME_CTX = re.compile(r"termin|teslim|üretim süre|lead time|delivery|turnaround",
                           re.IGNORECASE)
_CTA_RE = re.compile(
    r"teklif al|teklif iste|bize ulaşın|iletişime geç|numune iste|hemen ara|formu doldur"
    r"|get a quote|request a quote|contact us|get in touch|request a sample",
    re.IGNORECASE,
)
_CTA_LINK_RE = re.compile(r"iletisim|iletişim|contact|teklif|quote|offer", re.IGNORECASE)
_OPTIONS_RE = re.compile(
    r"baskı|ofset|offset|serigrafi|yaldız|foil|varnish|vernik|lamin|kapak|lid|cap"
    r"|varyant|seçenek|option|finish|emboss|deboss|çap|diameter",
    re.IGNORECASE,
)


def correct_terms(brandpack: dict) -> list[str]:
    """terms.json'daki doğru terimler (tüm diller, küçük harf)."""
    out = []
    for t in (brandpack.get("terms") or {}).get("terms", []):
        c = (t.get("correct") or "").strip().lower()
        if c:
            out.append(c)
    return out


def trap_terms(brandpack: dict) -> list[dict]:
    """terms.json'daki tuzak terimler: [{trap, correct, lang}]."""
    out = []
    for t in (brandpack.get("terms") or {}).get("terms", []):
        for trap in t.get("traps") or []:
            trap = (trap or "").strip()
            if trap:
                out.append({"trap": trap, "correct": t.get("correct", ""),
                            "lang": t.get("lang", "")})
    return out


def _word_re(phrase: str) -> re.Pattern:
    return re.compile(r"(?<!\w)" + re.escape(phrase.strip()) + r"(?!\w)", re.IGNORECASE)


def _page_links(page: dict) -> list[tuple[str, str]]:
    """links alanını (href, anchor) çiftlerine normalize eder.

    Tarayıcı {"url":…, "anchor":…} sözlükleri üretir; eski/test verisi
    (href, anchor) çifti olabilir. v1'deki hata: sözlükler çift gibi
    açılınca href="url", anchor="anchor" sabitleri geliyordu — iç link
    kriteri hep tek linke, CTA link fallback'i hiç bulguya düşüyordu.
    """
    out = []
    for it in page.get("links") or []:
        if isinstance(it, dict):
            out.append((it.get("url") or "", it.get("anchor") or ""))
        elif isinstance(it, (list, tuple)) and len(it) == 2:
            out.append((it[0] or "", it[1] or ""))
    return out


def _page_text(page: dict) -> str:
    parts = [page.get("title", ""), page.get("meta_description", "")]
    for hs in (page.get("headings") or {}).values():
        parts.extend(hs)
    parts.append(page.get("text", ""))
    return "\n".join(p for p in parts if p)


# ------------------------------------------------------- otomatik kriterler
# Her kontrol (page, brandpack) alır, (oran 0..1, not) döndürür.

def _check_spec_table(page: dict, bp: dict):
    n = len(_MEASURE_RE.findall(_page_text(page)))
    if n >= 3:
        return 1.0, f"{n} ölçü ifadesi (vekil ölçüm: tablo yapısı değil, ölçü yoğunluğu)"
    if n >= 1:
        return 0.5, f"{n} ölçü ifadesi (vekil ölçüm)"
    return 0.0, "ölçü/teknik veri ifadesi yok (vekil ölçüm)"


def _check_options(page: dict, bp: dict):
    n = len(set(m.group(0).lower() for m in _OPTIONS_RE.finditer(_page_text(page))))
    if n >= 3:
        return 1.0, f"{n} farklı seçenek/işlem terimi"
    if n >= 1:
        return 0.5, f"{n} seçenek terimi"
    return 0.0, "seçenek/baskı/son işlem bilgisi bulunamadı"


def _check_moq(page: dict, bp: dict):
    m = _MOQ_RE.search(_page_text(page))
    if m:
        return 1.0, f"MOQ ifadesi var: {m.group(0)[:60]!r}"
    return 0.0, "MOQ ifadesi yok"


def _check_lead_time(page: dict, bp: dict):
    text = _page_text(page)
    for m in _LEADTIME_RE.finditer(text):
        ctx = text[max(0, m.start() - 60):m.end() + 60]
        if _LEADTIME_CTX.search(ctx):
            return 1.0, f"termin ifadesi var: {m.group(0)!r}"
    return 0.0, "termin ifadesi yok"


def _check_cta(page: dict, bp: dict):
    if _CTA_RE.search(_page_text(page)):
        return 1.0, "dönüşüm çağrısı metni var"
    for href, anchor in _page_links(page):
        if _CTA_LINK_RE.search(href) or _CTA_LINK_RE.search(anchor):
            return 0.5, "yalnız menü/link düzeyinde iletişim bağlantısı"
    return 0.0, "dönüşüm çağrısı bulunamadı"


def _check_title_meta(page: dict, bp: dict):
    title = (page.get("title") or "").strip()
    meta = (page.get("meta_description") or "").strip()
    h1 = [h for h in (page.get("headings") or {}).get("h1", []) if h.strip()]
    score, notes = 0.0, []
    if 15 <= len(title) <= 70:
        score += 0.4
    elif title:
        score += 0.2
        notes.append(f"başlık {len(title)} karakter")
    else:
        notes.append("başlık yok")
    if 50 <= len(meta) <= 170:
        score += 0.4
    elif meta:
        score += 0.2
        notes.append(f"meta {len(meta)} karakter")
    else:
        notes.append("meta açıklama yok")
    if len(h1) == 1:
        score += 0.2
    else:
        notes.append(f"h1 sayısı {len(h1)}")
    notes.append("vekil ölçüm: gerçek sorgu uyumu GSC verisiyle Faz 2'de")
    return round(score, 2), "; ".join(notes)


def _check_alt_text(page: dict, bp: dict):
    alts = [a.lower() for a in page.get("images_alt") or []]
    if not alts:
        return 0.0, "alt metinli görsel yok"
    terms = correct_terms(bp)
    hit = sum(1 for a in alts if any(t in a for t in terms))
    if hit:
        return 1.0, f"{len(alts)} alt metin, {hit} tanesi ürün terimli"
    return 0.5, f"{len(alts)} alt metin var ama ürün terimi geçmiyor"


def _check_internal_links(page: dict, bp: dict):
    hrefs = {href for href, _ in _page_links(page) if href}
    n = len(hrefs)
    if n >= 3:
        return 1.0, f"{n} farklı iç bağlantı (vekil ölçüm: menü/gövde ayrımı yok)"
    if n >= 1:
        return 0.5, f"{n} iç bağlantı"
    return 0.0, "iç bağlantı yok"


def _check_product_links(page: dict, bp: dict):
    """Yönlendirme: ürün/sektör sayfalarına terimli iç link.

    Sayılan link: anchor'ında veya URL'sinde brandpack doğru terimi geçen,
    ya da URL'si ürün/sektör yol kalıbına uyan, sayfanın kendisi olmayan link.
    Vekil ölçüm: menü/gövde ayrımı yapılamıyor (notta belirtilir).
    """
    terms = correct_terms(bp)
    self_url = (page.get("url") or "").rstrip("/")
    hits = set()
    for href, anchor in _page_links(page):
        if not href or href.rstrip("/") == self_url:
            continue
        blob = f"{href} {anchor}".lower()
        if any(t in blob for t in terms) or PRODUCT_PATH.search(href) or SECTOR_PATH.search(href):
            hits.add(href)
    n = len(hits)
    if n >= 2:
        return 1.0, f"{n} ürün/sektör yönlendirme linki (vekil ölçüm: menü/gövde ayrımı yok)"
    if n == 1:
        return 0.6, "1 ürün/sektör yönlendirme linki"
    return 0.0, "ürün/sektör sayfasına terimli iç link yok"


AUTO_CHECKS = {
    "spec_table": _check_spec_table,
    "options": _check_options,
    "moq": _check_moq,
    "lead_time": _check_lead_time,
    "cta": _check_cta,
    "title_meta": _check_title_meta,
    "alt_text": _check_alt_text,
    "internal_links": _check_internal_links,
    "product_links": _check_product_links,
    "data_specificity": _check_spec_table,  # blog/sektör cetvelinde ölçü yoğunluğu vekili
}


# --------------------------------------------------------------- bulgular

def find_trap_terms(page: dict, brandpack: dict) -> list[dict]:
    """Tuzak terimleri sayfa metninde arar. Doğru terim geçişleri metinden
    çıkarılır ki doğru kullanım tuzak sanılmasın."""
    text = _page_text(page)
    for c in correct_terms(brandpack):
        text = _word_re(c).sub(" ", text)
    findings = []
    for t in trap_terms(brandpack):
        n = len(_word_re(t["trap"]).findall(text))
        if n:
            findings.append({"kind": "trap_term", "url": page.get("url", ""),
                             "trap": t["trap"], "correct": t["correct"], "count": n})
    return findings


def find_fact_conflicts(page: dict, brandpack: dict) -> list[dict]:
    """Sayfa ile onaylı facts çelişkisi — motor SEÇMEZ, raporlar (§6)."""
    findings = []
    facts = brandpack.get("facts") or {}
    approved = (facts.get("moq") or {}).get("baslangic_adet")
    if approved:
        for m in _MOQ_RE.finditer(_page_text(page)):
            raw = m.group(1).replace(".", "").replace(",", "")
            if raw.isdigit() and int(raw) != int(approved):
                findings.append({
                    "kind": "fact_conflict", "url": page.get("url", ""), "field": "moq",
                    "page_value": m.group(1), "approved_value": approved,
                    "note": "sayfadaki MOQ onaylı paketle çelişiyor — insan kararı gerekli (§6)",
                })
    return findings


# ----------------------------------------------------------------- puanlama

def score_page(page: dict, rubric: dict, brandpack: dict) -> dict:
    """Tek sayfayı cetvelle puanlar; kriter bazında döküm döndürür.

    v1: yalnız auto kriterler ölçülür; auto olmayanlar unassessed_weight'e gider.
    Kriter dökümü olmayan cetvellerde (sector/blog şablonu v1.0) genel otomatik
    kontroller uygulanır ve cetvel puanı üretilmez.
    """
    criteria_rows, auto_earned, auto_possible, unassessed = [], 0.0, 0.0, 0.0
    has_criteria = False
    for section in rubric.get("sections", []):
        for crit in section.get("criteria", []) or []:
            has_criteria = True
            key, weight = crit["key"], float(crit["weight"])
            if crit.get("auto") and key in AUTO_CHECKS:
                ratio, note = AUTO_CHECKS[key](page, brandpack)
                pts = round(weight * ratio, 1)
                auto_earned += pts
                auto_possible += weight
                criteria_rows.append({"key": key, "weight": weight, "auto": True,
                                      "ratio": ratio, "points": pts, "note": note})
            else:
                unassessed += weight
                criteria_rows.append({"key": key, "weight": weight, "auto": False,
                                      "ratio": None, "points": None,
                                      "note": "değerlendirilmedi (model yargısı — sonraki adım)"})
    result = {
        "url": page.get("url", ""),
        "rubric_type": rubric.get("type", ""),
        "rubric_version": str(rubric.get("version", "")),
        "rubric_note": "şablon cetvel, uyarlanmamış (v1)",
        "has_criteria": has_criteria,
        "auto_earned": round(auto_earned, 1),
        "auto_possible": round(auto_possible, 1),
        "unassessed_weight": round(unassessed, 1),
        "criteria": criteria_rows,
        "findings": find_trap_terms(page, brandpack) + find_fact_conflicts(page, brandpack),
    }
    return result
