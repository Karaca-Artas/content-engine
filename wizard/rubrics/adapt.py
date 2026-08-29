"""Cetvel uyarlama — sihirbaz, Faz 0 çıktısını cetvele bağlar (Adım 11).

Şablon cetvelleri (engine/scoring/rubrics/) okur ve ONAYLI bilgi paketinden
(brandpack/live: facts.json + terms.json) her kritere markaya özel
``brand_context`` satırı üretir; sonucu bilgi paketine (brandpack/live/rubrics/)
yazar. Motor, paketinde uyarlanmış cetvel bulunan tipleri onunla puanlar
(engine/scoring/quality_scan.py otomatik seçer).

Uyarlama İLKELERİ (docs/method.md ile uyumlu):
- Sihirbaz VERİ UYDURMAZ: kriter listesi, ağırlıklar ve eşik ŞABLONDAKİ GİBİ
  kalır. Uyarlama = markaya özgü bağlamın (onaylı sertifika, MOQ, termin,
  izinli referans listesi, terim sözlüğü, alıcı profili) kriterlere
  enjeksiyonudur. Ağırlık değişikliği ayrı bir insan kararıdır.
- Pakette OLMAYAN veri için bağlam üretilmez (§9 sıfır-başlangıç); alıcı
  profili gibi pakete işlenmemiş onaylar ``--audience`` ile açıkça verilir
  (varsayılmaz, kullanıcı onayı gerekir — §6).
- Sürümleme: şablon 1.1 → uyarlanmış "1.1+b1" (soy görünür); yeniden
  uyarlamada içerik değiştiyse b2, b3… — değişmediyse dosyaya DOKUNULMAZ
  (idempotent). Sürüm değişince compare.py ``method_changed.rubrics`` üretir.
- Varsayılan DRY-RUN: uyarlanmış cetveller yalnız stdout'a (Actions Summary)
  yazılır; ``--apply`` verilmeden pakete dosya yazılmaz (önce anlat, onayla
  uygula).

Kullanım::

    python -m wizard.rubrics.adapt \
        --templates engine/scoring/rubrics \
        --brandpack ../brandpack/live \
        --out ../brandpack/live/rubrics \
        [--audience "satın alma yöneticisi, ..."] [--apply]

Jenerik sihirbaz kodu — marka bilgisi içermez; markaya özel her şey pakette
ve komut girdilerinde yaşar (docs/method.md §9). Bağımlılık: PyYAML.
"""

from __future__ import annotations

import argparse
import copy
import datetime as _dt
import json
import os
import re
import sys

import yaml

_VER_RE = re.compile(r"^(?P<base>.+?)\+b(?P<n>\d+)$")


# ------------------------------------------------------------ paket okuma

def load_brandpack(path: str) -> dict:
    bp = {}
    for name in ("facts", "terms"):
        fp = os.path.join(path, f"{name}.json")
        if os.path.exists(fp):
            with open(fp, encoding="utf-8") as f:
                bp[name] = json.load(f)
    bp["has_customer_questions"] = os.path.exists(
        os.path.join(path, "customer_questions.json"))
    return bp


def _correct_terms(bp: dict) -> list[str]:
    out = []
    for t in (bp.get("terms") or {}).get("terms", []):
        c = (t.get("correct") or "").strip()
        if c:
            out.append(c)
    return out


def _fmt(value) -> str:
    """Onaylı değeri tek satır, insan-okur biçime çevirir."""
    if isinstance(value, dict):
        return "; ".join(f"{k}: {_fmt(v)}" for k, v in value.items())
    if isinstance(value, list):
        return ", ".join(_fmt(v) for v in value)
    return str(value)


# ---------------------------------------------- kriter → bağlam kuralları
# Her kural (facts, terms-listesi, seçenekler) alır; bağlam üretemiyorsa
# (paket verisi yok) None döner ve kriter şablondaki haliyle kalır.

def _ctx_certificates(facts, terms, opt):
    certs = facts.get("certificates")
    if not certs:
        return None
    return (f"Onaylı sertifikalar YALNIZ: {_fmt(certs)}. "
            "Bu liste dışındaki sertifika iddiası puan kazandırmaz; "
            "çelişki olarak gerekçeye yazılır.")


def _ctx_moq(facts, terms, opt):
    moq = facts.get("moq")
    if moq in (None, "", []):
        return None
    return (f"Onaylı MOQ: {_fmt(moq)}. Sayfadaki MOQ ifadesi bu değerle "
            "uyumlu olmalı; farklı değer çelişki bulgusudur (§6).")


def _ctx_lead_time(facts, terms, opt):
    lt = facts.get("lead_times")
    if not lt:
        return None
    return (f"Onaylı termin: {_fmt(lt)}. Sayfadaki termin ifadesi bu "
            "değerlerle uyumlu olmalı.")


def _ctx_named_reference(facts, terms, opt):
    refs = facts.get("named_references")
    if not refs:
        return ("Pakette izinli referans YOK: sayfadaki hiçbir isimli "
                "referans onaylı sayılmaz.")
    return (f"İzinli referans listesi pakette ({len(refs)} isim). Yalnız bu "
            "listedeki isimler tam puan sayılır; liste dışı isim kullanımı "
            "izin sorunudur ve gerekçeye yazılır.")


def _ctx_terms(facts, terms, opt):
    if not terms:
        return None
    return (f"Onaylı ticari terimler: {', '.join(terms)}. Tuzak terimler "
            "paketin terim sözlüğünde; tuzak kullanımı puanı düşürür.")


def _ctx_audience(facts, terms, opt):
    aud = opt.get("audience") or facts.get("audience")
    if not aud:
        return None
    return (f"Onaylı hedef alıcı profili: {_fmt(aud)}. Dil ve derinlik bu "
            "profillere göre değerlendirilir (B2B; son tüketici dili uyumsuzdur).")


def _ctx_claims(facts, terms, opt):
    keys = [k for k in ("moq", "lead_times", "certificates", "not_offered")
            if facts.get(k)]
    if not keys:
        return None
    return ("Sayısal/ticari iddialar paketin onaylı gerçekleriyle "
            f"({', '.join(keys)}) uyumlu olmalı; paket dışı kesin iddia "
            "kaynak ister.")


def _ctx_products(facts, terms, opt):
    prods = facts.get("products")
    if not prods:
        return None
    names = _fmt([p.get("name", "") for p in prods if isinstance(p, dict)])
    return (f"Onaylı ürün ailesi: {names}. Yönlendirme ve içerik bu ürünlere "
            "hizmet etmeli.")


def _ctx_sectors(facts, terms, opt):
    secs = facts.get("sectors")
    if not secs:
        return None
    names = _fmt([s.get("name", s) if isinstance(s, dict) else s for s in secs])
    return f"Onaylı sektörler: {names}. Kanıt ve örnekler bu sektörlere özgü olmalı."


def _ctx_faq(facts, terms, opt):
    if opt.get("has_customer_questions"):
        return ("Müşteri sık-soru dosyası pakette (customer_questions.json); "
                "kapsama bu sorulara göre ölçülür.")
    return ("Pakette müşteri sık-soru verisi (customer_questions.json) YOK — "
            "bu kriter değerlendirilemez ve ağırlığı 'değerlendirilmedi' "
            "olarak açık kalır. Veri eklenince cetvel yeniden uyarlanır.")


CONTEXT_RULES = {
    "certificates": _ctx_certificates,
    "moq": _ctx_moq,
    "lead_time": _ctx_lead_time,
    "named_reference": _ctx_named_reference,
    "term_accuracy": _ctx_terms,
    "alt_text": _ctx_terms,
    "product_links": _ctx_products,
    "audience_fit": _ctx_audience,
    "claims_sourced": _ctx_claims,
    "sector_evidence": _ctx_sectors,
    "faq_coverage": _ctx_faq,
}


# --------------------------------------------------------------- uyarlama

def adapt_rubric(template: dict, bp: dict, audience: str = "") -> dict:
    """Tek şablonu uyarlar; sürüm/tarih alanları adapt_all'da damgalanır."""
    r = copy.deepcopy(template)
    facts = bp.get("facts") or {}
    terms = _correct_terms(bp)
    opt = {"audience": audience.strip(),
           "has_customer_questions": bp.get("has_customer_questions", False)}
    n_ctx = 0
    for section in r.get("sections", []):
        for crit in section.get("criteria", []) or []:
            rule = CONTEXT_RULES.get(crit.get("key"))
            ctx = rule(facts, terms, opt) if rule else None
            if ctx:
                crit["brand_context"] = ctx
                n_ctx += 1
    r["adapted"] = True
    r["adapted_from_template"] = str(template.get("version", ""))
    r["brand_name"] = facts.get("brand_name", "")
    r["adapted_inputs"] = {
        "facts_approved_at": facts.get("approved_at", ""),
        "audience": opt["audience"] or facts.get("audience", "") or None,
        "criteria_with_context": n_ctx,
    }
    return r


def _strip_volatile(r: dict) -> dict:
    """Sürüm/tarih dışındaki içerik — idempotenlik kıyası için."""
    c = copy.deepcopy(r)
    for k in ("version", "adapted_at"):
        c.pop(k, None)
    return c


def _next_version(template_ver: str, existing: dict | None, new_core: dict):
    """(sürüm, değişti-mi). Mevcut uyarlanmış dosyayla içerik aynıysa mevcut
    sürüm korunur; değiştiyse b sayacı artar; dosya yoksa +b1."""
    if existing:
        if _strip_volatile(existing) == new_core:
            return str(existing.get("version", "")), False
        m = _VER_RE.match(str(existing.get("version", "")))
        if m:
            return f"{template_ver}+b{int(m.group('n')) + 1}", True
    return f"{template_ver}+b1", True


def _load_yaml(path: str) -> dict | None:
    try:
        with open(path, encoding="utf-8") as f:
            r = yaml.safe_load(f)
        return r if isinstance(r, dict) else None
    except OSError:
        return None


def adapt_all(templates_dir: str, brandpack_dir: str, out_dir: str,
              audience: str = "", apply: bool = False,
              today: str | None = None) -> list[dict]:
    """Tüm şablonları uyarlar. Dönen liste: her cetvel için özet satırı.
    apply=False → dosya yazılmaz (dry-run)."""
    bp = load_brandpack(brandpack_dir)
    if not bp.get("facts") or not bp.get("terms"):
        raise SystemExit(f"onaylı paket bulunamadı: {brandpack_dir} "
                         "(facts.json + terms.json gerekli — önce Faz 0)")
    today = today or _dt.date.today().isoformat()
    rows = []
    for fn in sorted(os.listdir(templates_dir)):
        if not fn.endswith((".yml", ".yaml")):
            continue
        template = _load_yaml(os.path.join(templates_dir, fn))
        if not (template and template.get("type")):
            continue
        adapted = adapt_rubric(template, bp, audience=audience)
        core = _strip_volatile(adapted)
        out_path = os.path.join(out_dir, fn)
        existing = _load_yaml(out_path)
        version, changed = _next_version(str(template.get("version", "")),
                                         existing, core)
        adapted["version"] = version
        adapted["adapted_at"] = (today if changed
                                 else (existing or {}).get("adapted_at", today))
        if apply and changed:
            os.makedirs(out_dir, exist_ok=True)
            with open(out_path, "w", encoding="utf-8") as f:
                yaml.safe_dump(adapted, f, allow_unicode=True, sort_keys=False,
                               width=100)
        rows.append({"file": fn, "type": adapted["type"], "version": version,
                     "changed": changed, "rubric": adapted})
    return rows


# -------------------------------------------------------------------- CLI

def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--templates", required=True, help="şablon cetvel dizini")
    ap.add_argument("--brandpack", required=True, help="onaylı paket (brandpack/live)")
    ap.add_argument("--out", required=True, help="uyarlanmış cetvel dizini (paket içinde)")
    ap.add_argument("--audience", default="",
                    help="onaylı hedef alıcı profili (kullanıcı onayıyla; varsayılmaz)")
    ap.add_argument("--apply", action="store_true",
                    help="dosyaları pakete YAZ (verilmezse dry-run: yalnız çıktı)")
    args = ap.parse_args(argv)

    rows = adapt_all(args.templates, args.brandpack, args.out,
                     audience=args.audience, apply=args.apply)
    mode = "APPLY — pakete yazıldı" if args.apply else "DRY-RUN — dosya yazılmadı"
    print(f"## Cetvel uyarlama ({mode})\n")
    for r in rows:
        state = "güncellendi" if r["changed"] else "değişiklik yok (dokunulmadı)"
        print(f"### {r['type']} → sürüm `{r['version']}` — {state}\n")
        print("```yaml")
        print(yaml.safe_dump(r["rubric"], allow_unicode=True, sort_keys=False,
                             width=100).rstrip())
        print("```\n")
    n = sum(1 for r in rows if r["changed"])
    print(f"Toplam {len(rows)} cetvel; {n} tanesi "
          + ("yazıldı." if args.apply else "yazılacak (apply ile)."), file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
