"""Performans taraması koşucusu — Faz 2, Kanal B'nin veri tarafı (Adım 14).

Search Console (sayfa + sayfa×sorgu) ve GA4 (sayfa yolu) verisini çeker, URL
yolu üzerinden birleştirir, varsa son kalite koşusunun (results/quality/latest.json)
puanlarını iliştirir ve öncelik ÖNİZLEMESİNİ üretir:

    priority_auto = (100 − auto_pct) × gösterim      (yöntem: docs/method.md)

Dürüstlük kuralları:
- Oto puan ile model puanı asla birleştirilmez; öncelik önizlemesi yalnız
  OTO yüzdesiyle hesaplanır ve alan adında bu açıkça yazılıdır (priority_auto).
  Tam Kanal C sentezi (aksiyon kuyruğu, dört kutu) ayrı adımın işidir.
- Kaynaklardan biri erişilemezse koşu düşmez: sources bloğunda ok=false +
  hata özeti; ikisi de düşerse koşu başarısız sayılır (veri yok).
- GSC verisi 2-3 gün gecikmelidir: pencere sonu varsayılan olarak bugünden
  --end-lag-days (3) gün geridedir; yorumlar 6-8 hafta kuralına tabidir.

Kanibalizm ön-tespiti: aynı sorguda birden çok sayfanın anlamlı gösterim
alması (sayfa başına ≥ MIN_IMP gösterim VE sorgu toplamının ≥ %15'i) bulgu
olarak işaretlenir; nihai yorum insana/sonraki adıma aittir.

Çıktı: docs/results-contract.md "performance-scan-result" v1.0 —
results/performance/{latest.json, index.json, history/<id>.json}

Kullanım (Actions'ta; jeton anahtarsız WIF adımından gelir)::

    python -m engine.performance.perf_scan \
        --site https://www.artaspack.com \
        --gsc-property sc-domain:artaspack.com --ga4-property 336534572 \
        --quality-latest ../brand/results/quality/latest.json \
        --out-dir ../brand/results/performance --summary rapor.md

Bağımlılık: saf stdlib. Test için --gsc-pages-json/--gsc-queries-json/--ga4-json
ile hazır API dökümleri verilebilir (ağ çağrısı yapılmaz).
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import sys
import urllib.parse

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
from engine.sources import ga4, gsc  # noqa: E402
from engine.sources.gsc import SourceError  # noqa: E402

CONTRACT = "performance-scan-result"
CONTRACT_INDEX = "performance-scan-index"
CONTRACT_VERSION = "1.0"
MIN_IMP = 10          # kanibalizm: sayfa başına en az gösterim
MIN_SHARE = 0.15      # kanibalizm: sorgu toplamındaki en az pay
TOP_QUERIES = 5       # sayfa başına saklanan en iyi sorgu sayısı
MAX_CANNIBAL = 20     # bulgu listesi tavanı


# ---------------------------------------------------------------- yardımcılar

def norm_path(url_or_path: str) -> str:
    """URL veya yol → kıyaslanabilir yol: sorgu/çapa atılır, kök dışında
    sondaki / kaldırılır."""
    s = url_or_path or ""
    if "://" in s:
        s = urllib.parse.urlsplit(s).path or "/"
    s = s.split("?", 1)[0].split("#", 1)[0]
    if not s.startswith("/"):
        s = "/" + s
    if len(s) > 1 and s.endswith("/"):
        s = s.rstrip("/") or "/"
    return s


def date_window(window_days: int, end_lag_days: int,
                today: _dt.date | None = None) -> tuple[str, str]:
    today = today or _dt.date.today()
    end = today - _dt.timedelta(days=end_lag_days)
    start = end - _dt.timedelta(days=window_days - 1)
    return start.isoformat(), end.isoformat()


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


# ---------------------------------------------------------------- birleştirme

def merge_pages(gsc_pages: list[dict], gsc_queries: list[dict],
                ga4_pages: list[dict], quality: dict | None) -> list[dict]:
    """Üç kaynağı yol üzerinden birleştirir; kalite puanını iliştirir."""
    pages: dict[str, dict] = {}

    def entry(path: str) -> dict:
        return pages.setdefault(path, {
            "path": path, "url": None,
            "clicks": 0, "impressions": 0, "ctr": None, "position": None,
            "sessions": 0, "engaged_sessions": 0, "users": 0,
            "engagement_rate": None, "in_gsc": False, "in_ga4": False,
            "top_queries": [], "quality": None, "priority_auto": None,
        })

    for r in gsc_pages:
        p = entry(norm_path(r["page"]))
        p["url"] = r["page"]
        p["clicks"] += r["clicks"]
        p["impressions"] += r["impressions"]
        p["position"] = r["position"] if p["position"] is None else min(
            p["position"], r["position"])
        p["in_gsc"] = True

    by_page_queries: dict[str, list[dict]] = {}
    for r in gsc_queries:
        by_page_queries.setdefault(norm_path(r["page"]), []).append(r)
    for path, rows in by_page_queries.items():
        rows.sort(key=lambda r: (-r["clicks"], -r["impressions"]))
        entry(path)["top_queries"] = [
            {"query": r["query"], "clicks": r["clicks"],
             "impressions": r["impressions"],
             "position": round(r["position"], 1)}
            for r in rows[:TOP_QUERIES]]

    for r in ga4_pages:
        p = entry(norm_path(r["path"]))
        p["sessions"] += r["sessions"]
        p["engaged_sessions"] += r["engaged_sessions"]
        p["users"] += r["users"]
        p["in_ga4"] = True

    qmap = {}
    if quality and isinstance(quality.get("pages"), list):
        for qp in quality["pages"]:
            qmap[norm_path(qp.get("url", ""))] = qp
    for p in pages.values():
        if p["impressions"]:
            p["ctr"] = round(p["clicks"] / p["impressions"], 4)
        if p["sessions"]:
            p["engagement_rate"] = round(
                p["engaged_sessions"] / p["sessions"], 3)
        if p["position"] is not None:
            p["position"] = round(p["position"], 1)
        qp = qmap.get(p["path"])
        if qp:
            p["quality"] = {
                "type": qp.get("type"), "scored": qp.get("scored"),
                "auto_pct": qp.get("auto_pct"),
                "judged_pct": qp.get("judged_pct"),
                "run_id": (quality.get("run") or {}).get("id"),
            }
            if qp.get("scored") and qp.get("auto_pct") is not None:
                p["priority_auto"] = round(
                    (100.0 - qp["auto_pct"]) * p["impressions"], 1)
    return sorted(pages.values(), key=lambda p: -p["impressions"])


def find_cannibal_queries(gsc_queries: list[dict]) -> list[dict]:
    """Aynı sorguda anlamlı gösterim alan birden çok sayfa → bulgu."""
    by_query: dict[str, list[dict]] = {}
    for r in gsc_queries:
        by_query.setdefault(r["query"], []).append(r)
    findings = []
    for q, rows in by_query.items():
        total = sum(r["impressions"] for r in rows)
        strong = [r for r in rows
                  if r["impressions"] >= MIN_IMP
                  and total and r["impressions"] / total >= MIN_SHARE]
        if len(strong) >= 2:
            strong.sort(key=lambda r: -r["impressions"])
            findings.append({
                "kind": "cannibal_query", "query": q,
                "total_impressions": total,
                "pages": [{"path": norm_path(r["page"]),
                           "clicks": r["clicks"],
                           "impressions": r["impressions"],
                           "position": round(r["position"], 1)}
                          for r in strong],
                "note": ("aynı sorguda birden çok sayfa yarışıyor olabilir — "
                         "vekil tespit, nihai yorum insana aittir"),
            })
    findings.sort(key=lambda f: -f["total_impressions"])
    return findings[:MAX_CANNIBAL]


# ---------------------------------------------------------------- çıktı

def build_changes(prev: dict | None, scan: dict) -> dict:
    if not prev or prev.get("contract") != CONTRACT:
        return {"first_run": True, "prev_run_id": None,
                "note": "önceki kayıtlı koşu yok — fark üretilmedi"}
    pt, nt = prev.get("totals", {}), scan["totals"]
    return {
        "first_run": False,
        "prev_run_id": (prev.get("run") or {}).get("id"),
        "prev_timestamp_utc": (prev.get("run") or {}).get("timestamp_utc"),
        "clicks_delta": nt["clicks"] - pt.get("clicks", 0),
        "impressions_delta": nt["impressions"] - pt.get("impressions", 0),
        "sessions_delta": nt["sessions"] - pt.get("sessions", 0),
        "note": ("pencereler örtüşebilir — dönemsel yorum 6-8 hafta kuralına "
                 "tabidir; sayfa bazlı fark görünümü sonraki adımın işidir"),
    }


def write_outputs(scan: dict, out_dir: str) -> dict:
    latest_path = os.path.join(out_dir, "latest.json")
    prev = _read_json(latest_path)
    scan["changes"] = build_changes(prev, scan)
    run = scan["run"]
    _write_json(os.path.join(out_dir, "history", f"{run['id']}.json"), scan)
    _write_json(latest_path, scan)

    index_path = os.path.join(out_dir, "index.json")
    index = _read_json(index_path)
    if not (isinstance(index, dict) and isinstance(index.get("runs"), list)):
        index = {"contract": CONTRACT_INDEX,
                 "contract_version": CONTRACT_VERSION, "runs": []}
    t = scan["totals"]
    entry = {
        "id": run["id"], "timestamp_utc": run["timestamp_utc"],
        "file": f"history/{run['id']}.json",
        "engine_rev": run["engine_rev"], "brandpack_rev": run["brandpack_rev"],
        "window_start": run["window"]["start_date"],
        "window_end": run["window"]["end_date"],
        "pages": t["pages"], "clicks": t["clicks"],
        "impressions": t["impressions"], "sessions": t["sessions"],
        "matched_quality_pages": t["matched_quality_pages"],
        "cannibal_queries": t["cannibal_queries"],
    }
    index["runs"] = [entry] + [r for r in index["runs"] if r.get("id") != run["id"]]
    _write_json(index_path, index)
    return scan["changes"]


def render_summary(scan: dict) -> str:
    run, t = scan["run"], scan["totals"]
    L = [f"## Performans taraması — {run['id']}", "",
         f"Pencere: {run['window']['start_date']} → {run['window']['end_date']} "
         f"({run['window']['days']} gün, GSC gecikmesi {run['window']['end_lag_days']} gün)", ""]
    for name in ("gsc", "ga4"):
        s = run["sources"][name]
        L.append(f"- **{name.upper()}** ({s['property']}): "
                 + (f"{s['rows']} satır" if s["ok"] else f"HATA — {s['error']}"))
    L += ["",
          f"Toplam: {t['pages']} sayfa · {t['clicks']} tıklama · "
          f"{t['impressions']} gösterim · {t['sessions']} oturum · "
          f"kalite eşleşen {t['matched_quality_pages']} sayfa", "",
          "### En çok gösterim alan sayfalar", "",
          "| Sayfa | Tık | Göst. | Ort. sıra | Oturum | Oto-% | Öncelik (önizleme) |",
          "|---|---|---|---|---|---|---|"]
    for p in scan["pages"][:10]:
        q = p["quality"] or {}
        L.append("| {} | {} | {} | {} | {} | {} | {} |".format(
            p["path"], p["clicks"], p["impressions"],
            p["position"] if p["position"] is not None else "—",
            p["sessions"],
            q.get("auto_pct") if q.get("auto_pct") is not None else "—",
            p["priority_auto"] if p["priority_auto"] is not None else "—"))
    pri = [p for p in scan["pages"] if p["priority_auto"] is not None]
    pri.sort(key=lambda p: -p["priority_auto"])
    if pri:
        L += ["", "### Öncelik önizlemesi — (100 − oto puan) × gösterim", "",
              "Yalnız OTO yüzdesiyle; model puanı ayrı tutulur. "
              "Tam Kanal C sentezi sonraki adımın işidir.", ""]
        for p in pri[:5]:
            L.append(f"- `{p['path']}` → **{p['priority_auto']}** "
                     f"(oto %{p['quality']['auto_pct']}, {p['impressions']} gösterim)")
    cann = [f for f in scan["findings"] if f["kind"] == "cannibal_query"]
    if cann:
        L += ["", f"### Kanibalizm ön-tespiti ({len(cann)} sorgu)", ""]
        for f in cann[:5]:
            ps = " · ".join(f"{x['path']} ({x['impressions']}g, sıra {x['position']})"
                            for x in f["pages"])
            L.append(f"- \"{f['query']}\" ({f['total_impressions']}g): {ps}")
    ch = scan.get("changes") or {}
    L += ["", "### Önceki koşuya göre değişim", ""]
    if ch.get("first_run"):
        L.append("İlk kalıcı koşu — kıyaslanacak önceki kayıt yok.")
    elif ch:
        L.append(f"Önceki koşu {ch['prev_run_id']} · tıklama {ch['clicks_delta']:+d} · "
                 f"gösterim {ch['impressions_delta']:+d} · oturum {ch['sessions_delta']:+d} "
                 f"(pencere örtüşmesine dikkat; 6-8 hafta kuralı)")
    return "\n".join(L) + "\n"


# ---------------------------------------------------------------- ana akış

def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--site", required=True)
    ap.add_argument("--gsc-property", required=True,
                    help="örn. sc-domain:example.com veya https://www.example.com/")
    ap.add_argument("--ga4-property", required=True,
                    help="sayısal GA4 mülk numarası")
    ap.add_argument("--window-days", type=int, default=28)
    ap.add_argument("--end-lag-days", type=int, default=3)
    ap.add_argument("--start-date", default="", help="pencere başlangıcını sabitle (test)")
    ap.add_argument("--end-date", default="")
    ap.add_argument("--token-env", default="GOOGLE_OAUTH_TOKEN")
    ap.add_argument("--quality-latest", default="",
                    help="results/quality/latest.json yolu (öncelik önizlemesi için)")
    ap.add_argument("--out-dir", default="")
    ap.add_argument("--summary", default="")
    ap.add_argument("--engine-rev", default="?")
    ap.add_argument("--brandpack-rev", default="?")
    ap.add_argument("--run-number", default="")
    ap.add_argument("--run-id", default="")
    ap.add_argument("--gsc-pages-json", default="", help="test: hazır GSC sayfa dökümü")
    ap.add_argument("--gsc-queries-json", default="", help="test: hazır GSC sayfa×sorgu dökümü")
    ap.add_argument("--ga4-json", default="", help="test: hazır GA4 dökümü")
    args = ap.parse_args(argv)

    if args.start_date and args.end_date:
        start, end = args.start_date, args.end_date
    else:
        start, end = date_window(args.window_days, args.end_lag_days)
    token = os.environ.get(args.token_env, "")

    sources = {
        "gsc": {"property": args.gsc_property, "ok": False, "rows": 0, "error": None},
        "ga4": {"property": args.ga4_property, "ok": False, "rows": 0, "error": None},
    }
    gsc_pages, gsc_queries, ga4_pages = [], [], []
    if args.gsc_pages_json:
        gsc_pages = _read_json(args.gsc_pages_json) or []
        gsc_queries = _read_json(args.gsc_queries_json) or []
        sources["gsc"].update(ok=True, rows=len(gsc_pages))
    else:
        try:
            gsc_pages = gsc.fetch_pages(args.gsc_property, token, start, end)
            gsc_queries = gsc.fetch_page_queries(args.gsc_property, token, start, end)
            sources["gsc"].update(ok=True, rows=len(gsc_pages))
        except SourceError as e:
            sources["gsc"]["error"] = str(e)
    if args.ga4_json:
        ga4_pages = _read_json(args.ga4_json) or []
        sources["ga4"].update(ok=True, rows=len(ga4_pages))
    else:
        try:
            ga4_pages = ga4.fetch_pages(args.ga4_property, token, start, end)
            sources["ga4"].update(ok=True, rows=len(ga4_pages))
        except SourceError as e:
            sources["ga4"]["error"] = str(e)

    quality = _read_json(args.quality_latest) if args.quality_latest else None
    if quality and quality.get("contract") != "quality-scan-result":
        quality = None

    pages = merge_pages(gsc_pages, gsc_queries, ga4_pages, quality)
    findings = find_cannibal_queries(gsc_queries)
    now = _dt.datetime.now(_dt.timezone.utc)
    run_id = args.run_id or now.strftime("%Y%m%dT%H%M%SZ")
    scan = {
        "contract": CONTRACT, "contract_version": CONTRACT_VERSION,
        "run": {
            "id": run_id,
            "timestamp_utc": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "site": args.site,
            "engine_rev": args.engine_rev, "brandpack_rev": args.brandpack_rev,
            "workflow_run": args.run_number or None,
            "window": {"start_date": start, "end_date": end,
                       "days": args.window_days,
                       "end_lag_days": args.end_lag_days},
            "sources": sources,
            "quality_run_id": (quality.get("run", {}).get("id")
                               if quality else None),
        },
        "totals": {
            "pages": len(pages),
            "clicks": sum(p["clicks"] for p in pages),
            "impressions": sum(p["impressions"] for p in pages),
            "sessions": sum(p["sessions"] for p in pages),
            "matched_quality_pages": sum(1 for p in pages if p["quality"]),
            "cannibal_queries": len(findings),
        },
        "pages": pages,
        "findings": findings,
    }

    ok_count = sum(1 for s in sources.values() if s["ok"])
    if args.out_dir and ok_count:
        write_outputs(scan, args.out_dir)
    else:
        scan["changes"] = None
    if args.summary:
        with open(args.summary, "w", encoding="utf-8") as f:
            f.write(render_summary(scan))
    print(render_summary(scan))
    if ok_count == 0:
        print("HATA: iki kaynak da erişilemedi — sonuç yazılmadı.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
