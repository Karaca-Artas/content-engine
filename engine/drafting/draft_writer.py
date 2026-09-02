"""Kapı 1/2 içerik taslağı üreticisi — aksiyon kuyruğundan B2B taslak (Adım 18).

Girdi: Kanal C aksiyon kuyruğu (results/actions/latest.json) satırı + marka
paketi (onaylı gerçekler, terim sözlüğü, ret hafızası, sık-sorular, uyarlanmış
cetvel) + hedef sayfanın CANLI içeriği. Çıktı: docs/results-contract.md
"draft-result" v1.0 — results/drafts/{latest.json, latest.md, index.json,
history/<id>.{json,md}}.

Kutu → üretim tipi (docs/method.md dört kutu kuralı):
- enrich      → yeni yazı DEĞİL, "sayfaya eklenecek bölümler paketi" (mevcut
                sayfa + bölümler birlikte cetvelden geçer). Tam taslak yalnız
                (d) yeni sayfa içindir ve (d) otomatik atanmaz.
- title_meta  → 3 başlık + meta açıklama önerisi (varyant).
- merge_or_remove / new_page → bu araç ÜRETMEZ (insan kararı / Kapı 1 seçimi).

Değişmez kurallar (skill + docs/method.md):
1. DOĞRULUK KAPISI (model sonrası, deterministik): taslakta tuzak/yasaklı
   terim taraması + MOQ/termin çelişki taraması (onaylı gerçeklere karşı) +
   ret hafızası kontrolü. İhlal → durum "accuracy_failed"; taslak yine
   kaydedilir (ne yakalandığı görünür) ama onaya sunulamaz.
2. 70 SELF-CHECK: taslak uygulanmış sayfa (mevcut sayfa + bölümler / yeni
   başlık-meta) aynı cetvel + aynı sabit rubrikle puanlanır. Görsel kriterler
   taslak aşamasında DEĞERLENDİRİLEMEZ (sahte görsel üretilmez — skill görsel
   kuralı); değerlendirilemeyen ağırlık kapı paydasından düşülür ve gerekli
   görseller insan görevi olarak listelenir. Kapı puanı = (oto + model) /
   (değerlendirilebilir ağırlık). NOT: bu kapı puanı YAYIN EŞİĞİ içindir;
   sayfa karnelerindeki "oto ve model ayrı gösterilir" kuralının yerine
   geçmez, sonuç dosyasında iki bileşen ayrı da durur.
3. Model onaylı gerçeklerin DIŞINDA sayı/süre/iddia üretemez; bilgi yoksa
   metne "[BİLGİ GEREKLİ: ...]" yer tutucusu yazar → durum "needs_input".
4. Yayın dili kuralı marka kararıdır ve PAKET/İŞ AKIŞINDAN gelir
   (--publish-languages); kural dışı dildeki sayfa için koşu BAŞARISIZ olur
   (motor kural çiğneyen taslağı sessizce üretmez).
5. Motor YAYINLAMAZ. Çıktı taslaktır; onay insandadır (teslim: Drive+e-posta).

API: Anthropic Messages API; anahtar ANTHROPIC_API_KEY (Adım 10 kararı —
sıfır-secret deseninin bilinçli tek istisnası). Yazım modeli varsayılanı
Sonnet (metin kalitesi), self-check yargısı judge varsayılanı (Haiku).

Jenerik motor kodu — marka bilgisi içermez (docs/method.md §9).
Bağımlılık: PyYAML (cetveller); kalanı stdlib.

Kullanım (Actions'ta, marka deposunda)::

    python engine-repo/engine/drafting/draft_writer.py \
        --site https://www.example.com \
        --queue-latest results/actions/latest.json --rank 1 \
        --brandpack-dir brandpack/live \
        --rubrics-dir engine-repo/engine/scoring/rubrics \
        --publish-languages tr,en --default-lang tr \
        --out-dir results/drafts --summary rapor.md
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
from engine.channels.channel_c_synthesis import (  # noqa: E402
    is_rejected, load_rejections)
from engine.performance.perf_scan import norm_path  # noqa: E402
from engine.scoring.judge import (  # noqa: E402
    API_URL, API_VERSION, DEFAULT_MODEL as DEFAULT_JUDGE_MODEL, Judge,
    load_prompts)
from engine.scoring.quality_scan import (  # noqa: E402
    DEFAULT_JUDGE_PROMPTS, load_brandpack, load_effective_rubrics)
from engine.scoring.scorer import (  # noqa: E402
    find_fact_conflicts, find_trap_terms, score_page)
from engine.sources.crawler import (  # noqa: E402
    _PageParser, _content_images, _decode, _fetch)

CONTRACT = "draft-result"
CONTRACT_INDEX = "draft-index"
CONTRACT_VERSION = "1.0"

DEFAULT_WRITER_MODEL = "claude-sonnet-4-5"
DEFAULT_THRESHOLD = 70.0
ALLOWED_BOXES = ("enrich", "title_meta")
MAX_FAQ_LINES = 20
PLACEHOLDER_RE = re.compile(r"\[B[İI]LG[İI] GEREKL[İI][^\]]*\]")
_FENCE_RE = re.compile(r"^```[a-zA-Z]*\s*|\s*```$")
_LANG_PREFIX_RE = re.compile(r"^/([a-z]{2})(/|$)", re.IGNORECASE)

# Sayfa tipine göre ton (jenerik yöntem kuralı — docs/method.md yazım kuralları)
TONE_BY_TYPE = {
    "product_page": "teknik-uzman: ölçü, tolerans, gramaj konuşur; süsleme yok",
    "sector_page": "teknik-uzman: ölçü, tolerans, gramaj konuşur; süsleme yok",
    "blog_post": "danışman-satıcı: alıcının problemiyle başlar, çözüme bağlar",
}
DEFAULT_TONE = "açık, pratik, profesyonel B2B dili"
LENGTH_BY_TYPE = {
    "product_page": "sayfanın TAMAMI 700-1.100 kelime bandında kalmalı (tavan, hedef değil)",
    "sector_page": "sayfanın TAMAMI 700-1.100 kelime bandında kalmalı (tavan, hedef değil)",
    "blog_post": "yazının TAMAMI 1.200-1.800 kelime bandında kalmalı (tavan, hedef değil)",
}


# ---------------------------------------------------------------- yardımcılar

def _read_json(path: str):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def _write_json(path: str, data: dict) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
        f.write("\n")


def _write_text(path: str, text: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


def page_language(page: dict, path: str, default_lang: str) -> str:
    """Sayfa dili: html lang özniteliği > URL dil öneki (/en/, /fr/ …) >
    site varsayılanı. Küçük harf iki-harf kod döner."""
    lang = (page.get("lang") or "").strip().lower()
    if lang:
        return lang.split("-")[0][:2]
    m = _LANG_PREFIX_RE.match(path or "")
    if m:
        return m.group(1).lower()
    return (default_lang or "tr").strip().lower()


def pick_row(queue_doc: dict, rank: int, path_override: str) -> tuple[dict | None, str]:
    """Kuyruk satırı seçimi. path_override verilirse kuyruk+bekleme listesinde
    aranır; yoksa rank ile kuyruğdan alınır. (satır, hata) döner."""
    rows = list(queue_doc.get("queue") or [])
    pool = rows + list(queue_doc.get("waiting") or [])
    if path_override:
        target = norm_path(path_override)
        for r in pool:
            if norm_path(r.get("path", "")) == target:
                return r, ""
        return None, (f"'{path_override}' kuyruğda/bekleme listesinde yok — "
                      "taslak yalnız kuyruğa girmiş sayfalar için üretilir "
                      "(Kapı 1 disiplini)")
    for r in rows:
        if r.get("rank") == rank:
            return r, ""
    return None, f"kuyrukta {rank}. satır yok (kuyruk {len(rows)} satır)"


def fetch_page(url: str, timeout: int = 20) -> dict:
    """Tek sayfayı tarayıcının ayrıştırıcısıyla çeker (crawl ile aynı alanlar).
    Hata → {"url", "status", "error"}."""
    try:
        status, body, ctype = _fetch(url, timeout)
    except urllib.error.HTTPError as e:
        return {"url": url, "status": e.code, "error": "http"}
    except Exception as e:  # noqa: BLE001 — tek sayfa; neden rapora yazılır
        return {"url": url, "status": 0, "error": str(e)[:200]}
    parser = _PageParser()
    try:
        parser.feed(_decode(body, ctype))
    except Exception as e:  # noqa: BLE001
        return {"url": url, "status": status, "error": f"parse: {e}"[:200]}
    text = re.sub(r"[ \t]+", " ", "".join(parser.text_parts))
    text = re.sub(r"\s*\n\s*", "\n", text).strip()
    return {
        "url": url, "status": status, "lang": parser.lang,
        "title": parser.title.strip(),
        "meta_description": parser.meta_description,
        "headings": {k: [h.strip() for h in v if h.strip()]
                     for k, v in parser.headings.items()},
        "text": text[:20000],
        "links": [], "images_alt": parser.images_alt[:50],
        "images": _content_images(url, parser.images),
        "og_type": parser.og_type, "published_time": parser.published_time,
        "ld_types": parser.ld_types[:20],
    }


# ------------------------------------------------------------- yazım isteği

def faq_block(brandpack: dict) -> str:
    """Anonim sık-soru bölümü (sıklık × yenilik — judge ile aynı ağırlık)."""
    cq = brandpack.get("customer_questions") or {}
    qs = [q for q in cq.get("questions", []) if isinstance(q, dict)]
    if not qs:
        return ""
    ref = str((cq.get("coverage") or {}).get("to", ""))
    qs.sort(key=lambda q: (-Judge._faq_weight(q, ref), str(q.get("question", ""))))
    lines = []
    for q in qs[:MAX_FAQ_LINES]:
        meta = (f"sıklık {q.get('frequency', '?')}, "
                f"{q.get('first_seen', '?')}–{q.get('last_seen', '?')}")
        if q.get("languages"):
            meta += "; dil: " + ",".join(map(str, q["languages"]))
        if q.get("products"):
            meta += "; ürün: " + ", ".join(map(str, q["products"]))
        lines.append(f"- {q.get('question', '')} ({meta})")
    return ("=== MÜŞTERİ SIK-SORU LİSTESİ (anonim; en ağırlıklı "
            f"{len(lines)}) ===\n" + "\n".join(lines) + "\n\n")


def rubric_lines(rubric: dict) -> str:
    out = []
    for section in rubric.get("sections", []):
        for c in section.get("criteria", []) or []:
            line = f"- {c['key']} (ağırlık {c['weight']}): {c.get('desc', '')}"
            if c.get("brand_context"):
                line += f" | Marka bağlamı: {c['brand_context']}"
            out.append(line)
    return "\n".join(out)


class DraftWriter:
    """Tek kuyruk satırı için taslak üretir (Anthropic Messages API)."""

    def __init__(self, model: str, api_key: str, timeout: float = 240.0,
                 delay: float = 1.0):
        self.model = model
        self.api_key = api_key
        self.timeout = timeout
        self.delay = delay
        self.requests = 0
        self.failures = 0

    def _post(self, body: dict) -> dict:
        """API çağrısı — testlerde taklit edilir (monkeypatch)."""
        req = urllib.request.Request(
            API_URL, data=json.dumps(body).encode("utf-8"),
            headers={"content-type": "application/json",
                     "x-api-key": self.api_key,
                     "anthropic-version": API_VERSION},
            method="POST")
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:
            return json.load(resp)

    # ---- istem kurulumu

    @staticmethod
    def system_prompt(language: str) -> str:
        return (
            "Sen B2B üretici sitesi için içerik taslağı yazan bir yazarsın. "
            "DEĞİŞMEZ kurallar:\n"
            "1. SAYI, SÜRE, SERTİFİKA, REFERANS ve TİCARİ İDDİA yalnız sana "
            "verilen MARKA BAĞLAMINDAN (onaylı gerçekler) gelebilir. Orada "
            "olmayan bir bilgi gerekiyorsa UYDURMA; metne tam olarak şu "
            "biçimde yer tutucu yaz: [BİLGİ GEREKLİ: <ne gerektiği>].\n"
            "2. Muhatap her zaman profesyoneldir (satın almacı, ambalaj "
            "müdürü, marka sahibi, ajans); son tüketiciye yazan cümle "
            "kurma. Her bölüm bir satın alma sorusunu cevaplasın: kaç "
            "adetten, ne kadar sürede, hangi belgeyle, hangi maliyet "
            "farkıyla. Adet dili çoğuldur: 'seri', 'SKU başına'.\n"
            "3. Birinci ağızdan fabrika anlatımı (biz-üretiyoruz tonu) tam "
            "metin boyunca KULLANILMAZ; sahte durur. Gerçek alıntı gerekiyorsa "
            "insan görevi olarak işaretle.\n"
            "4. Sahte görsel, sahte teknik çizim, sahte fotoğraf ÜRETME ve "
            "varmış gibi yazma; gereken görseli insan görevi olarak listele.\n"
            "5. Terim sözlüğündeki tuzak/yasaklı terimleri KULLANMA; doğru "
            "terimleri kullan.\n"
            f"6. Taslak dili: {language} (sayfanın kendi dili).\n"
            "7. Yanıtın SADECE geçerli JSON olsun; başka hiçbir metin veya "
            "kod bloğu işareti ekleme.")

    @staticmethod
    def _brand_context(brandpack: dict) -> str:
        ctx = {}
        if brandpack.get("facts"):
            ctx["onayli_gercekler"] = brandpack["facts"]
        if brandpack.get("terms"):
            ctx["terim_sozlugu"] = brandpack["terms"]
        return json.dumps(ctx, ensure_ascii=False, separators=(",", ":"))

    def user_prompt(self, row: dict, page: dict, rubric: dict,
                    brandpack: dict, language: str) -> str:
        box = row.get("box")
        ptype = row.get("type", "")
        tone = TONE_BY_TYPE.get(ptype, DEFAULT_TONE)
        length = LENGTH_BY_TYPE.get(ptype, "kısa ve öz; dolgu metin yazma")
        missing = ", ".join(
            f"{m['key']} (eksik {m['gap']}/{m['weight']})"
            for m in row.get("missing_criteria") or []) or "—"
        heads = page.get("headings") or {}
        head_txt = " | ".join(heads.get("h2", [])[:15])
        if box == "enrich":
            task = (
                "GÖREV: Bu MEVCUT sayfaya eklenecek bölümler paketi üret "
                "(yeni yazı DEĞİL). Amaç, sayfanın cetvel eksiklerini "
                "kapatmak — özellikle eksik kriterler listesindekileri. "
                "JSON biçimi:\n"
                '{"sections": [{"heading": "...", "body_markdown": "...", '
                '"addresses": ["kriter_anahtari", ...], "placement_hint": '
                '"sayfada nereye"}], "human_tasks": [{"kind": '
                '"image|quote|info", "note": "..."}], "notes": ["..."]}\n'
                "Bölüm sayısı gerektiği kadar (genelde 3-6). Markdown tablo "
                "kullanabilirsin (ölçü/özellik tabloları için tercih et).")
        else:  # title_meta
            task = (
                "GÖREV: Bu sayfa için 3 başlık (title) + meta açıklama "
                "varyantı üret. Başlık ≤60 karakter, meta ≤155 karakter; "
                "sayfanın GERÇEK sorgusuyla uyumlu, tıklama gerekçesi net "
                "(fayda/kanıt), tuzak terimsiz. JSON biçimi:\n"
                '{"title_meta": {"variants": [{"title": "...", '
                '"meta_description": "...", "rationale": "..."}]}, '
                '"human_tasks": [], "notes": ["..."]}')
        return (
            f"Sayfa tipi: {ptype} · kutu: {box} · dil: {language}\n"
            f"Ton: {tone}\nUzunluk kuralı: {length}\n\n"
            "=== MARKA BAĞLAMI (onaylı gerçekler + terimler; bunun dışında "
            "gerçek üretme) ===\n" + self._brand_context(brandpack) + "\n\n"
            + faq_block(brandpack)
            + "=== KUYRUK SATIRI (neden seçildi) ===\n"
            f"Sayfa: {row.get('path')}\nGerekçe: {row.get('reason')}\n"
            f"En ağır eksik kriterler: {missing}\n"
            f"En çok gösterim alan sorgu: {row.get('top_query') or '—'}\n\n"
            "=== CETVEL (taslak bu kriterlerden puan alacak) ===\n"
            + rubric_lines(rubric) + "\n\n"
            "=== MEVCUT SAYFA ===\n"
            f"URL: {page.get('url')}\nBaşlık: {page.get('title')}\n"
            f"Meta: {page.get('meta_description')}\nH2'ler: {head_txt}\n"
            f"Metin (kısaltılmış):\n{(page.get('text') or '')[:9000]}\n\n"
            + task)

    def write_draft(self, row: dict, page: dict, rubric: dict,
                    brandpack: dict, language: str) -> dict:
        """Taslağı üretir; bozuk cevapta BİR kez yeniden dener. Hata → ValueError."""
        # max_tokens: enrich paketi birkaç bölüm + tablo içerir; 4000'de cevap
        # ortadan kesilip JSON bozuluyordu (draft #2 saha bulgusu) — 8192 tavan.
        body = {
            "model": self.model, "max_tokens": 8192, "temperature": 0.4,
            "system": self.system_prompt(language),
            "messages": [{"role": "user", "content": self.user_prompt(
                row, page, rubric, brandpack, language)}],
        }
        last_err = None
        for attempt in (1, 2):
            try:
                self.requests += 1
                data = self._post(body)
                text = "".join(b.get("text", "") for b in data.get("content", [])
                               if b.get("type") == "text").strip()
                text = _FENCE_RE.sub("", text).strip()
                parsed = json.loads(text)
                if isinstance(parsed, dict) and (
                        isinstance(parsed.get("sections"), list)
                        or isinstance(parsed.get("title_meta"), dict)):
                    return parsed
                last_err = ValueError("cevap beklenen JSON yapısında değil")
            except (urllib.error.URLError, urllib.error.HTTPError, OSError,
                    ValueError, KeyError) as e:
                last_err = e
            if attempt == 1:
                self.failures += 1
                time.sleep(self.delay)
        raise ValueError(str(last_err))


# ------------------------------------------------------ taslak → metin/karne

def draft_text(draft: dict) -> str:
    """Deterministik kapıların tarayacağı YAYINLANACAK taslak metni:
    bölümler + başlık/meta varyantları. Yazar notları (notes) ve insan
    görevleri kasıtlı olarak DIŞARIDA — sayfaya girmezler ve modelin
    "şu tuzak terimleri kullanmadım" gibi öz-raporu tuzak taramasında
    yanlış pozitif üretir (draft #3 saha bulgusu)."""
    parts = []
    for s in draft.get("sections") or []:
        parts += [str(s.get("heading", "")), str(s.get("body_markdown", ""))]
    for v in (draft.get("title_meta") or {}).get("variants") or []:
        parts += [str(v.get("title", "")), str(v.get("meta_description", "")),
                  str(v.get("rationale", ""))]
    return "\n".join(p for p in parts if p)


def merged_page(page: dict, draft: dict, box: str) -> dict:
    """Taslak uygulanmış sayfa: enrich → metin+başlıklara bölümler eklenir;
    title_meta → 1. varyantın başlık/metası geçer. Self-check bu sayfayı puanlar
    (dürüst ölçü: 'sayfa taslakla 70'i geçer mi')."""
    m = dict(page)
    m["headings"] = {k: list(v) for k, v in (page.get("headings") or {}).items()}
    if box == "enrich":
        secs = draft.get("sections") or []
        m["text"] = ((page.get("text") or "") + "\n\n" + "\n\n".join(
            f"{s.get('heading', '')}\n{s.get('body_markdown', '')}" for s in secs))[:40000]
        m["headings"].setdefault("h2", [])
        m["headings"]["h2"] = m["headings"]["h2"] + [
            str(s.get("heading", "")) for s in secs if s.get("heading")]
    elif box == "title_meta":
        variants = (draft.get("title_meta") or {}).get("variants") or []
        if variants:
            m["title"] = str(variants[0].get("title", "")) or m.get("title", "")
            m["meta_description"] = (str(variants[0].get("meta_description", ""))
                                     or m.get("meta_description", ""))
    return m


def accuracy_gate(text: str, brandpack: dict) -> dict:
    """Doğruluk kapısı — deterministik, model sonrası. Tuzak terim veya
    MOQ/termin çelişkisi → geçmez. Sayı denetimi MOQ+termin kalıplarıyla
    sınırlıdır (bilinen sınır; kalan sayılar insan onayının konusudur)."""
    pseudo = {"url": "(taslak)", "text": text, "headings": {},
              "title": "", "meta_description": ""}
    traps = find_trap_terms(pseudo, brandpack)
    conflicts = find_fact_conflicts(pseudo, brandpack)
    return {"passed": not traps and not conflicts,
            "trap_terms": traps, "fact_conflicts": conflicts,
            "note": ("sayı denetimi MOQ/termin kalıplarıyla sınırlıdır; "
                     "diğer sayılar onay okumasının konusudur")}


def self_check(page: dict, draft: dict, row: dict, rubric: dict,
               brandpack: dict, judge: Judge | None) -> dict:
    """Taslak uygulanmış sayfayı cetvelden geçirir. Görsel yargı KAPALI
    (taslakta görsel değerlendirilemez); değerlendirilemeyen ağırlık kapı
    paydasına girmez. Kapı puanı = (oto+model kazanılan) / (oto+model
    değerlendirilebilir) × 100."""
    m = merged_page(page, draft, row.get("box", ""))
    scored = score_page(m, rubric, brandpack)
    if judge is not None:
        judge.judge_page(scored, m, brandpack, rubric)
    auto_e = scored.get("auto_earned") or 0.0
    auto_p = scored.get("auto_possible") or 0.0
    jud_e = scored.get("judged_earned") or 0.0
    jud_p = scored.get("judged_possible") or 0.0
    unassessed = scored.get("unassessed_weight") or 0.0
    possible = auto_p + jud_p
    gate_pct = round(100.0 * (auto_e + jud_e) / possible, 1) if possible else None
    threshold = float(rubric.get("threshold_publish") or DEFAULT_THRESHOLD)
    return {
        "gate_pct": gate_pct, "threshold": threshold,
        "passed": gate_pct is not None and gate_pct >= threshold,
        "auto_earned": auto_e, "auto_possible": auto_p,
        "judged_earned": jud_e, "judged_possible": jud_p,
        "unassessed_weight": unassessed,
        "rubric_version": str(rubric.get("version", "")),
        "criteria": scored.get("criteria") or [],
        "findings": scored.get("findings") or [],
        "note": ("kapı puanı yayın eşiği içindir; oto ve model bileşenleri "
                 "ayrıca ayrı durur, sayfa karnesi kuralının yerine geçmez. "
                 "Görsel kriterler taslakta değerlendirilemez (sahte görsel "
                 "üretilmez) — paydaya girmez, insan görevi olarak listelenir"),
    }


def ensure_visual_tasks(draft: dict, rubric: dict, prompts: dict) -> None:
    """Cetvelde görsel kriter varsa insan görevlerinde görsel görevi olduğunu
    garanti eder (model unutsa da deterministik eklenir — skill görsel kuralı)."""
    vision_keys = set((prompts.get("vision_criteria") or {}).keys())
    rubric_keys = {c["key"] for s in rubric.get("sections", [])
                   for c in s.get("criteria", []) or []}
    needed = sorted(vision_keys & rubric_keys)
    if not needed:
        return
    tasks = draft.setdefault("human_tasks", [])
    have_image = any((t or {}).get("kind") == "image" for t in tasks)
    if not have_image:
        tasks.append({"kind": "image",
                      "note": ("cetveldeki görsel kriterler (" + ", ".join(needed)
                               + ") taslakla kapanmaz — gerçek görsel/çizim "
                               "insan işidir; yapay görsel üretilmez")})


def decide_status(accuracy: dict, check: dict, placeholders: list[str]) -> str:
    if not accuracy["passed"]:
        return "accuracy_failed"
    if not check["passed"]:
        return "below_threshold"
    if placeholders:
        return "needs_input"
    return "ready_for_review"


STATUS_TEXT = {
    "ready_for_review": "onaya hazır — doğruluk kapısı + 70 eşiği geçti",
    "needs_input": "eşik geçti ama [BİLGİ GEREKLİ] yer tutucuları var — "
                   "bilgiler tamamlanmadan yayına çıkamaz",
    "below_threshold": "cetvel eşiğinin altında — yayına çıkamaz (docs/method.md)",
    "accuracy_failed": "DOĞRULUK KAPISI RED — tuzak terim/çelişki bulundu; "
                       "yayına çıkamaz",
}


# ---------------------------------------------------------- sonuç + rapor

def build_result(args, row: dict, queue_doc: dict, language: str, draft: dict,
                 accuracy: dict, check: dict, placeholders: list[str],
                 writer: DraftWriter, judge_info: dict) -> dict:
    now = _dt.datetime.now(_dt.timezone.utc).replace(microsecond=0)
    run_id = args.run_id or now.strftime("%Y%m%dT%H%M%SZ")
    status = decide_status(accuracy, check, placeholders)
    words = len(re.findall(r"\S+", draft_text(draft)))
    return {
        "contract": CONTRACT, "contract_version": CONTRACT_VERSION,
        "run": {
            "id": run_id,
            "timestamp_utc": now.isoformat().replace("+00:00", "Z"),
            "site": args.site,
            "engine_rev": args.engine_rev, "brandpack_rev": args.brandpack_rev,
            "workflow_run": args.run_number or None,
            "writer": {"model": writer.model, "requests": writer.requests,
                       "retries": writer.failures},
            "judge": judge_info,
            "inputs": {
                "action_run_id": (queue_doc.get("run") or {}).get("id"),
                "rank": row.get("rank"), "path": row.get("path"),
                "box": row.get("box"), "type": row.get("type"),
                "priority_auto": row.get("priority_auto"),
                "publish_languages": args.publish_languages or None,
            },
        },
        "target": {
            "path": row.get("path"), "url": row.get("url"),
            "type": row.get("type"), "box": row.get("box"),
            "language": language,
            "queue_reason": row.get("reason"),
            "missing_criteria": row.get("missing_criteria") or [],
        },
        "status": status,
        "status_text": STATUS_TEXT[status],
        "accuracy_gate": accuracy,
        "self_check": check,
        "draft": {**draft, "word_count": words, "placeholders": placeholders},
        "notes": [
            "motor yayınlamaz; onay insandadır (teslim: Drive + e-posta)",
            "enrich çıktısı yeni yazı değil, sayfaya eklenecek bölümler paketidir",
            "görsel/alıntı görevleri insan işidir; yapay görsel-alıntı üretilmez",
            "değişikliğin etkisi 6-8 hafta kuralına göre ölçülür (aksiyon kütüğü)",
        ],
    }


def render_draft_md(result: dict) -> str:
    """İnsanın okuyacağı taslak dosyası (Drive'a gidecek biçim)."""
    t, d = result["target"], result["draft"]
    run = result["run"]
    L = [f"# İçerik taslağı — {t['path']}", "",
         f"- Koşu: `{run['id']}` · kutu: **{t['box']}** · tip: {t['type']} · "
         f"dil: **{t['language']}**",
         f"- Durum: **{result['status']}** — {result['status_text']}",
         f"- Kapı puanı: **{result['self_check']['gate_pct']}** "
         f"(eşik {result['self_check']['threshold']}) · "
         f"oto {result['self_check']['auto_earned']}/{result['self_check']['auto_possible']} + "
         f"model {result['self_check']['judged_earned']}/{result['self_check']['judged_possible']} · "
         f"değerlendirilemeyen ağırlık {result['self_check']['unassessed_weight']}",
         f"- Kuyruk gerekçesi: {t['queue_reason']}", ""]
    if d.get("sections"):
        L.append("## Sayfaya eklenecek bölümler")
        L.append("")
        for i, s in enumerate(d["sections"], 1):
            L += [f"### {i}. {s.get('heading', '')}",
                  f"_Yer: {s.get('placement_hint', '—')} · kapattığı kriterler: "
                  f"{', '.join(s.get('addresses') or []) or '—'}_", "",
                  str(s.get("body_markdown", "")), ""]
    if (d.get("title_meta") or {}).get("variants"):
        L += ["## Başlık + meta önerileri", ""]
        for i, v in enumerate(d["title_meta"]["variants"], 1):
            L += [f"**Varyant {i}**",
                  f"- Başlık: {v.get('title', '')}",
                  f"- Meta: {v.get('meta_description', '')}",
                  f"- Gerekçe: {v.get('rationale', '')}", ""]
    if d.get("human_tasks"):
        L += ["## İnsan görevleri (taslakla kapanmayanlar)", ""]
        L += [f"- **{h.get('kind')}**: {h.get('note')}" for h in d["human_tasks"]]
        L.append("")
    if d.get("placeholders"):
        L += ["## Tamamlanacak bilgiler", ""]
        L += [f"- {p}" for p in d["placeholders"]]
        L.append("")
    if not result["accuracy_gate"]["passed"]:
        L += ["## ⛔ Doğruluk kapısı bulguları", ""]
        L += [f"- tuzak terim: `{f.get('trap')}` (doğrusu: {f.get('correct')})"
              for f in result["accuracy_gate"]["trap_terms"]]
        L += [f"- çelişki {f.get('field')}: taslakta {f.get('page_value')} / "
              f"onaylı {f.get('approved_value')}"
              for f in result["accuracy_gate"]["fact_conflicts"]]
        L.append("")
    if d.get("notes"):
        L += ["## Yazar notları", ""] + [f"- {n}" for n in d["notes"]] + [""]
    L += ["---", "_" + " · ".join(result["notes"]) + "_", ""]
    return "\n".join(L)


def render_summary(result: dict) -> str:
    t, c = result["target"], result["self_check"]
    a = result["accuracy_gate"]
    fails = [x for x in c["criteria"]
             if x.get("points") is not None and (x.get("ratio") or 0) < 1.0]
    L = [f"## İçerik taslağı ({result['run']['id']}) — {t['path']}", "",
         f"- Kutu **{t['box']}** · tip {t['type']} · dil **{t['language']}** · "
         f"kuyruk sırası {result['run']['inputs']['rank']} "
         f"(aksiyon koşusu `{result['run']['inputs']['action_run_id']}`)",
         f"- Yazım modeli `{result['run']['writer']['model']}` · self-check "
         f"yargısı: {json.dumps(result['run']['judge'], ensure_ascii=False)}",
         f"- **Durum: {result['status']}** — {result['status_text']}",
         f"- Doğruluk kapısı: {'GEÇTİ' if a['passed'] else 'RED'} "
         f"(tuzak {len(a['trap_terms'])}, çelişki {len(a['fact_conflicts'])})",
         f"- Kapı puanı **{c['gate_pct']}** / eşik {c['threshold']} — "
         f"oto {c['auto_earned']}/{c['auto_possible']} + model "
         f"{c['judged_earned']}/{c['judged_possible']} (değerlendirilemeyen "
         f"{c['unassessed_weight']})",
         f"- Taslak {result['draft']['word_count']} kelime · yer tutucu "
         f"{len(result['draft'].get('placeholders') or [])} · insan görevi "
         f"{len(result['draft'].get('human_tasks') or [])}", ""]
    if fails:
        L += ["Tam puan almayan kriterler:", ""]
        L += [f"- {x['key']} ({x['points']}/{x['weight']}): {x.get('note', '')}"
              for x in fails]
        L.append("")
    return "\n".join(L) + "\n"


def write_outputs(result: dict, md: str, out_dir: str) -> None:
    run_id = result["run"]["id"]
    prev = _read_json(os.path.join(out_dir, "latest.json"))
    if prev and prev.get("contract") == CONTRACT:
        result["changes"] = {"first_run": False,
                             "prev_run_id": (prev.get("run") or {}).get("id"),
                             "prev_path": (prev.get("target") or {}).get("path"),
                             "prev_status": prev.get("status")}
    else:
        result["changes"] = {"first_run": True, "prev_run_id": None}
    _write_json(os.path.join(out_dir, "history", f"{run_id}.json"), result)
    _write_json(os.path.join(out_dir, "latest.json"), result)
    _write_text(os.path.join(out_dir, "history", f"{run_id}.md"), md)
    _write_text(os.path.join(out_dir, "latest.md"), md)
    index_path = os.path.join(out_dir, "index.json")
    index = _read_json(index_path)
    if not (isinstance(index, dict) and isinstance(index.get("runs"), list)):
        index = {"contract": CONTRACT_INDEX,
                 "contract_version": CONTRACT_VERSION, "runs": []}
    entry = {
        "id": run_id, "timestamp_utc": result["run"]["timestamp_utc"],
        "file": f"history/{run_id}.json", "md_file": f"history/{run_id}.md",
        "path": result["target"]["path"], "box": result["target"]["box"],
        "language": result["target"]["language"], "status": result["status"],
        "gate_pct": result["self_check"]["gate_pct"],
        "accuracy_passed": result["accuracy_gate"]["passed"],
        "writer_model": result["run"]["writer"]["model"],
        "action_run_id": result["run"]["inputs"]["action_run_id"],
        "engine_rev": result["run"]["engine_rev"],
        "brandpack_rev": result["run"]["brandpack_rev"],
    }
    index["runs"] = [entry] + [r for r in index["runs"] if r.get("id") != run_id]
    _write_json(index_path, index)


# ---------------------------------------------------------------- ana akış

def fail(msg: str) -> int:
    print(f"HATA: {msg}", file=sys.stderr)
    return 1


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--site", required=True)
    ap.add_argument("--queue-latest", required=True,
                    help="aksiyon kuyruğu (results/actions/latest.json)")
    ap.add_argument("--rank", type=int, default=1,
                    help="kuyruk sırası (varsayılan 1)")
    ap.add_argument("--path", default="",
                    help="sıra yerine sayfa yolu (kuyruk/bekleme listesinden)")
    ap.add_argument("--brandpack-dir", required=True)
    ap.add_argument("--rubrics-dir", required=True)
    ap.add_argument("--brand-rubrics-dir", default="")
    ap.add_argument("--publish-languages", default="",
                    help="markanın yayın dilleri, virgüllü (örn. tr,en); boşsa "
                         "kısıt uygulanmaz. Marka kararıdır, koddan gelmez")
    ap.add_argument("--default-lang", default="tr",
                    help="dil tespit edilemezse site varsayılanı")
    ap.add_argument("--model", default=DEFAULT_WRITER_MODEL,
                    help="yazım modeli")
    ap.add_argument("--judge-model", default=DEFAULT_JUDGE_MODEL,
                    help="self-check yargı modeli")
    ap.add_argument("--judge-prompts", default=DEFAULT_JUDGE_PROMPTS)
    ap.add_argument("--page-json", default="",
                    help="test: canlı çekim yerine hazır sayfa dökümü")
    ap.add_argument("--timeout", type=int, default=20)
    ap.add_argument("--out-dir", default="")
    ap.add_argument("--summary", default="")
    ap.add_argument("--engine-rev", default="?")
    ap.add_argument("--brandpack-rev", default="?")
    ap.add_argument("--run-number", default="")
    ap.add_argument("--run-id", default="")
    args = ap.parse_args(argv)

    queue_doc = _read_json(args.queue_latest)
    if not queue_doc or queue_doc.get("contract") != "action-queue-result":
        return fail(f"aksiyon kuyruğu okunamadı veya sözleşme uymuyor: "
                    f"{args.queue_latest}")
    row, err = pick_row(queue_doc, args.rank, args.path)
    if not row:
        return fail(err)
    if row.get("box") not in ALLOWED_BOXES:
        return fail(f"kutu '{row.get('box')}' için taslak üretilmez — "
                    "merge_or_remove insan kararıdır, new_page Kapı 1 seçimidir")

    brandpack = load_brandpack(args.brandpack_dir)
    rejections = load_rejections(args.brandpack_dir)
    rej = is_rejected(row.get("path", ""), rejections)
    if rej:
        return fail(f"ret hafızası: '{row.get('path')}' daha önce reddedildi "
                    f"({rej.get('reason')}) — taslak üretilmez")
    brand_rubrics_dir = (args.brand_rubrics_dir
                         or os.path.join(args.brandpack_dir, "rubrics"))
    rubrics = load_effective_rubrics(args.rubrics_dir, brand_rubrics_dir)
    rubric = rubrics.get(row.get("type"))
    if not rubric:
        return fail(f"'{row.get('type')}' tipi için cetvel yok — self-check "
                    "yapılamaz, taslak üretilmez")

    # sayfa içeriği
    if args.page_json:
        with open(args.page_json, encoding="utf-8") as f:
            page = json.load(f)
    else:
        url = row.get("url") or (args.site.rstrip("/") + row.get("path", ""))
        page = fetch_page(url, args.timeout)
    if page.get("status") != 200:
        return fail(f"hedef sayfa canlıda okunamadı (HTTP "
                    f"{page.get('status')}, {page.get('error')}) — taslak "
                    "canlı içerik olmadan üretilmez")

    language = page_language(page, row.get("path", ""), args.default_lang)
    allowed = [x.strip().lower() for x in args.publish_languages.split(",")
               if x.strip()]
    if allowed and language not in allowed:
        return fail(f"yayın dili kuralı: sayfa dili '{language}', izinli "
                    f"diller {allowed} — bu sayfaya taslak üretilmez "
                    "(kural değişikliği insan kararıdır)")

    api_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if not api_key:
        return fail("ANTHROPIC_API_KEY tanımlı değil — yazım ve self-check "
                    "modeli olmadan taslak üretilemez")

    writer = DraftWriter(args.model, api_key)
    try:
        draft = writer.write_draft(row, page, rubric, brandpack, language)
    except ValueError as e:
        return fail(f"yazım modeli başarısız: {e}")

    prompts = load_prompts(args.judge_prompts)
    ensure_visual_tasks(draft, rubric, prompts)
    judge = Judge(prompts, model=args.judge_model, api_key=api_key,
                  vision=False)  # görsel yargı taslakta kapalı (tasarım kararı)
    text = draft_text(draft)
    placeholders = PLACEHOLDER_RE.findall(text)
    accuracy = accuracy_gate(text, brandpack)
    check = self_check(page, draft, row, rubric, brandpack, judge)
    judge_info = {"enabled": True, "model": judge.model,
                  "prompt_version": str(prompts["version"]),
                  "requests": judge.requests, "failures": judge.failures,
                  "vision_enabled": False,
                  "vision_note": "taslakta görsel değerlendirilemez — "
                                 "insan görevi listesine düşer"}

    result = build_result(args, row, queue_doc, language, draft, accuracy,
                          check, placeholders, writer, judge_info)
    md = render_draft_md(result)
    if args.out_dir:
        write_outputs(result, md, args.out_dir)
    summary = render_summary(result)
    if args.summary:
        with open(args.summary, "a", encoding="utf-8") as f:
            f.write(summary)
    print(summary)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
