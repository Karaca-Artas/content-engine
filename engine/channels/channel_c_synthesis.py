"""Kanal C — sentez: aylık aksiyon kuyruğu (Faz 3 / Adım 16).

Girdi: son performans koşusu (results/performance/latest.json) + son kalite
koşusu (results/quality/latest.json) + marka paketi (ret hafızası varsa).
Çıktı: docs/results-contract.md "action-queue-result" v1.0 —
results/actions/{latest.json, index.json, history/<id>.json}.

Yöntem (docs/method.md §2-3, değişmez kurallar):

    öncelik = (100 − oto%) × gösterim          — YALNIZ OTO puanla
    aylık kuyruk tavanı: --cap (varsayılan 4)  — kalanlar bekleme listesinde

Dürüstlük kuralları:
- Model puanı önceliğe ve kutu atamasına ASLA karışmaz; satırda yalnız bilgi
  olarak taşınır (judged_pct).
- Öncelik, kalite latest'inden YENİDEN hesaplanır (perf dosyasındaki
  priority_auto önizlemesi eski bir kalite koşusuna dayanabilir); iki koşunun
  kimliği de run.inputs bloğuna yazılır.
- Dört kutu ataması deterministik kurallarla yapılır ve her atamanın
  `reason` metni vardır; model çağrısı YOKTUR (bu koşu 0 $).
- (d) yeni sayfa kutusu OTOMATİK ATANMAZ: gerçek talep tespiti Kapı 1 /
  Kanal A işidir; dosyaya açık not yazılır.
- 404 (broken_page) ve kanibal etiket/arşiv sayfaları (c) kutusunun
  ADAYLARIDIR; nihai 301/birleştirme/kaldırma kararı insana aittir. Bunlar
  aylık içerik kuyruğunun 4 satırlık tavanını YEMEZ — ayrı listelerde durur
  (acil site işi ile aylık içerik işi karışmasın diye).
- Ret hafızası (brandpack/live/rejections.json) okunur: reddedilen konuya
  denk düşen sayfa kuyruğa girmez, atlananlar dosyada listelenir.
- Girdi dosyalarından biri yoksa/sözleşmeye uymuyorsa koşu BAŞARISIZ sayılır
  (sentez veri olmadan üretilemez; sessizce boş kuyruk yazmak yanıltıcıdır).

Kutu kuralları (deterministik; eşikler sabittir ve dosyaya yazılır):
- (a) title_meta:  puan iyi (oto ≥ %70) + sıra iyi (≤ 10) + gösterim ≥ 100
                   + CTR < %1 → içerik değil başlık/meta işi.
- (b) enrich:      oto < %70 + gösterim > 0 → sayfa zenginleştirilecek.
- (c) merge_or_remove adayları: broken_page bulguları (urgent listesi) +
                   kanibal sorgu gruplarındaki etiket/arşiv sayfaları
                   (consolidation listesi).
- izlenir:         oto ≥ %70 ve CTR sorunu yok → kuyruğa girmez, sayılır.
- puanlanmamış:    gösterimi olan ama kalite koşusunda puanı olmayan sayfa
                   önceliklenemez; en gösterimli ilk 5'i bilgi olarak yazılır
                   (sonraki kalite koşusu bunları tohumlar).

Stratejik bulgu (docs/method.md "boş kalan kriter = stratejik iş"): bir
kriter puanlanan tüm sayfalarda (≥ MIN_STRATEGIC_PAGES sayfa) sıfırsa sayfa
sayfa listelenmez, TEK stratejik satır olarak çıkar.

Kullanım (Actions'ta, marka deposunda; secret gerekmez)::

    python -m engine.channels.channel_c_synthesis \
        --site https://www.example.com \
        --perf-latest results/performance/latest.json \
        --quality-latest results/quality/latest.json \
        --brandpack-dir brandpack/live \
        --cap 4 --out-dir results/actions --summary rapor.md

Bağımlılık: saf stdlib. Jenerik motor kodu — marka bilgisi içermez.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
from engine.performance.perf_scan import norm_path  # noqa: E402

CONTRACT = "action-queue-result"
CONTRACT_INDEX = "action-queue-index"
CONTRACT_VERSION = "1.0"

DEFAULT_CAP = 4            # docs/method.md: aylık tavan
WAITING_MAX = 20           # bekleme listesi dosya tavanı (okunabilirlik)
MISSING_MAX = 3            # satır başına listelenen eksik kriter sayısı
UNSCORED_MAX = 5           # bilgi: puanlanmamış gösterimli sayfa tavanı
MIN_STRATEGIC_PAGES = 5    # stratejik bulgu için asgari puanlanan sayfa

# (a) title_meta eşikleri — sabit, dosyaya yazılır
A_MIN_AUTO = 70.0
A_MAX_POSITION = 10.0
A_MIN_IMPRESSIONS = 100
A_MAX_CTR = 0.01
# (b) enrich eşiği (docs/method.md: 70+ iyi)
B_MAX_AUTO = 70.0

# Kanibal gruplarında (c) adayı sayılan etiket/arşiv yol kalıbı (jenerik)
CONSOLIDATION_PATH = re.compile(
    r"/(tag|etiket|category|kategori|categories|author|yazar)(/|$)|/page/\d+(/|$)",
    re.IGNORECASE,
)

THRESHOLDS = {
    "priority": "(100 − auto_pct) × impressions — yalnız oto puan",
    "cap": None,  # main doldurur
    "a_title_meta": {"min_auto_pct": A_MIN_AUTO, "max_position": A_MAX_POSITION,
                     "min_impressions": A_MIN_IMPRESSIONS, "max_ctr": A_MAX_CTR},
    "b_enrich": {"max_auto_pct": B_MAX_AUTO, "min_impressions": 1},
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


def load_rejections(brandpack_dir: str) -> list[dict]:
    """Ret hafızası — dosya yoksa boş liste (koşu düşmez)."""
    if not brandpack_dir:
        return []
    data = _read_json(os.path.join(brandpack_dir, "rejections.json"))
    return data if isinstance(data, list) else []


def is_rejected(path: str, rejections: list[dict]) -> dict | None:
    """Sayfa yolu bir ret kaydına denk düşüyor mu? Eşleme: ret konusu sayfa
    yoluyla aynıysa veya yolun içinde geçiyorsa (basit, denetlenebilir kural).
    """
    low = path.lower()
    for r in rejections:
        topic = str(r.get("topic", "")).strip().lower()
        if topic and (topic == low or (topic.startswith("/") and topic in low)):
            return r
    return None


# ------------------------------------------------------------ girdi hazırlığı

def quality_by_path(quality: dict) -> dict[str, dict]:
    out = {}
    for p in quality.get("pages", []):
        if isinstance(p, dict) and p.get("url"):
            out[norm_path(p["url"])] = p
    return out


def broken_by_path(quality: dict) -> dict[str, dict]:
    out = {}
    for f in quality.get("findings", []):
        if isinstance(f, dict) and f.get("kind") == "broken_page" and f.get("url"):
            out[norm_path(f["url"])] = f
    return out


def missing_criteria(qpage: dict) -> list[dict]:
    """Sayfanın en ağır eksik OTO kriterleri (puan < ağırlık), ağırlık farkına
    göre; en fazla MISSING_MAX satır."""
    rows = []
    for c in qpage.get("criteria") or []:
        if not c.get("auto") or c.get("points") is None:
            continue
        gap = (c.get("weight") or 0) - (c.get("points") or 0)
        if gap > 0:
            rows.append({"key": c["key"], "points": c["points"],
                         "weight": c["weight"], "gap": round(gap, 1)})
    rows.sort(key=lambda r: -r["gap"])
    return rows[:MISSING_MAX]


# ------------------------------------------------------------ sınıflandırma

def classify_boxes(perf: dict, quality: dict,
                   rejections: list[dict]) -> dict:
    """Dört kutu ataması + kuyruk adayları. Dönen sözlük: candidates (a+b),
    urgent (404), consolidation (kanibal etiket/arşiv), watch_count,
    unscored_top, skipped_rejected."""
    qmap = quality_by_path(quality)
    broken = broken_by_path(quality)
    quality_run_id = (quality.get("run") or {}).get("id")

    candidates, urgent, watch = [], [], 0
    unscored, skipped = [], []
    for p in perf.get("pages", []):
        path = p.get("path") or ""
        imp = p.get("impressions") or 0
        if not path or imp <= 0:
            continue
        if path in broken:
            f = broken[path]
            urgent.append({
                "path": path, "box": "merge_or_remove",
                "http_status": f.get("http_status"),
                "impressions": imp, "clicks": p.get("clicks") or 0,
                "position": p.get("position"),
                "reason": (f"canlıda HTTP {f.get('http_status')} dönüyor ama "
                           f"{imp} gösterim almaya devam ediyor — 301/geri "
                           "getirme kararı insana aittir (site işi)"),
            })
            continue
        q = qmap.get(path)
        if not q or not q.get("scored") or q.get("auto_pct") is None:
            unscored.append({"path": path, "impressions": imp})
            continue
        auto = q["auto_pct"]
        prio = round((100.0 - auto) * imp, 1)
        rej = is_rejected(path, rejections)
        if rej:
            skipped.append({"path": path, "reason": rej.get("reason"),
                            "rejected_on": rej.get("date")})
            continue
        row = {
            "path": path, "url": p.get("url"),
            "type": q.get("type"),
            "auto_pct": auto, "judged_pct": q.get("judged_pct"),
            "impressions": imp, "clicks": p.get("clicks") or 0,
            "ctr": p.get("ctr"), "position": p.get("position"),
            "top_query": ((p.get("top_queries") or [{}])[0].get("query")),
            "priority_auto": prio,
            "quality_run_id": quality_run_id,
            "missing_criteria": missing_criteria(q),
        }
        ctr = p.get("ctr") if p.get("ctr") is not None else (
            (row["clicks"] / imp) if imp else None)
        pos = p.get("position")
        if (auto >= A_MIN_AUTO and pos is not None and pos <= A_MAX_POSITION
                and imp >= A_MIN_IMPRESSIONS
                and ctr is not None and ctr < A_MAX_CTR):
            row["box"] = "title_meta"
            row["reason"] = (f"sıra {pos} ve {imp} gösterimle CTR yalnız "
                             f"%{(ctr or 0) * 100:.1f}; oto puan zaten "
                             f"%{auto:.0f} — en ucuz kazanç başlık/meta")
            row["effort"] = "düşük"
            candidates.append(row)
        elif auto < B_MAX_AUTO:
            row["box"] = "enrich"
            gaps = ", ".join(m["key"] for m in row["missing_criteria"]) or "—"
            row["reason"] = (f"oto puan %{auto:.0f} (eşik 70 altı) + "
                             f"{imp} gösterim; en ağır eksikler: {gaps}")
            row["effort"] = ("orta" if sum(m["gap"] for m in
                                           row["missing_criteria"]) <= 15
                             else "yüksek")
            candidates.append(row)
        else:
            watch += 1

    urgent.sort(key=lambda r: -r["impressions"])
    candidates.sort(key=lambda r: -r["priority_auto"])
    unscored.sort(key=lambda r: -r["impressions"])

    # kanibal gruplarındaki etiket/arşiv sayfaları → (c) birleştirme adayı
    consolidation: dict[str, dict] = {}
    for f in perf.get("findings", []):
        if f.get("kind") != "cannibal_query":
            continue
        pages = f.get("pages") or []
        arch = [x for x in pages if CONSOLIDATION_PATH.search(x.get("path", ""))]
        core = [x for x in pages if not CONSOLIDATION_PATH.search(x.get("path", ""))]
        if not arch or not core:
            continue
        for x in arch:
            c = consolidation.setdefault(x["path"], {
                "path": x["path"], "box": "merge_or_remove",
                "queries": [], "competing_with": set(), "impressions": 0,
            })
            c["queries"].append(f.get("query"))
            c["impressions"] += x.get("impressions") or 0
            c["competing_with"].update(y["path"] for y in core)
    cons = []
    for c in consolidation.values():
        c["competing_with"] = sorted(c["competing_with"])
        c["reason"] = ("etiket/arşiv sayfası " + str(len(c["queries"])) +
                       " kanibal sorguda gerçek sayfalarla yarışıyor — "
                       "birleştirme/noindex kararı insana aittir")
        cons.append(c)
    cons.sort(key=lambda c: -c["impressions"])

    return {"candidates": candidates, "urgent": urgent,
            "consolidation": cons, "watch_count": watch,
            "unscored_top": unscored[:UNSCORED_MAX],
            "unscored_count": len(unscored),
            "skipped_rejected": skipped}


def strategic_findings(quality: dict) -> list[dict]:
    """Site genelinde sürekli sıfır alan kriter → tek stratejik satır."""
    stats: dict[str, dict] = {}
    for p in quality.get("pages", []):
        if not p.get("scored"):
            continue
        for c in p.get("criteria") or []:
            if c.get("points") is None:
                continue
            s = stats.setdefault(c["key"], {"pages": 0, "zero": 0, "weight": c.get("weight")})
            s["pages"] += 1
            if (c.get("points") or 0) == 0:
                s["zero"] += 1
    out = []
    for key, s in sorted(stats.items()):
        if s["pages"] >= MIN_STRATEGIC_PAGES and s["zero"] == s["pages"]:
            out.append({
                "criterion": key, "pages_scored": s["pages"],
                "weight": s["weight"],
                "note": (f"kriter puanlanan {s['pages']} sayfanın TAMAMINDA "
                         "sıfır — bu bir sayfa sorunu değil şirket/site "
                         "sorunudur; tek stratejik iş olarak ele alınır"),
            })
    return out


# ------------------------------------------------------------ sonuç üretimi

def build_result(site: str, perf: dict, quality: dict, boxes: dict,
                 cap: int, args) -> dict:
    now = _dt.datetime.now(_dt.timezone.utc).replace(microsecond=0)
    run_id = args.run_id or now.strftime("%Y%m%dT%H%M%SZ")
    queue = []
    for i, row in enumerate(boxes["candidates"][:cap], start=1):
        queue.append({"rank": i, **row})
    waiting = boxes["candidates"][cap:cap + WAITING_MAX]
    thresholds = dict(THRESHOLDS)
    thresholds["cap"] = cap
    box_counts = {
        "title_meta": sum(1 for r in boxes["candidates"] if r["box"] == "title_meta"),
        "enrich": sum(1 for r in boxes["candidates"] if r["box"] == "enrich"),
        "merge_or_remove": len(boxes["urgent"]) + len(boxes["consolidation"]),
        "new_page": None,
    }
    return {
        "contract": CONTRACT, "contract_version": CONTRACT_VERSION,
        "run": {
            "id": run_id,
            "timestamp_utc": now.isoformat().replace("+00:00", "Z"),
            "site": site,
            "engine_rev": args.engine_rev, "brandpack_rev": args.brandpack_rev,
            "workflow_run": args.run_number or None,
            "inputs": {
                "performance_run_id": (perf.get("run") or {}).get("id"),
                "performance_window": (perf.get("run") or {}).get("window"),
                "quality_run_id": (quality.get("run") or {}).get("id"),
                "quality_rubric_note": (quality.get("run") or {}).get("rubric_note"),
            },
            "thresholds": thresholds,
        },
        "totals": {
            "queue": len(queue), "waiting": len(waiting),
            "urgent_broken": len(boxes["urgent"]),
            "consolidation_candidates": len(boxes["consolidation"]),
            "watch_pages": boxes["watch_count"],
            "unscored_with_impressions": boxes["unscored_count"],
            "skipped_rejected": len(boxes["skipped_rejected"]),
            "strategic": None,  # main doldurur
            "boxes": box_counts,
        },
        "queue": queue,
        "waiting": waiting,
        "urgent": boxes["urgent"],
        "consolidation": boxes["consolidation"],
        "unscored_top": boxes["unscored_top"],
        "skipped_rejected": boxes["skipped_rejected"],
        "strategic": [],  # main doldurur
        "notes": [
            "öncelik yalnız OTO puanla hesaplanır; model puanı (judged_pct) satırda bilgidir, hesaba karışmaz",
            "(d) yeni sayfa kutusu otomatik atanmaz — gerçek talep tespiti Kapı 1 / Kanal A işidir",
            "(c) satırları ADAYDIR: 301/birleştirme/kaldırma kararı insana aittir; acil 404 listesi aylık tavanı yemez",
            "değişikliklerin etkisi 6-8 hafta kuralına göre yorumlanır (docs/method.md)",
        ],
    }


def build_changes(prev: dict | None, result: dict) -> dict:
    if not prev or prev.get("contract") != CONTRACT:
        return {"first_run": True, "prev_run_id": None,
                "note": "önceki kayıtlı sentez yok — fark üretilmedi"}
    pq = {r["path"] for r in prev.get("queue", [])}
    nq = {r["path"] for r in result.get("queue", [])}
    pu = {r["path"] for r in prev.get("urgent", [])}
    nu = {r["path"] for r in result.get("urgent", [])}
    return {
        "first_run": False,
        "prev_run_id": (prev.get("run") or {}).get("id"),
        "prev_timestamp_utc": (prev.get("run") or {}).get("timestamp_utc"),
        "queue_added": sorted(nq - pq), "queue_removed": sorted(pq - nq),
        "urgent_added": sorted(nu - pu), "urgent_resolved": sorted(pu - nu),
        "note": "kuyruk her ay yeniden sıralanır; çıkan satır 'çözüldü' demek değildir",
    }


def write_outputs(result: dict, out_dir: str) -> dict:
    latest_path = os.path.join(out_dir, "latest.json")
    prev = _read_json(latest_path)
    result["changes"] = build_changes(prev, result)
    run = result["run"]
    _write_json(os.path.join(out_dir, "history", f"{run['id']}.json"), result)
    _write_json(latest_path, result)

    index_path = os.path.join(out_dir, "index.json")
    index = _read_json(index_path)
    if not (isinstance(index, dict) and isinstance(index.get("runs"), list)):
        index = {"contract": CONTRACT_INDEX,
                 "contract_version": CONTRACT_VERSION, "runs": []}
    t = result["totals"]
    entry = {
        "id": run["id"], "timestamp_utc": run["timestamp_utc"],
        "file": f"history/{run['id']}.json",
        "engine_rev": run["engine_rev"], "brandpack_rev": run["brandpack_rev"],
        "performance_run_id": run["inputs"]["performance_run_id"],
        "quality_run_id": run["inputs"]["quality_run_id"],
        "queue": t["queue"], "waiting": t["waiting"],
        "urgent_broken": t["urgent_broken"],
        "consolidation_candidates": t["consolidation_candidates"],
        "strategic": t["strategic"],
    }
    index["runs"] = [entry] + [r for r in index["runs"] if r.get("id") != run["id"]]
    _write_json(index_path, index)
    return result["changes"]


# ------------------------------------------------------------ markdown rapor

def render_summary(result: dict) -> str:
    run, t = result["run"], result["totals"]
    inp = run["inputs"]
    L = [f"## Kanal C sentezi — aylık aksiyon kuyruğu ({run['id']})", "",
         f"Girdi: performans `{inp['performance_run_id']}` + kalite "
         f"`{inp['quality_run_id']}` · tavan {run['thresholds']['cap']} satır · "
         "öncelik = (100 − oto%) × gösterim (yalnız oto; model puanı bilgidir)", ""]

    L += [f"### Aylık kuyruk ({t['queue']} satır — tavan "
          f"{run['thresholds']['cap']})", ""]
    if result["queue"]:
        L += ["| # | Sayfa | Kutu | Oto % | Model % | Göst. | Öncelik | Eksikler | Emek |",
              "|---|---|---|---|---|---|---|---|---|"]
        for r in result["queue"]:
            miss = ", ".join(m["key"] for m in r["missing_criteria"]) or "—"
            L.append("| {} | {} | {} | {} | {} | {} | {} | {} | {} |".format(
                r["rank"], r["path"], r["box"], r["auto_pct"],
                r["judged_pct"] if r["judged_pct"] is not None else "—",
                r["impressions"], r["priority_auto"], miss, r["effort"]))
        L.append("")
        for r in result["queue"]:
            L.append(f"- **{r['path']}** — {r['reason']}")
    else:
        L.append("Kuyruk boş — aday sayfa yok.")
    L.append("")

    if result["urgent"]:
        L += [f"### ACİL — erişilemeyen ama gösterim alan sayfalar "
              f"({t['urgent_broken']}) · (c) adayı, tavanı yemez", "",
              "| Sayfa | HTTP | Göst. | Tık |", "|---|---|---|---|"]
        L += [f"| {r['path']} | {r['http_status']} | {r['impressions']} | {r['clicks']} |"
              for r in result["urgent"]]
        L += ["", "301/geri getirme kararı insana aittir (site işi).", ""]

    if result["consolidation"]:
        L += [f"### Birleştirme adayları — kanibal etiket/arşiv sayfaları "
              f"({t['consolidation_candidates']})", ""]
        for c in result["consolidation"]:
            L.append(f"- `{c['path']}` — {len(c['queries'])} sorguda şu "
                     f"sayfalarla yarışıyor: {', '.join(c['competing_with'])}")
        L.append("")

    if result["strategic"]:
        L += [f"### Stratejik bulgular ({len(result['strategic'])})", ""]
        for s in result["strategic"]:
            L.append(f"- **{s['criterion']}** (ağırlık {s['weight']}): {s['note']}")
        L.append("")

    if result["waiting"]:
        L += [f"### Bekleme listesi ({t['waiting']}; gelecek ay yeniden sıralanır)", ""]
        for r in result["waiting"][:10]:
            L.append(f"- {r['path']} ({r['box']}, öncelik {r['priority_auto']})")
        L.append("")

    if result["unscored_top"]:
        L += [f"### Puanlanmamış gösterimli sayfalar "
              f"(toplam {t['unscored_with_impressions']}; ilk {len(result['unscored_top'])})", ""]
        L += [f"- {r['path']} ({r['impressions']} gösterim)"
              for r in result["unscored_top"]]
        L += ["", "Bunlar önceliklenemez; sonraki kalite koşusu gösterime göre tohumlar.", ""]

    if result["skipped_rejected"]:
        L += [f"### Ret hafızasıyla atlananlar ({t['skipped_rejected']})", ""]
        L += [f"- {r['path']} — {r['reason']}" for r in result["skipped_rejected"]]
        L.append("")

    ch = result.get("changes") or {}
    L += ["### Önceki senteze göre değişim", ""]
    if ch.get("first_run"):
        L.append("İlk kalıcı sentez — kıyaslanacak önceki kayıt yok.")
    elif ch:
        L.append(f"Önceki `{ch['prev_run_id']}` · kuyruğa giren: "
                 f"{', '.join(ch['queue_added']) or '—'} · çıkan: "
                 f"{', '.join(ch['queue_removed']) or '—'} · yeni 404: "
                 f"{', '.join(ch['urgent_added']) or '—'} · düzelen 404: "
                 f"{', '.join(ch['urgent_resolved']) or '—'}")
    L += ["", "_Notlar: " + " · ".join(result["notes"]) + "_"]
    return "\n".join(L) + "\n"


# ---------------------------------------------------------------- ana akış

def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--site", required=True)
    ap.add_argument("--perf-latest", required=True)
    ap.add_argument("--quality-latest", required=True)
    ap.add_argument("--brandpack-dir", default="",
                    help="ret hafızası (rejections.json) için; boşsa okunmaz")
    ap.add_argument("--cap", type=int, default=DEFAULT_CAP)
    ap.add_argument("--out-dir", default="")
    ap.add_argument("--summary", default="")
    ap.add_argument("--engine-rev", default="?")
    ap.add_argument("--brandpack-rev", default="?")
    ap.add_argument("--run-number", default="")
    ap.add_argument("--run-id", default="")
    args = ap.parse_args(argv)

    perf = _read_json(args.perf_latest)
    if not perf or perf.get("contract") != "performance-scan-result":
        print(f"HATA: performans sonucu okunamadı veya sözleşme uymuyor: "
              f"{args.perf_latest}", file=sys.stderr)
        return 1
    quality = _read_json(args.quality_latest)
    if not quality or quality.get("contract") != "quality-scan-result":
        print(f"HATA: kalite sonucu okunamadı veya sözleşme uymuyor: "
              f"{args.quality_latest}", file=sys.stderr)
        return 1

    rejections = load_rejections(args.brandpack_dir)
    boxes = classify_boxes(perf, quality, rejections)
    result = build_result(args.site, perf, quality, boxes, args.cap, args)
    result["strategic"] = strategic_findings(quality)
    result["totals"]["strategic"] = len(result["strategic"])

    if args.out_dir:
        write_outputs(result, args.out_dir)
    else:
        result["changes"] = None
    if args.summary:
        with open(args.summary, "w", encoding="utf-8") as f:
            f.write(render_summary(result))
    print(render_summary(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
