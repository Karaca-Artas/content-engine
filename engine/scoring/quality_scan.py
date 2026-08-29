"""Kalite taraması koşucusu — Faz 1 ilk gerçek deneme (yalnız Summary çıktısı).

Siteyi nazik tarayıcıyla gezer, sayfaları tipine göre sınıflandırır, canlı
brandpack ile cetvel puanı üretir ve markdown rapor yazar. Sonuçlar bu sürümde
depoya YAZILMAZ; yalnız rapor (Actions Summary) üretilir.

Sınıflandırma (jenerik; marka bilgisi yalnız brandpack'ten gelir):
1. URL deseni: ürün/sektör/blog kalıpları
2. Yapısal makale sinyali: og:type=article veya article:published_time → blog_post
   (WordPress'te yazılar kök dizinde yaşayabilir; URL kalıbı tek başına yetmez)
3. Kalanlarda: başlık/h1 içinde brandpack doğru terimi geçen sayfa ürün sayılır
4. Kalanlar "other": cetvel puanı üretilmez, yalnız tuzak terim + çelişki taraması

Kullanım::

    python -m engine.scoring.quality_scan --site https://www.example.com \
        --brandpack-dir ../brandpack-repo/brandpack/live \
        --rubrics-dir engine/scoring/rubrics \
        --max-pages 30 --delay 3 --summary rapor.md

Bağımlılık: PyYAML (cetvel şablonları için); kalanı stdlib.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys

import yaml

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
from engine.sources.crawler import crawl  # noqa: E402
from engine.scoring.scorer import (  # noqa: E402
    BLOG_PATH, PRODUCT_PATH, SECTOR_PATH,
    correct_terms, find_fact_conflicts, find_trap_terms, score_page,
)


def load_brandpack(path: str) -> dict:
    bp = {}
    for name in ("facts", "terms"):
        fp = os.path.join(path, f"{name}.json")
        if os.path.exists(fp):
            with open(fp, encoding="utf-8") as f:
                bp[name] = json.load(f)
    return bp


def load_rubrics(path: str) -> dict:
    rubrics = {}
    for fn in os.listdir(path):
        if fn.endswith((".yml", ".yaml")):
            with open(os.path.join(path, fn), encoding="utf-8") as f:
                r = yaml.safe_load(f)
            if isinstance(r, dict) and r.get("type"):
                rubrics[r["type"]] = r
    return rubrics


def _is_article(page: dict) -> bool:
    """Yapısal makale sinyali (jenerik): og:type=article veya yayın tarihi meta'sı."""
    return (page.get("og_type") or "").strip().lower() == "article" or \
        bool((page.get("published_time") or "").strip())


def classify(page: dict, brandpack: dict) -> str:
    url = page.get("url", "")
    if PRODUCT_PATH.search(url):
        return "product_page"
    if SECTOR_PATH.search(url):
        return "sector_page"
    if BLOG_PATH.search(url) or _is_article(page):
        return "blog_post"
    head = " ".join([page.get("title", "")] +
                    (page.get("headings") or {}).get("h1", [])).lower()
    if any(t in head for t in correct_terms(brandpack)):
        return "product_page"
    return "other"


def pct(row: dict) -> float:
    return 100.0 * row["auto_earned"] / row["auto_possible"] if row["auto_possible"] else 0.0


def render_markdown(site: str, results: list[dict], other_findings: list[dict],
                    engine_rev: str, brandpack_rev: str) -> str:
    scored = [r for r in results if r["has_criteria"]]
    scored.sort(key=pct)
    lines = [
        "## Kalite taraması — ilk gerçek deneme (Faz 1 · v1)",
        "",
        f"- Site: {site}",
        f"- Motor sürümü: `{engine_rev}` · Brandpack sürümü: `{brandpack_rev}`",
        "- Cetvel: **şablon v1.0, uyarlanmamış** · yalnız otomatik kriterler puanlandı;",
        "  model yargılı kriterler \"değerlendirilmedi\" (ağırlıkları ayrı sütunda).",
        "- Sonuçlar bu turda depoya yazılmadı (yalnız bu rapor).",
        "",
        f"### Cetvelle puanlanan sayfalar ({len(scored)})",
        "",
        "| Sayfa | Tip | Oto. puan | Oto. tavan | % | Değerlendirilmeyen ağırlık |",
        "|---|---|---|---|---|---|",
    ]
    for r in scored:
        lines.append(
            f"| {r['url']} | {r['rubric_type']} | {r['auto_earned']} | "
            f"{r['auto_possible']} | {pct(r):.0f}% | {r['unassessed_weight']} |")
    lines += ["", "### En zayıf 5 sayfa (otomatik kriter yüzdesine göre)", ""]
    for r in scored[:5]:
        lines.append(f"**{r['url']}** — %{pct(r):.0f}")
        for c in r["criteria"]:
            if c["auto"] and (c["ratio"] or 0) < 1.0:
                lines.append(f"- {c['key']} ({c['points']}/{c['weight']}): {c['note']}")
        lines.append("")
    findings = [f for r in results for f in r["findings"]] + other_findings
    traps = [f for f in findings if f["kind"] == "trap_term"]
    conflicts = [f for f in findings if f["kind"] == "fact_conflict"]
    lines += [f"### Tuzak terim bulguları ({len(traps)})", ""]
    if traps:
        lines += ["| Sayfa | Tuzak | Doğrusu | Adet |", "|---|---|---|---|"]
        lines += [f"| {f['url']} | {f['trap']} | {f['correct']} | {f['count']} |" for f in traps]
    else:
        lines.append("Tuzak terim bulunamadı.")
    lines += ["", f"### Onaylı paketle çelişkiler ({len(conflicts)}) — motor seçmez, insan kararı (§6)", ""]
    if conflicts:
        lines += ["| Sayfa | Alan | Sayfadaki | Onaylı |", "|---|---|---|---|"]
        lines += [f"| {f['url']} | {f['field']} | {f['page_value']} | {f['approved_value']} |"
                  for f in conflicts]
    else:
        lines.append("Çelişki bulunamadı.")
    others = [r for r in results if not r["has_criteria"]]
    lines += ["", f"### Cetvel dışı sayfalar ({len(others)}) — yalnız tuzak/çelişki tarandı", ""]
    lines += [f"- {r['url']} ({r['rubric_type'] or 'other'})" for r in others]
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--site", required=True)
    ap.add_argument("--brandpack-dir", required=True)
    ap.add_argument("--rubrics-dir", required=True)
    ap.add_argument("--max-pages", type=int, default=30)
    ap.add_argument("--delay", type=float, default=3.0)
    ap.add_argument("--summary", default="")
    ap.add_argument("--engine-rev", default="?")
    ap.add_argument("--brandpack-rev", default="?")
    ap.add_argument("--pages-json", default="", help="test/tekrar için hazır tarama dökümü")
    args = ap.parse_args(argv)

    brandpack = load_brandpack(args.brandpack_dir)
    rubrics = load_rubrics(args.rubrics_dir)
    if args.pages_json:
        with open(args.pages_json, encoding="utf-8") as f:
            pages = json.load(f)
    else:
        pages = crawl({"site": {"url": args.site},
                       "crawler": {"delay_seconds": args.delay,
                                   "max_pages": args.max_pages}})

    results, other_findings = [], []
    for page in pages:
        if page.get("status") != 200:
            continue
        ptype = classify(page, brandpack)
        rubric = rubrics.get(ptype)
        if rubric:
            results.append(score_page(page, rubric, brandpack))
            results[-1]["rubric_type"] = ptype
        else:
            other_findings += find_trap_terms(page, brandpack)
            other_findings += find_fact_conflicts(page, brandpack)
            results.append({"url": page.get("url", ""), "rubric_type": ptype,
                            "has_criteria": False, "auto_earned": 0, "auto_possible": 0,
                            "unassessed_weight": 0, "criteria": [], "findings": []})

    md = render_markdown(args.site, results, other_findings,
                         args.engine_rev, args.brandpack_rev)
    if args.summary:
        with open(args.summary, "a", encoding="utf-8") as f:
            f.write(md)
    print(md)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
