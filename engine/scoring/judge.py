"""Model yargısı — sabit rubrikle kriter puanlama (Adım 10 metin + Adım 12 görsel).

Oto kontrollerin ölçemediği kriterler (auto: false) sayfa kanıtı + marka
bağlamıyla birlikte SABİT rubrikle (engine/scoring/judge_prompts.yml) modele
gönderilir; model her kriter için 0 / 0.5 / 1 puanı ve kısa kanıt gerekçesi
döndürür. Modele sadece rakam gönderilmez: sayfanın metni, başlıkları ve
görsel alt metinleri de gider (yoksa model rakamları başka kelimelerle tekrar
eder; değer kesişimdedir).

Görsel kriterler (rubrikteki `vision_criteria`: real_photos, tech_drawing)
sayfa başına AYRI bir görüş isteğiyle puanlanır: tarayıcının topladığı içerik
görselleri (page["images"]) API'ye URL kaynağı olarak gönderilir (en çok
MAX_VISION_IMAGES; görselleri Anthropic çeker, workflow indirmez). Tarayıcı
sayfada hiç içerik görseli bulamadıysa model çağrılmaz ve kriter 0 alır —
"kanıt yoksa 0" kuralı (bilinen sınır: CSS arkaplan görselleri toplanamaz;
not satırında açıkça yazılır).

Dürüstlük kuralları (docs/method.md ile uyumlu):
- Model puanı oto puanla ASLA tek puanda birleştirilmez; ayrı alanlarda yaşar
  (judged_earned/judged_possible), pano ayrı gösterir.
- Model kimliği + rubrik sürümü koşuya damgalanır; biri değişirse compare.py
  `method_changed.judge` üretir — koşular arası puan farkı yöntemden gelebilir.
- Model erişilemezse veya cevap bozuksa koşu DÜŞMEZ: kriter "değerlendirilmedi"
  kalır ve nedeni notuna yazılır.
- Rubrikte `skip` listesindeki kriterler (görsel yargısı, eksik veri) modele
  hiç gönderilmez; nedenleri kriter notuna yazılır.

API: Anthropic Messages API (api.anthropic.com), anahtar ANTHROPIC_API_KEY
ortam değişkeninden okunur (Actions'ta repo secret'ı — bu projenin sıfır-secret
deseninin bilinçli tek istisnası, Adım 10 kararı). temperature=0.

Jenerik motor kodu — marka bilgisi içermez (docs/method.md §9).
Bağımlılık: PyYAML (rubrik dosyası); kalanı stdlib.
"""

from __future__ import annotations

import json
import re
import time
import urllib.error
import urllib.request

import yaml

API_URL = "https://api.anthropic.com/v1/messages"
API_VERSION = "2023-06-01"
DEFAULT_MODEL = "claude-haiku-4-5"
VALID_RATIOS = (0.0, 0.5, 1.0)
TEXT_CHAR_LIMIT = 12000
MAX_ALT_TEXTS = 30
EVIDENCE_CHAR_LIMIT = 240
MAX_VISION_IMAGES = 8

_FENCE_RE = re.compile(r"^```[a-zA-Z]*\s*|\s*```$")


def load_prompts(path: str) -> dict:
    """judge_prompts.yml'i okur ve asgari doğrular."""
    with open(path, encoding="utf-8") as f:
        p = yaml.safe_load(f)
    if not (isinstance(p, dict) and p.get("version") and p.get("system")
            and isinstance(p.get("criteria"), dict)):
        raise ValueError(f"geçersiz rubrik dosyası: {path}")
    p.setdefault("skip", {})
    p.setdefault("vision_criteria", {})
    return p


def _clamp_ratio(value) -> float | None:
    """Model puanını geçerli çıpaya oturtur; sayı değilse None."""
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    return min(VALID_RATIOS, key=lambda r: abs(r - v))


class Judge:
    """Sayfa başına tek istekle auto:false kriterleri puanlar."""

    def __init__(self, prompts: dict, model: str = DEFAULT_MODEL,
                 api_key: str = "", delay: float = 1.0, timeout: float = 120.0,
                 vision: bool = True):
        self.prompts = prompts
        self.model = model
        self.api_key = api_key
        self.delay = delay
        self.timeout = timeout
        self.vision = vision  # görsel kriter yargısı (Adım 12); --no-vision kapatır
        self.requests = 0
        self.failures = 0
        self.vision_requests = 0
        self.vision_failures = 0

    # ------------------------------------------------------------ istek katmanı

    def _post(self, body: dict) -> dict:
        """API çağrısı — testlerde taklit edilir (monkeypatch)."""
        req = urllib.request.Request(
            API_URL,
            data=json.dumps(body).encode("utf-8"),
            headers={
                "content-type": "application/json",
                "x-api-key": self.api_key,
                "anthropic-version": API_VERSION,
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:
            return json.load(resp)

    def _call(self, user_content, system: str = "", vision: bool = False) -> dict:
        """Bir sayfalık istek; bozuk cevapta/ağ hatasında BİR kez yeniden dener.
        ``user_content``: düz metin (metin yargısı) veya içerik bloğu listesi
        (görüş yargısı — metin + image blokları). Dönen değer: {"criteria": ...}
        sözlüğü. Hata → ValueError."""
        body = {
            "model": self.model,
            "max_tokens": 1500,
            "temperature": 0,
            "system": system or self.prompts["system"],
            "messages": [{"role": "user", "content": user_content}],
        }
        last_err = None
        for attempt in (1, 2):
            try:
                if vision:
                    self.vision_requests += 1
                else:
                    self.requests += 1
                data = self._post(body)
                text = "".join(b.get("text", "") for b in data.get("content", [])
                               if b.get("type") == "text").strip()
                text = _FENCE_RE.sub("", text).strip()
                parsed = json.loads(text)
                if isinstance(parsed, dict) and isinstance(parsed.get("criteria"), dict):
                    return parsed
                last_err = ValueError("cevap beklenen JSON yapısında değil")
            except (urllib.error.URLError, urllib.error.HTTPError, OSError,
                    ValueError, KeyError) as e:
                last_err = e
            if attempt == 1:
                time.sleep(self.delay)
        raise ValueError(str(last_err))

    # ---------------------------------------------------------- girdi hazırlama

    @staticmethod
    def _brand_context(brandpack: dict) -> str:
        """Marka bağlamı: onaylı gerçekler + terim sözlüğü (kompakt JSON).
        Model bu bağlamın DIŞINDA gerçek üretemez (docs/method.md §5)."""
        ctx = {}
        if brandpack.get("facts"):
            ctx["onayli_gercekler"] = brandpack["facts"]
        if brandpack.get("terms"):
            ctx["terim_sozlugu"] = brandpack["terms"]
        return json.dumps(ctx, ensure_ascii=False, separators=(",", ":"))

    @staticmethod
    def _page_evidence(page: dict) -> str:
        heads = page.get("headings") or {}
        parts = [
            f"URL: {page.get('url', '')}",
            f"Başlık (title): {page.get('title', '')}",
            f"Meta açıklama: {page.get('meta_description', '')}",
        ]
        for lvl in ("h1", "h2", "h3"):
            if heads.get(lvl):
                parts.append(f"{lvl.upper()}: " + " | ".join(heads[lvl]))
        alts = (page.get("images_alt") or [])[:MAX_ALT_TEXTS]
        parts.append("Görsel alt metinleri: " + (" | ".join(alts) if alts else "(yok)"))
        text = (page.get("text") or "")[:TEXT_CHAR_LIMIT]
        parts.append("Sayfa metni:\n" + text)
        return "\n".join(parts)

    def _judgeable(self, rubric: dict) -> tuple[list[dict], list[dict], dict]:
        """(metin isteğine gidecekler, görüş isteğine gidecekler,
        atlanacaklar {key: neden})."""
        send, vision_send, skipped = [], [], {}
        skip = self.prompts.get("skip") or {}
        known = self.prompts.get("criteria") or {}
        vision_known = self.prompts.get("vision_criteria") or {}
        for section in rubric.get("sections", []):
            for crit in section.get("criteria", []) or []:
                if crit.get("auto"):
                    continue
                key = crit["key"]
                if key in skip:
                    skipped[key] = str(skip[key])
                elif key in known:
                    send.append(crit)
                elif key in vision_known:
                    if self.vision:
                        vision_send.append(crit)
                    else:
                        skipped[key] = "görsel yargısı kapalı (--no-vision)"
                else:
                    skipped[key] = "sabit rubrikte bu kriterin çıpası yok"
        return send, vision_send, skipped

    @staticmethod
    def _crit_lines(send: list[dict], anchors_map: dict) -> list[str]:
        crit_lines = []
        for crit in send:
            anchors = (anchors_map.get(crit["key"]) or {}).get("anchors") or []
            a_txt = " · ".join(f"{a['ratio']}: {a['desc']}" for a in anchors)
            line = (f"- {crit['key']} (ağırlık {crit['weight']}): "
                    f"{crit.get('desc', '')}\n  Çıpalar: {a_txt}")
            # Uyarlanmış cetvelden gelen markaya özel bağlam (Adım 11):
            # çıpalar SABİT kalır, bağlam kriterin değerlendirme çerçevesini
            # markaya bağlar. Cetvel sürümü değiştiği için bu ekleme
            # method_changed.rubrics kapsamında raporlanır.
            if crit.get("brand_context"):
                line += f"\n  Marka bağlamı: {crit['brand_context']}"
            crit_lines.append(line)
        return crit_lines

    def _user_prompt(self, page: dict, rubric: dict,
                     send: list[dict], brandpack: dict) -> str:
        crit_lines = self._crit_lines(send, self.prompts["criteria"])
        return (
            f"Sayfa tipi: {rubric.get('type', '')}\n\n"
            "=== MARKA BAĞLAMI (onaylı gerçekler + terimler; bunun dışında gerçek üretme) ===\n"
            + self._brand_context(brandpack) + "\n\n"
            "=== SAYFA KANITI ===\n" + self._page_evidence(page) + "\n\n"
            "=== PUANLANACAK KRİTERLER ===\n" + "\n".join(crit_lines) + "\n\n"
            "Her kriteri çıpalara göre puanla. Yanıt SADECE JSON."
        )

    def _vision_content(self, page: dict, rubric: dict, vision_send: list[dict],
                        brandpack: dict, images: list[dict]) -> list[dict]:
        """Görüş isteğinin içerik blokları: bağlam metni + görsel blokları.
        Görseller URL kaynağı olarak gider; Anthropic kendisi çeker."""
        crit_lines = self._crit_lines(vision_send, self.prompts["vision_criteria"])
        shown = images[:MAX_VISION_IMAGES]
        header = (
            f"Sayfa tipi: {rubric.get('type', '')}\n"
            f"URL: {page.get('url', '')}\n"
            f"Başlık: {page.get('title', '')}\n\n"
            "=== MARKA BAĞLAMI (onaylı gerçekler + terimler; bunun dışında gerçek üretme) ===\n"
            + self._brand_context(brandpack) + "\n\n"
            f"Sayfada {len(images)} içerik görseli bulundu; ilk {len(shown)} tanesi "
            "aşağıda numaralı olarak gösteriliyor.\n\n"
            "=== PUANLANACAK GÖRSEL KRİTERLER ===\n" + "\n".join(crit_lines)
        )
        blocks: list[dict] = [{"type": "text", "text": header}]
        for i, im in enumerate(shown, 1):
            label = f"Görsel {i}: {im.get('src', '')}"
            if im.get("alt"):
                label += f" (alt: {im['alt']})"
            blocks.append({"type": "text", "text": label})
            blocks.append({"type": "image",
                           "source": {"type": "url", "url": im.get("src", "")}})
        blocks.append({"type": "text",
                       "text": "Her kriteri çıpalara göre puanla. Yanıt SADECE JSON."})
        return blocks

    # -------------------------------------------------------------- uygulama

    def _apply_answer(self, answer: dict, send: list[dict], rows: dict,
                      judged_by: str, note_prefix: str) -> tuple[float, float, float]:
        """Model cevabındaki puanları kriter satırlarına yazar;
        (earned, possible, unassessed) döndürür."""
        earned = possible = unassessed = 0.0
        got = answer["criteria"]
        for crit in send:
            key, weight, target = crit["key"], float(crit["weight"]), rows.get(crit["key"])
            if target is None:
                continue
            ratio = _clamp_ratio((got.get(key) or {}).get("ratio"))
            if ratio is None:
                unassessed += weight
                target["note"] = "değerlendirilmedi (model bu kriter için puan döndürmedi)"
                continue
            evidence = str((got.get(key) or {}).get("evidence", ""))[:EVIDENCE_CHAR_LIMIT]
            pts = round(weight * ratio, 1)
            target.update({"ratio": ratio, "points": pts, "judged_by": judged_by,
                           "note": f"{note_prefix}: {evidence}" if evidence else note_prefix})
            earned += pts
            possible += weight
        return earned, possible, unassessed

    def judge_page(self, row: dict, page: dict, brandpack: dict, rubric: dict) -> None:
        """score_page çıktısını (row) yerinde günceller.

        Metin kriterleri tek istekte, görsel kriterler (varsa) ayrı bir görüş
        isteğinde puanlanır (Adım 12). Başarıda: yargılanan kriterlere
        ratio/points/note (+judged_by: "model" | "vision") yazılır, row'a
        judged_earned/judged_possible eklenir, unassessed_weight yalnız
        gerçekten yargılanamayan ağırlığı gösterir. Hatada: kriterler
        "değerlendirilmedi" kalır, neden notlara yazılır, koşu düşmez.
        """
        send, vision_send, skipped = self._judgeable(rubric)
        rows = {c["key"]: c for c in row.get("criteria", []) if not c.get("auto")}
        earned = possible = unassessed = 0.0

        for key, reason in skipped.items():
            if key in rows:
                rows[key]["note"] = f"değerlendirilmedi ({reason})"
                unassessed += float(rows[key]["weight"])

        # ---- metin yargısı (Adım 10)
        if send:
            try:
                answer = self._call(self._user_prompt(page, rubric, send, brandpack))
                e, p, u = self._apply_answer(answer, send, rows, "model", "model")
                earned, possible, unassessed = earned + e, possible + p, unassessed + u
            except ValueError as err:
                self.failures += 1
                for crit in send:
                    if crit["key"] in rows:
                        rows[crit["key"]]["note"] = f"değerlendirilmedi (model hatası: {err})"
                        unassessed += float(crit["weight"])
            time.sleep(self.delay)

        # ---- görüş yargısı (Adım 12)
        if vision_send:
            images = page.get("images") or []
            if not images:
                # "Kanıt yoksa 0" kuralı: tarayıcı sayfada içerik görseli
                # bulamadı → model çağrılmaz, kriter 0 alır. Bilinen sınır:
                # CSS arkaplan görselleri toplanamaz; not satırında açık.
                for crit in vision_send:
                    target = rows.get(crit["key"])
                    if target is None:
                        continue
                    target.update({
                        "ratio": 0.0, "points": 0.0, "judged_by": "vision",
                        "note": ("içerik görseli bulunamadı — kanıt yokluğu 0 "
                                 "(görsel modele gönderilmedi; CSS arkaplan "
                                 "görselleri tarayıcıca toplanamaz)")})
                    possible += float(crit["weight"])
            else:
                try:
                    answer = self._call(
                        self._vision_content(page, rubric, vision_send, brandpack, images),
                        system=self.prompts.get("system_vision") or "",
                        vision=True)
                    e, p, u = self._apply_answer(answer, vision_send, rows,
                                                 "vision", "model(görsel)")
                    earned, possible, unassessed = earned + e, possible + p, unassessed + u
                except ValueError as err:
                    self.vision_failures += 1
                    for crit in vision_send:
                        if crit["key"] in rows:
                            rows[crit["key"]]["note"] = (
                                f"değerlendirilmedi (görüş modeli hatası: {err})")
                            unassessed += float(crit["weight"])
                time.sleep(self.delay)

        row["judged_earned"] = round(earned, 1)
        row["judged_possible"] = round(possible, 1)
        row["unassessed_weight"] = round(unassessed, 1)
