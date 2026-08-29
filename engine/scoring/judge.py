"""Model yargısı — sabit rubrikle kriter puanlama (Adım 10).

Oto kontrollerin ölçemediği kriterler (auto: false) sayfa kanıtı + marka
bağlamıyla birlikte SABİT rubrikle (engine/scoring/judge_prompts.yml) modele
gönderilir; model her kriter için 0 / 0.5 / 1 puanı ve kısa kanıt gerekçesi
döndürür. Modele sadece rakam gönderilmez: sayfanın metni, başlıkları ve
görsel alt metinleri de gider (yoksa model rakamları başka kelimelerle tekrar
eder; değer kesişimdedir).

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

_FENCE_RE = re.compile(r"^```[a-zA-Z]*\s*|\s*```$")


def load_prompts(path: str) -> dict:
    """judge_prompts.yml'i okur ve asgari doğrular."""
    with open(path, encoding="utf-8") as f:
        p = yaml.safe_load(f)
    if not (isinstance(p, dict) and p.get("version") and p.get("system")
            and isinstance(p.get("criteria"), dict)):
        raise ValueError(f"geçersiz rubrik dosyası: {path}")
    p.setdefault("skip", {})
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
                 api_key: str = "", delay: float = 1.0, timeout: float = 120.0):
        self.prompts = prompts
        self.model = model
        self.api_key = api_key
        self.delay = delay
        self.timeout = timeout
        self.requests = 0
        self.failures = 0

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

    def _call(self, user_prompt: str) -> dict:
        """Bir sayfalık istek; bozuk cevapta/ağ hatasında BİR kez yeniden dener.
        Dönen değer: {"criteria": {...}} sözlüğü. Hata → ValueError."""
        body = {
            "model": self.model,
            "max_tokens": 1500,
            "temperature": 0,
            "system": self.prompts["system"],
            "messages": [{"role": "user", "content": user_prompt}],
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

    def _judgeable(self, rubric: dict) -> tuple[list[dict], dict]:
        """(modele gidecek kriterler, atlanacaklar {key: neden})."""
        send, skipped = [], {}
        skip = self.prompts.get("skip") or {}
        known = self.prompts.get("criteria") or {}
        for section in rubric.get("sections", []):
            for crit in section.get("criteria", []) or []:
                if crit.get("auto"):
                    continue
                key = crit["key"]
                if key in skip:
                    skipped[key] = str(skip[key])
                elif key in known:
                    send.append(crit)
                else:
                    skipped[key] = "sabit rubrikte bu kriterin çıpası yok"
        return send, skipped

    def _user_prompt(self, page: dict, rubric: dict,
                     send: list[dict], brandpack: dict) -> str:
        crit_lines = []
        for crit in send:
            anchors = (self.prompts["criteria"].get(crit["key"]) or {}).get("anchors") or []
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
        return (
            f"Sayfa tipi: {rubric.get('type', '')}\n\n"
            "=== MARKA BAĞLAMI (onaylı gerçekler + terimler; bunun dışında gerçek üretme) ===\n"
            + self._brand_context(brandpack) + "\n\n"
            "=== SAYFA KANITI ===\n" + self._page_evidence(page) + "\n\n"
            "=== PUANLANACAK KRİTERLER ===\n" + "\n".join(crit_lines) + "\n\n"
            "Her kriteri çıpalara göre puanla. Yanıt SADECE JSON."
        )

    # -------------------------------------------------------------- uygulama

    def judge_page(self, row: dict, page: dict, brandpack: dict, rubric: dict) -> None:
        """score_page çıktısını (row) yerinde günceller.

        Başarıda: yargılanan kriterlere ratio/points/note (+judged_by) yazılır,
        row'a judged_earned/judged_possible eklenir, unassessed_weight yalnız
        gerçekten yargılanamayan ağırlığı gösterir. Hatada: kriterler
        "değerlendirilmedi" kalır, neden notlara yazılır, koşu düşmez.
        """
        send, skipped = self._judgeable(rubric)
        rows = {c["key"]: c for c in row.get("criteria", []) if not c.get("auto")}

        for key, reason in skipped.items():
            if key in rows:
                rows[key]["note"] = f"değerlendirilmedi ({reason})"

        if not send:
            row["judged_earned"], row["judged_possible"] = 0.0, 0.0
            row["unassessed_weight"] = round(sum(c["weight"] for c in rows.values()), 1)
            return

        try:
            answer = self._call(self._user_prompt(page, rubric, send, brandpack))
        except ValueError as e:
            self.failures += 1
            for crit in send:
                if crit["key"] in rows:
                    rows[crit["key"]]["note"] = f"değerlendirilmedi (model hatası: {e})"
            row["judged_earned"], row["judged_possible"] = 0.0, 0.0
            row["unassessed_weight"] = round(sum(c["weight"] for c in rows.values()), 1)
            return

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
            target.update({"ratio": ratio, "points": pts, "judged_by": "model",
                           "note": f"model: {evidence}" if evidence else "model yargısı"})
            earned += pts
            possible += weight
        unassessed += sum(float(c["weight"]) for k, c in rows.items() if k in skipped)
        row["judged_earned"] = round(earned, 1)
        row["judged_possible"] = round(possible, 1)
        row["unassessed_weight"] = round(unassessed, 1)
        time.sleep(self.delay)
