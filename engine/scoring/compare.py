"""Koşular arası karşılaştırma — tarama sonuçlarının farkı (Adım 8 / B yönü).

Yeni tarama sonucu, depodaki bir önceki sonuçla (results/quality/latest.json)
kıyaslanır ve fark `changes` bloğu olarak üretilir. Amaç geri bildirim
döngüsüdür: bir sayfa zenginleştirilince puanı yükseldi mi, MOQ çelişkisi
sitede düzeltilince bulgu kapandı mı — bunlar ancak koşular arası farkla
görülür (docs/method.md 6-8 hafta kuralı).

Dürüstlük kuralı: motor sürümü, cetvel sürümleri veya brandpack sürümü iki
koşu arasında değiştiyse fark bloğu bunu `method_changed` ile işaretler —
puan değişimi siteden değil yöntem değişikliğinden gelmiş olabilir ve
yorum insana bırakılır.

Jenerik motor kodu — marka bilgisi içermez (docs/method.md §9).
Veri sözleşmesi: docs/results-contract.md (v1.1) — model yargısı (Adım 10):
model kimliği veya rubrik sürümü değişirse `method_changed.judge` true olur;
model puan farkları `judged_score_changes` listesinde oto farklardan AYRI durur.
"""

from __future__ import annotations


def finding_key(f: dict) -> tuple:
    """Bulgunun kimliği — iki koşuda aynı bulguyu eşlemek için.

    trap_term: sayfa + tuzak terim (adet değişimi aynı bulgu sayılır).
    fact_conflict: sayfa + alan + sayfadaki değer (sayfadaki değer değişirse
    eski bulgu kapanır, yenisi açılır — bu istenen davranış: 40.000→3.000
    hâlâ çelişkidir ama FARKLI bir çelişkidir).
    """
    kind = f.get("kind", "")
    if kind == "trap_term":
        return (kind, f.get("url", ""), str(f.get("trap", "")).lower())
    if kind == "fact_conflict":
        return (kind, f.get("url", ""), f.get("field", ""), str(f.get("page_value", "")))
    if kind == "broken_page":
        # hata metni koşudan koşuya değişebilir; kimlik = sayfa + HTTP durumu
        return (kind, f.get("url", ""), str(f.get("http_status", "")))
    return (kind, f.get("url", ""), str(sorted(f.items())))


def _pages_by_url(scan: dict) -> dict:
    return {p.get("url", ""): p for p in scan.get("pages", []) if p.get("url")}


def _pct(p: dict):
    if not p.get("scored"):
        return None
    poss = p.get("auto_possible") or 0
    return round(100.0 * (p.get("auto_earned") or 0) / poss, 1) if poss else None


def _judged_pct(p: dict):
    if not p.get("scored"):
        return None
    poss = p.get("judged_possible") or 0
    return round(100.0 * (p.get("judged_earned") or 0) / poss, 1) if poss else None


def _judge_sig(run: dict):
    """Yargı yönteminin kimliği: (model, rubrik sürümü); kapalıysa None."""
    j = run.get("judge") or {}
    if not j.get("enabled"):
        return None
    return (j.get("model"), j.get("prompt_version"))


def diff(prev: dict | None, new: dict) -> dict:
    """İki tarama sonucunun farkı → `changes` bloğu (sözleşme v1.0).

    prev None ise (ilk kalıcı koşu) first_run=True döner ve fark alanları boş.
    """
    if not prev:
        return {"first_run": True, "prev_run_id": None,
                "note": "önceki kayıtlı koşu yok — fark üretilmedi"}

    prev_run, new_run = prev.get("run", {}), new.get("run", {})
    pp, np_ = _pages_by_url(prev), _pages_by_url(new)
    prev_urls, new_urls = set(pp), set(np_)

    type_changes, score_changes, judged_score_changes = [], [], []
    for url in sorted(prev_urls & new_urls):
        a, b = pp[url], np_[url]
        if a.get("type") != b.get("type"):
            type_changes.append({"url": url, "prev": a.get("type"), "new": b.get("type")})
        pa, pb = _pct(a), _pct(b)
        if pa is not None and pb is not None and abs(pb - pa) >= 0.1:
            score_changes.append({"url": url, "prev_pct": pa, "new_pct": pb,
                                  "delta_pct": round(pb - pa, 1)})
        ja, jb = _judged_pct(a), _judged_pct(b)
        if ja is not None and jb is not None and abs(jb - ja) >= 0.1:
            judged_score_changes.append({"url": url, "prev_pct": ja, "new_pct": jb,
                                         "delta_pct": round(jb - ja, 1)})
    score_changes.sort(key=lambda r: -abs(r["delta_pct"]))
    judged_score_changes.sort(key=lambda r: -abs(r["delta_pct"]))

    prev_f = {finding_key(f): f for f in prev.get("findings", [])}
    new_f = {finding_key(f): f for f in new.get("findings", [])}
    new_findings = [new_f[k] for k in sorted(new_f.keys() - prev_f.keys(), key=str)]
    resolved = [prev_f[k] for k in sorted(prev_f.keys() - new_f.keys(), key=str)]

    method_changed = {
        "engine": prev_run.get("engine_rev") != new_run.get("engine_rev"),
        "rubrics": prev_run.get("rubric_versions") != new_run.get("rubric_versions"),
        "brandpack": prev_run.get("brandpack_rev") != new_run.get("brandpack_rev"),
        # model veya sabit rubrik sürümü değişti / yargı açılıp kapandı →
        # model puan farkları yöntemden gelebilir (dürüstlük kuralı)
        "judge": _judge_sig(prev_run) != _judge_sig(new_run),
    }
    return {
        "first_run": False,
        "prev_run_id": prev_run.get("id"),
        "prev_timestamp_utc": prev_run.get("timestamp_utc"),
        "method_changed": method_changed,
        "new_pages": sorted(new_urls - prev_urls),
        "removed_pages": sorted(prev_urls - new_urls),
        "type_changes": type_changes,
        "score_changes": score_changes,
        "judged_score_changes": judged_score_changes,
        "new_findings": new_findings,
        "resolved_findings": resolved,
        "summary": {
            "pages_changed": len(score_changes),
            "judged_pages_changed": len(judged_score_changes),
            "new_pages": len(new_urls - prev_urls),
            "removed_pages": len(prev_urls - new_urls),
            "new_findings": len(new_findings),
            "resolved_findings": len(resolved),
        },
    }
