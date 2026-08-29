"""Kalite taraması koşucusu — Faz 1 (Adım 8: sonuçlar depoya yazılır).

Siteyi nazik tarayıcıyla gezer, sayfaları tipine göre sınıflandırır, canlı
brandpack ile cetvel puanı üretir, markdown rapor (Actions Summary) yazar ve
--out-dir verilirse sonuçları veri sözleşmesine (docs/results-contract.md v1.0)
uygun JSON olarak marka deposuna yazar: latest.json + history/<id>.json +
index.json. Önceki latest.json bulunursa koşular arası fark (`changes` bloğu)
engine.scoring.compare ile üretilir.

Sınıflandırma (jenerik; marka bilgisi yalnız brandpack'ten gelir):
1. Arşiv/liste kalıbı (kategori, yazar, sayfalama, blog dizini) → "archive": liste
   sayfası içerik cetveliyle puanlanmaz, yalnız tuzak terim + çelişki taranır
2. URL deseni: ürün/sektör/blog kalıpları
3. Yapısal makale sinyali → blog_post: og:type=article, article:published_time
   veya JSON-LD @type Article/BlogPosting/NewsArticle (og:type'ı yanlış
   yapılandırılmış sitelerde sinyal JSON-LD'den gelir; yazılar kök dizinde
   yaşayabilir, URL kalıbı tek başına yetmez)
4. Kalanlarda: başlık/h1 içinde brandpack doğru terimi geçen sayfa ürün sayılır
5. Kalanlar "other": cetvel puanı üretilmez, yalnız tuzak terim + çelişki taraması

Kullanım::

    python -m engine.scoring.quality_scan --site https://www.example.com \
        --brandpack-dir ../brandpack-repo/brandpack/live \
        --rubrics-dir engine/scoring/rubrics \
        --max-pages 30 --delay 3 --summary rapor.md \
        --out-dir ../brandpack-repo/results/quality

Bağımlılık: PyYAML (cetvel şablonları için); kalanı stdlib.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import re
import sys

import yaml

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
from engine.sources.crawler import crawl  # noqa: E402
from engine.scoring.compare import diff  # noqa: E402
from engine.scoring.scorer import (  # noqa: E402
    ARCHIVE_PATH, BLOG_PATH, PRODUCT_PATH, SECTOR_PATH,
    correct_terms, find_fact_conflicts, find_trap_terms, score_page,
)

ARTICLE_LD_TYPES = {"article", "blogposting", "newsarticle", "techarticle"}
CONTRACT_VERSION = "1.0"


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
    """Yapısal makale sinyali (jenerik): og:type=article, yayın tarihi meta'sı
    veya JSON-LD @type Article/BlogPosting/NewsArticle."""
    if (page.get("og_type") or "").strip().lower() == "article":
        return True
    if (page.get("published_time") or "").strip():
        return True
    lds = {str(t).strip().lower() for t in (page.get("ld_types") or [])}
    return bool(lds & ARTICLE_LD_TYPES)


def classify(page: dict, brandpack: dict) -> str:
    url = page.get("url", "")
    if ARCHIVE_PATH.search(url):
        return "archive"
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


# ------------------------------------------------- sözleşme (JSON) üretimi

def build_scan(site: str, results: list[dict], other_findings: list[dict],
               rubrics: dict, args) -> dict:
    """Sonuç listesini veri sözleşmesi v1.0 yapısına çevirir (changes hariç)."""
    now = _dt.datetime.now(_dt.timezone.utc).replace(microsecond=0)
    run_id = args.run_id or now.strftime("%Y%m%dT%H%M%SZ")
    pages, findings = [], list(other_findings)
    for r in results:
        scored = bool(r.get("has_criteria"))
        row = {
            "url": r["url"],
            "type": r.get("rubric_type") or "other",
            "scored": scored,
            "rubric_version": r.get("rubric_version", "") if scored else None,
            "auto_earned": r["auto_earned"] if scored else None,
            "auto_possible": r["auto_possible"] if scored else None,
            "auto_pct": round(pct(r), 1) if scored and r["auto_possible"] else None,
            "unassessed_weight": r["unassessed_weight"] if scored else None,
            "criteria": r.get("criteria") or [],
        }
        pages.append(row)
        findings.extend(r.get("findings") or [])
    scored_rows = [p for p in pages if p["scored"]]
    by_type: dict = {}
    for p in scored_rows:
        b = by_type.setdefault(p["type"], {"pages": 0, "sum_pct": 0.0})
        b["pages"] += 1
        b["sum_pct"] += p["auto_pct"] or 0.0
    for t, b in by_type.items():
        b["avg_auto_pct"] = round(b.pop("sum_pct") / b["pages"], 1)
    return {
        "contract": "quality-scan-result",
        "contract_version": CONTRACT_VERSION,
        "run": {
            "id": run_id,
            "timestamp_utc": now.isoformat().replace("+00:00", "Z"),
            "site": site,
            "engine_rev": args.engine_rev,
            "brandpack_rev": args.brandpack_rev,
            "workflow_run": args.run_number or None,
            "rubric_versions": {t: str(r.get("version", "")) for t, r in rubrics.items()},
            "rubric_note": "şablon cetvel, uyarlanmamış (v1)",
            "max_pages": args.max_pages,
            "pages_ok": len(results),
        },
        "totals": {
            "scored_pages": len(scored_rows),
            "unscored_pages": len(pages) - len(scored_rows),
            "avg_auto_pct": (round(sum(p["auto_pct"] or 0 for p in scored_rows)
                                   / len(scored_rows), 1) if scored_rows else None),
            "by_type": by_type,
            "trap_terms": sum(1 for f in findings if f.get("kind") == "trap_term"),
            "fact_conflicts": sum(1 for f in findings if f.get("kind") == "fact_conflict"),
        },
        "pages": pages,
        "findings": findings,
    }


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


def write_outputs(scan: dict, out_dir: str) -> dict:
    """latest.json'ı okur → fark üretir → history/<id>.json + latest.json +
    index.json yazar. Dönen değer: üretilen `changes` bloğu."""
    latest_path = os.path.join(out_dir, "latest.json")
    prev = _read_json(latest_path)
    if prev and prev.get("contract") != "quality-scan-result":
        prev = None
    scan["changes"] = diff(prev, scan)

    run = scan["run"]
    _write_json(os.path.join(out_dir, "history", f"{run['id']}.json"), scan)
    _write_json(latest_path, scan)

    index_path = os.path.join(out_dir, "index.json")
    index = _read_json(index_path)
    if not (isinstance(index, dict) and isinstance(index.get("runs"), list)):
        index = {"contract": "quality-scan-index",
                 "contract_version": CONTRACT_VERSION, "runs": []}
    entry = {
        "id": run["id"],
        "timestamp_utc": run["timestamp_utc"],
        "file": f"history/{run['id']}.json",
        "engine_rev": run["engine_rev"],
        "brandpack_rev": run["brandpack_rev"],
        "scored_pages": scan["totals"]["scored_pages"],
        "avg_auto_pct": scan["totals"]["avg_auto_pct"],
        "trap_terms": scan["totals"]["trap_terms"],
        "fact_conflicts": scan["totals"]["fact_conflicts"],
        "changed_pages": (None if scan["changes"].get("first_run")
                          else scan["changes"]["summary"]["pages_changed"]),
    }
    index["runs"] = [entry] + [r for r in index["runs"] if r.get("id") != run["id"]]
    _write_json(index_path, index)
    return scan["changes"]


# ---------------------------------------------------------- markdown rapor

def _fmt_finding(f: dict) -> str:
    if f.get("kind") == "trap_term":
        return f"tuzak terim `{f.get('trap')}` ({f.get('url')})"
    if f.get("kind") == "fact_conflict":
        return (f"çelişki {f.get('field')}: sayfada {f.get('page_value')} / "
                f"onaylı {f.get('approved_value')} ({f.get('url')})")
    return str(f)


def render_changes(changes: dict | None) -> list[str]:
    lines = ["### Önceki koşuya göre değişim", ""]
    if not changes:
        return lines + ["Sonuç depoya yazılmadı (--out-dir verilmedi); fark üretilmedi.", ""]
    if changes.get("first_run"):
        return lines + ["İlk kalıcı koşu — kıyaslanacak önceki kayıt yok.", ""]
    mc = changes.get("method_changed") or {}
    if any(mc.values()):
        parts = [k for k, v in mc.items() if v]
        lines.append(f"⚠️ Yöntem değişti ({', '.join(parts)}) — puan farkları siteden değil "
                     "yöntem değişikliğinden gelebilir; yorum insan kararıdır.")
        lines.append("")
    s = changes["summary"]
    lines.append(f"Önceki koşu: `{changes.get('prev_run_id')}` · puanı değişen sayfa: "
                 f"{s['pages_changed']} · yeni sayfa: {s['new_pages']} · kaybolan: "
                 f"{s['removed_pages']} · yeni bulgu: {s['new_findings']} · kapanan bulgu: "
                 f"{s['resolved_findings']}")
    lines.append("")
    if changes["score_changes"]:
        lines += ["| Sayfa | Önceki % | Yeni % | Δ |", "|---|---|---|---|"]
        lines += [f"| {c['url']} | {c['prev_pct']} | {c['new_pct']} | "
                  f"{c['delta_pct']:+.1f} |" for c in changes["score_changes"]]
        lines.append("")
    for c in changes["type_changes"]:
        lines.append(f"- tip değişti: {c['url']} — {c['prev']} → {c['new']}")
    lines += [f"- YENİ bulgu: {_fmt_finding(f)}" for f in changes["new_findings"]]
    lines += [f"- KAPANDI: {_fmt_finding(f)}" for f in changes["resolved_findings"]]
    if not (changes["score_changes"] or changes["type_changes"] or
            changes["new_findings"] or changes["resolved_findings"] or
            changes["new_pages"] or changes["removed_pages"]):
        lines.append("Değişiklik yok — iki koşu aynı sonucu verdi.")
    lines.append("")
    return lines


def render_markdown(site: str, results: list[dict], other_findings: list[dict],
                    engine_rev: str, brandpack_rev: str,
                    changes: dict | None = None, persisted: bool = False) -> str:
    scored = [r for r in results if r["has_criteria"]]
    scored.sort(key=pct)
    lines = [
        "## Kalite taraması (Faz 1)",
        "",
        f"- Site: {site}",
        f"- Motor sürümü: `{engine_rev}` · Brandpack sürümü: `{brandpack_rev}`",
        "- Cetvel: **şablon v1.x, uyarlanmamış** · yalnız otomatik kriterler puanlandı;",
        "  model yargılı kriterler \"değerlendirilmedi\" (ağırlıkları ayrı sütunda).",
        ("- Sonuçlar depoya yazıldı: `results/quality/` (sözleşme v" + CONTRACT_VERSION + ")."
         if persisted else "- Sonuçlar depoya YAZILMADI (yalnız bu rapor)."),
        "",
    ]
    lines += render_changes(changes)
    lines += [
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
    ap.add_argument("--run-number", default="", help="Actions koşu numarası (bilgi amaçlı)")
    ap.add_argument("--run-id", default="", help="koşu kimliği (boşsa UTC zaman damgası)")
    ap.add_argument("--out-dir", default="",
                    help="sonuç JSON'larının yazılacağı dizin (örn. results/quality); "
                         "boşsa depoya yazılmaz, yalnız rapor üretilir")
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

    changes = None
    if args.out_dir:
        scan = build_scan(args.site, results, other_findings, rubrics, args)
        changes = write_outputs(scan, args.out_dir)

    md = render_markdown(args.site, results, other_findings,
                         args.engine_rev, args.brandpack_rev,
                         changes=changes, persisted=bool(args.out_dir))
    if args.summary:
        with open(args.summary, "a", encoding="utf-8") as f:
            f.write(md)
    print(md)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
