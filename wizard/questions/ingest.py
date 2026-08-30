"""Müşteri sık-soru dosyası alımı — sihirbaz (Adım 13).

Müşteri yazışmalarından OTURUM İÇİNDE çıkarılan taslak sık-soru dosyasını
(customer_questions taslağı) doğrular ve onayla canlı pakete yazar.

İlkeler (docs/method.md + brandpack/SCHEMA.md):
- Sihirbaz VERİ UYDURMAZ ve posta kutusuna ERİŞMEZ: taslağı oturumda insan
  gözetiminde Claude çıkarır; bu modül yalnız doğrular ve yazar.
- ANONİMLİK ZORUNLU: dosyada ad, firma, fiyat, e-posta, telefon olamaz.
  Mekanik denetim (e-posta/telefon/para kalıpları) burada RED üretir;
  isim/firma denetimi listeyi onaylayan insandadır — ikisi birlikte gerekir.
- Tarih etiketi: her kayıt ay hassasiyetinde first_seen/last_seen taşır
  (YYYY-MM); motor yeni kayıtlara daha çok ağırlık verir.
- Varsayılan DRY-RUN: özet stdout'a (Actions Summary) yazılır; ``--apply``
  verilmeden pakete dosya yazılmaz (önce anlat, onayla uygula).

Kullanım::

    python -m wizard.questions.ingest \
        --draft draft_customer_questions.json \
        --brandpack ../brandpack/live [--apply]

Jenerik sihirbaz kodu — marka bilgisi içermez (docs/method.md §9). Stdlib.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys

MONTH_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

# --- Anonimlik kalıpları (mekanik katman; insan onayı ayrıca zorunlu) ------
EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
# Telefon: uluslararası önek VEYA aralıklı/bitişik en az 10 hane.
PHONE_RE = re.compile(r"(?:\+|00)\d[\d\s().-]{8,}\d|\b\d{10,}\b")
# Para: sembol/kod + sayı bitişikliği (fiyat dosyaya giremez).
MONEY_RE = re.compile(
    r"[€$£₺]\s?\d|\d[\d.,]*\s?(?:EUR|USD|GBP|TRY|TL|eur|usd|gbp)\b")

ANON_PATTERNS = (("e-posta adresi", EMAIL_RE),
                 ("telefon numarası", PHONE_RE),
                 ("fiyat/para tutarı", MONEY_RE))


class IngestError(Exception):
    """Doğrulama hatası — pakete yazım reddedilir."""


def _load_json(path: str):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _strings_of(obj):
    """Nesnedeki tüm dizgileri (yol, değer) olarak gezer."""
    if isinstance(obj, str):
        yield ("", obj)
    elif isinstance(obj, dict):
        for k, v in obj.items():
            for p, s in _strings_of(v):
                yield (f"{k}.{p}".rstrip("."), s)
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            for p, s in _strings_of(v):
                yield (f"[{i}].{p}".rstrip("."), s)


# ------------------------------------------------------------- doğrulama

def validate_structure(doc: dict) -> None:
    """Şemanın zorunlu koşulları, stdlib ile (jsonschema yok)."""
    if not isinstance(doc, dict):
        raise IngestError("taslak bir JSON nesnesi olmalı")
    gen = doc.get("generated_at", "")
    if not (isinstance(gen, str) and DATE_RE.match(gen)):
        raise IngestError("generated_at zorunlu, biçim YYYY-MM-DD")
    cov = doc.get("coverage")
    if not (isinstance(cov, dict) and MONTH_RE.match(str(cov.get("from", "")))
            and MONTH_RE.match(str(cov.get("to", "")))):
        raise IngestError("coverage.from/to zorunlu, biçim YYYY-MM")
    if str(cov["from"]) > str(cov["to"]):
        raise IngestError("coverage.from, coverage.to'dan sonra olamaz")
    qs = doc.get("questions")
    if not (isinstance(qs, list) and qs):
        raise IngestError("questions boş olmayan bir liste olmalı")
    seen = set()
    for i, q in enumerate(qs):
        where = f"questions[{i}]"
        if not isinstance(q, dict):
            raise IngestError(f"{where} bir nesne olmalı")
        text = str(q.get("question", "")).strip()
        if not text:
            raise IngestError(f"{where}.question zorunlu")
        if text.lower() in seen:
            raise IngestError(f"{where}: yinelenen soru: {text!r}")
        seen.add(text.lower())
        freq = q.get("frequency")
        if not (isinstance(freq, int) and freq >= 1):
            raise IngestError(f"{where}.frequency ≥1 tamsayı olmalı")
        for fld in ("first_seen", "last_seen"):
            if not MONTH_RE.match(str(q.get(fld, ""))):
                raise IngestError(f"{where}.{fld} zorunlu, biçim YYYY-MM")
        if str(q["first_seen"]) > str(q["last_seen"]):
            raise IngestError(f"{where}: first_seen > last_seen olamaz")
        if not (str(cov["from"]) <= str(q["first_seen"])
                and str(q["last_seen"]) <= str(cov["to"])):
            raise IngestError(f"{where}: kayıt tarihleri coverage dışına taşıyor")
        for fld in ("languages", "products", "customer_terms"):
            if fld in q and not isinstance(q[fld], list):
                raise IngestError(f"{where}.{fld} liste olmalı")


def lint_anonymity(doc: dict) -> list[str]:
    """Anonimlik ihlali adayları: (yol, kalıp adı) listesi. Boş = temiz."""
    hits = []
    for path, s in _strings_of(doc):
        for label, rx in ANON_PATTERNS:
            if rx.search(s):
                hits.append(f"{path or '(kök)'}: {label} kalıbı: {s[:60]!r}")
    return hits


# ---------------------------------------------------------------- özet

def summarize(doc: dict, top: int = 10) -> str:
    qs = doc["questions"]
    langs = sorted({l for q in qs for l in (q.get("languages") or [])})
    rows = sorted(qs, key=lambda q: (-q["frequency"], q["question"]))[:top]
    lines = [
        f"Kayıt: {len(qs)} soru · Dönem: {doc['coverage']['from']} – "
        f"{doc['coverage']['to']} · Diller: {', '.join(langs) or '(etiketsiz)'}",
        f"En sık {len(rows)} soru:",
    ]
    for q in rows:
        lines.append(f"  - {q['question']} (sıklık {q['frequency']}, "
                     f"{q['first_seen']}–{q['last_seen']})")
    return "\n".join(lines)


# ---------------------------------------------------------------- komut

def run(draft_path: str, brandpack_dir: str, apply: bool) -> int:
    doc = _load_json(draft_path)
    validate_structure(doc)
    hits = lint_anonymity(doc)
    if hits:
        print("RED — anonimlik denetimi ihlal adayları buldu; pakete yazılamaz:")
        for h in hits:
            print(f"  ! {h}")
        return 2
    print(summarize(doc))
    out = os.path.join(brandpack_dir, "customer_questions.json")
    if not apply:
        print(f"\nDRY-RUN: pakete yazılmadı ({out}). Onaydan sonra --apply ile yazılır.")
        return 0
    os.makedirs(brandpack_dir, exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, indent=2)
        f.write("\n")
    print(f"\nYAZILDI: {out}")
    print("Not: cetvellerin yeniden uyarlanması gerekir (wizard/rubrics/adapt.py — b sayacı artar).")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--draft", required=True, help="taslak customer_questions JSON yolu")
    ap.add_argument("--brandpack", required=True, help="canlı paket dizini (brandpack/live)")
    ap.add_argument("--apply", action="store_true",
                    help="onaydan sonra pakete yaz (varsayılan dry-run)")
    args = ap.parse_args(argv)
    try:
        return run(args.draft, args.brandpack, args.apply)
    except (IngestError, json.JSONDecodeError, OSError) as err:
        print(f"RED — {err}")
        return 2


if __name__ == "__main__":
    sys.exit(main())
