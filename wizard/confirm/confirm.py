"""Teyit akışı — Faz 0, Tur 2 (wizard/README.md).

Keşif taslağını (Tur 1 çıktısı) ve anket cevaplarını alır, kullanıcıyla
yürütülecek soru-cevap turunun GÜNDEMİNİ üretir; onaylı cevapları doğrulayıp
canlı bilgi paketine (`brandpack/live/`) işler. İki komut:

``prepare``
    Girdi:  keşif taslağı klasörü (facts.draft.json, terms.draft.json,
            open_questions.json) + isteğe bağlı anket cevap metni
            (anket formunun "derle" çıktısı, düz metin).
    Çıktı:  teyit oturumu dosyası (``session.json``) — her soru; varsa
            anketten gelen ön-cevap ipucu ve kanıt URL'leriyle. Anket ile
            site ÇELİŞİRSE motor seçmez, çelişki sorusu üretir (§6).

``apply``
    Girdi:  cevapları doldurulmuş oturum dosyası + keşif taslağı klasörü.
    Çıktı:  ``brandpack/live/facts.json`` + ``terms.json`` (şemalara uygun)
            + ``approval_log.json`` (hangi soruya hangi cevabın ne zaman
            onaylandığının izi).

İlkeler (docs/method.md):
- §6  Çelişki işaretli soru ERTELENEMEZ; cevapsız/ertelenmiş soru varken
      koşullar sağlanmadan canlıya yazım yapılmaz.
- §9  Sıfır-başlangıç: ``named_references`` yalnız yazılı izin onayı
      (``permission_confirmed: true``) ile dolar; ``not_offered`` yalnız
      kullanıcı cevabından gelir. Taslak, onay değildir.

Cevap doldurma sözleşmesi (session.json → questions[i]):
- ``status``: "open" → "answered" | "deferred"
- ``answer``: konuya göre yapılandırılmış nesne (aşağıda TOPIC_HELP) —
  serbest metin not için ``answer.note`` alanı kullanılır.
- ``deferred`` için ``defer_reason`` zorunlu; ``conflict: true`` sorular
  ertelenemez.

Kullanım::

    python -m wizard.confirm.confirm prepare \
        --draft brandpack/draft --survey anket-cevaplari.txt \
        --out brandpack/confirm/session.json

    python -m wizard.confirm.confirm apply \
        --session brandpack/confirm/session.json \
        --draft brandpack/draft --live brandpack/live

Harici bağımlılık yok (saf stdlib).
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import re
import sys

# --- Konu başına beklenen cevap biçimi (belgelendirme + doğrulama) -----------

TOPIC_HELP: dict[str, str] = {
    "brand_name": '{"value": "Marka Adı"}',
    "moq": '{"value": 1000} veya ürün bazında {"value": {"ürün tipi": 1000, ...}}',
    "lead_times": '{"value": {"iş tipi": "3-4 hafta", ...}}',
    "certificates": '{"value": ["ISO 9001", ...]} (boş liste = sertifika yok)',
    "named_references": '{"value": ["Marka X", ...], "permission_confirmed": true} — izin onayı ZORUNLU',
    "not_offered": '{"value": ["yapılmayan iş", ...]}',
    "products": '{"approve_draft": true, "remove": ["yanlış aday"], "add": [{"name": "eksik ürün"}]} veya {"value": [{"name": ...}, ...]}',
    "sectors": '{"approve_draft": true, "remove": [...], "add": [{"name": ...}]} veya {"value": [...]}',
    "terms": '{"approved": true, "remove": ["kelime"], "add": [{"lang": "en", "correct": "...", "traps": [...]}], "traps": [{"lang": "en", "correct": "kelime", "traps": ["tuzak", ...]}]}',
}

_CONFLICT_MARK = re.compile(r"ÇELİŞKİ", re.IGNORECASE)


def _today() -> str:
    return _dt.date.today().isoformat()


def _load_json(path: str):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _write_json(path: str, obj) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)
    print(f"[confirm] yazıldı: {path}", file=sys.stderr)


def _digits(s: str) -> str:
    return re.sub(r"[^0-9]", "", s or "")


# --- Anket cevap metnini ayrıştırma ------------------------------------------
# Anket formunun (wizard/survey) "derle" çıktısı: "N. Başlık..." + girintili
# gövde satırları. Ayrıştırma en-iyi-çaba; bulunamayan alan yok sayılır.

def parse_survey(text: str) -> dict:
    items: dict[int, str] = {}
    current = None
    for line in text.splitlines():
        m = re.match(r"^(\d+)\.\s", line)
        if m:
            current = int(m.group(1))
            items[current] = line.strip()
        elif current is not None and (line.startswith("   ") or line.startswith("\t")):
            items[current] += "\n" + line.strip()

    def field(item: int, label: str) -> str:
        body = items.get(item, "")
        m = re.search(re.escape(label) + r":\s*([^·\n]+)", body)
        v = m.group(1).strip() if m else ""
        return "" if v in ("", "—", "-") else v

    def body_of(item: int) -> str:
        body = items.get(item, "")
        lines = body.split("\n")[1:]
        v = " ".join(l for l in lines if l).strip()
        return "" if v in ("", "—", "-") else v

    out = {
        "raw_items": items,
        "moq": field(4, "MOQ"),
        "lead_time": field(4, "Termin"),
        "sample_time": field(4, "Numune"),
        "delivery": field(4, "Teslim"),
        "certificates": body_of(5),
        "certificates_none": "Sertifika yok" in items.get(5, ""),
        "not_offered": body_of(6),
        "references": body_of(9),
        "products_desc": body_of(2),
        "markets": body_of(3),
    }
    return out


# --- prepare -----------------------------------------------------------------

def _survey_hint_for(topic: str, sv: dict) -> str:
    if not sv:
        return ""
    if topic == "moq" and sv.get("moq"):
        return f"Anket cevabı: MOQ = '{sv['moq']}'"
    if topic == "lead_times" and (sv.get("lead_time") or sv.get("sample_time")):
        bits = []
        if sv.get("lead_time"):
            bits.append(f"termin '{sv['lead_time']}'")
        if sv.get("sample_time"):
            bits.append(f"numune '{sv['sample_time']}'")
        return "Anket cevabı: " + " · ".join(bits)
    if topic == "certificates":
        if sv.get("certificates_none"):
            return "Anket cevabı: sertifika YOK işaretlendi"
        if sv.get("certificates"):
            return f"Anket cevabı: {sv['certificates'][:200]}"
    if topic == "not_offered" and sv.get("not_offered"):
        return f"Anket cevabı: {sv['not_offered'][:200]}"
    if topic == "named_references" and sv.get("references"):
        return f"Anket cevabı: {sv['references'][:200]}"
    if topic == "products" and sv.get("products_desc"):
        return f"Anket 2. soru: {sv['products_desc'][:200]}"
    return ""


def _survey_conflicts(sv: dict, facts_draft: dict) -> list[dict]:
    """Anket ile site taslağı arasındaki çelişkileri soruya çevir (§6)."""
    qs: list[dict] = []
    draft_meta = facts_draft.get("_draft", {})
    site = draft_meta.get("source_site", "site")

    # MOQ: anket değeri, sitedeki tek/çok adaydan farklıysa
    sv_moq = _digits(sv.get("moq", ""))
    draft_moq = facts_draft.get("moq")
    if sv_moq and draft_moq is not None and _digits(str(draft_moq)) != sv_moq:
        qs.append({
            "topic": "moq",
            "question": (f"ÇELİŞKİ: ankette MOQ '{sv['moq']}', sitede '{draft_moq}' görünüyor. "
                         "Hangisi geçerli? (canlı sayfaların güncellenmesi gerekiyorsa not düşün)"),
            "why": "Anket ile site çelişiyor — motor seçmez (§6).",
            "evidence": [site],
            "conflict": True,
            "origin": "survey-conflict",
        })

    # Sertifika: ankette YOK, sitede aday var
    if sv.get("certificates_none") and facts_draft.get("certificates"):
        qs.append({
            "topic": "certificates",
            "question": ("ÇELİŞKİ: ankette 'sertifika yok' işaretli ama sitede şu adaylar "
                         f"bulundu: {', '.join(facts_draft['certificates'])}. Hangisi doğru?"),
            "why": "Anket ile site çelişiyor — motor seçmez (§6).",
            "evidence": [site],
            "conflict": True,
            "origin": "survey-conflict",
        })
    return qs


def cmd_prepare(args) -> int:
    facts_draft = _load_json(os.path.join(args.draft, "facts.draft.json"))
    open_questions = _load_json(os.path.join(args.draft, "open_questions.json"))

    sv: dict = {}
    if args.survey:
        with open(args.survey, encoding="utf-8") as f:
            sv = parse_survey(f.read())

    questions: list[dict] = []

    # Marka adı teyidi — facts.json'un zorunlu alanı; taslak onay değildir (§9)
    brand = facts_draft.get("brand_name", "")
    questions.append({
        "topic": "brand_name",
        "question": (f"Marka adı '{brand}' olarak tespit edildi. İçeriklerde bu yazımla mı "
                     "kullanılmalı?" if brand else
                     "Siteden marka adı çıkarılamadı. Marka adı (içerikte kullanılacak yazımıyla) nedir?"),
        "why": "facts.json zorunlu alanı — taslak onay değildir (§9).",
        "evidence": facts_draft.get("_draft", {}).get("brand_name_evidence", []),
        "conflict": False,
        "origin": "prepare",
    })

    for q in open_questions:
        q = dict(q)
        q.setdefault("origin", "discovery")
        q["conflict"] = bool(_CONFLICT_MARK.search(q.get("why", "")))
        questions.append(q)

    questions.extend(_survey_conflicts(sv, facts_draft))

    # Sektör adayları için teyit (taslak meta'da var ama keşif sorusu üretmiyor)
    sectors = facts_draft.get("_draft", {}).get("sector_candidates", [])
    if sectors:
        questions.append({
            "topic": "sectors",
            "question": ("Sektör adayları: " + ", ".join(s["name"] for s in sectors[:15])
                         + ". Liste doğru ve tam mı?"),
            "why": "Yol deseni temelli otomatik çıkarım — onay gerekli.",
            "evidence": sum((s.get("evidence", [])[:1] for s in sectors[:5]), []),
            "conflict": False,
            "origin": "prepare",
        })

    for i, q in enumerate(questions, 1):
        q["id"] = f"q{i:02d}"
        q["survey_hint"] = q.get("survey_hint") or _survey_hint_for(q["topic"], sv)
        q["answer_format"] = TOPIC_HELP.get(q["topic"], '{"note": "serbest metin"}')
        q["status"] = "open"
        q["answer"] = None

    session = {
        "created_at": _today(),
        "source": {"draft_dir": args.draft, "survey_file": args.survey or None,
                   "site": facts_draft.get("_draft", {}).get("source_site", "")},
        "survey_parsed": {k: v for k, v in sv.items() if k != "raw_items"} if sv else None,
        "questions": questions,
    }
    _write_json(args.out, session)
    n_conf = sum(1 for q in questions if q["conflict"])
    print(f"[confirm] {len(questions)} soru ({n_conf} çelişki işaretli) → {args.out}",
          file=sys.stderr)
    return 0


# --- apply -------------------------------------------------------------------

class ApplyError(Exception):
    pass


def _ans(q: dict) -> dict:
    a = q.get("answer")
    if not isinstance(a, dict):
        raise ApplyError(f"{q['id']} ({q['topic']}): cevap yapılandırılmış nesne değil. "
                         f"Beklenen biçim: {q.get('answer_format')}")
    return a


def _check_answers(questions: list[dict]) -> None:
    problems = []
    for q in questions:
        st = q.get("status")
        if st == "open":
            problems.append(f"{q['id']} ({q['topic']}): CEVAPSIZ")
        elif st == "deferred":
            if q.get("conflict"):
                problems.append(f"{q['id']} ({q['topic']}): ÇELİŞKİ sorusu ertelenemez (§6)")
            elif not q.get("defer_reason"):
                problems.append(f"{q['id']} ({q['topic']}): erteleme gerekçesi (defer_reason) yok")
        elif st == "answered":
            if not isinstance(q.get("answer"), dict):
                problems.append(f"{q['id']} ({q['topic']}): status=answered ama cevap nesnesi yok")
        else:
            problems.append(f"{q['id']} ({q['topic']}): geçersiz status '{st}'")
    if problems:
        raise ApplyError("Canlıya yazım REDDEDİLDİ:\n  - " + "\n  - ".join(problems))


def _apply_list_edit(base: list[dict], a: dict, key: str = "name") -> list[dict]:
    """approve_draft/remove/add veya value biçimli liste cevabını uygula."""
    if "value" in a:
        out = []
        for item in a["value"]:
            out.append({key: item} if isinstance(item, str) else dict(item))
        return out
    if not a.get("approve_draft"):
        raise ApplyError(f"Liste cevabı ya 'value' ya 'approve_draft: true' içermeli: {a}")
    removed = {str(r).strip().lower() for r in a.get("remove", [])}
    out = [dict(item) for item in base
           if str(item.get(key, "")).strip().lower() not in removed]
    for item in a.get("add", []):
        out.append({key: item} if isinstance(item, str) else dict(item))
    return out


def _build_facts(facts_draft: dict, by_topic: dict[str, dict], today: str) -> dict:
    facts: dict = {
        "brand_name": facts_draft.get("brand_name", ""),
        "approved_at": today,
        "products": [],
        "moq": None,
        "lead_times": {},
        "certificates": [],
        "named_references": [],
        "not_offered": [],
    }

    if "brand_name" in by_topic and by_topic["brand_name"]["status"] == "answered":
        v = str(_ans(by_topic["brand_name"]).get("value", "")).strip()
        if not v:
            raise ApplyError("brand_name cevabında 'value' boş — zorunlu alan.")
        facts["brand_name"] = v
    else:
        raise ApplyError("Marka adı sorusu cevaplanmadan facts.json yazılamaz (zorunlu alan, §9).")

    if "moq" in by_topic and by_topic["moq"]["status"] == "answered":
        v = _ans(by_topic["moq"]).get("value")
        if not isinstance(v, (int, dict)):
            raise ApplyError(f"moq cevabı tamsayı veya nesne olmalı, gelen: {v!r}")
        facts["moq"] = v

    if "lead_times" in by_topic and by_topic["lead_times"]["status"] == "answered":
        v = _ans(by_topic["lead_times"]).get("value")
        if not isinstance(v, dict):
            raise ApplyError(f"lead_times cevabı nesne olmalı (iş tipi → süre), gelen: {v!r}")
        facts["lead_times"] = v

    if "certificates" in by_topic and by_topic["certificates"]["status"] == "answered":
        v = _ans(by_topic["certificates"]).get("value")
        if not isinstance(v, list) or not all(isinstance(x, str) for x in v):
            raise ApplyError(f"certificates cevabı dize listesi olmalı, gelen: {v!r}")
        facts["certificates"] = v

    # §9: named_references YALNIZ izin onayıyla dolar
    if "named_references" in by_topic and by_topic["named_references"]["status"] == "answered":
        a = _ans(by_topic["named_references"])
        vals = a.get("value") or []
        if vals and not a.get("permission_confirmed"):
            raise ApplyError("named_references: 'permission_confirmed: true' olmadan isim "
                             "yazılamaz (§9 — yazılı izin onayı).")
        if not all(isinstance(x, str) for x in vals):
            raise ApplyError("named_references 'value' dize listesi olmalı.")
        facts["named_references"] = vals

    # §9: not_offered YALNIZ kullanıcıdan gelir
    if "not_offered" in by_topic and by_topic["not_offered"]["status"] == "answered":
        v = _ans(by_topic["not_offered"]).get("value")
        if not isinstance(v, list) or not all(isinstance(x, str) for x in v):
            raise ApplyError(f"not_offered cevabı dize listesi olmalı, gelen: {v!r}")
        facts["not_offered"] = v

    draft_products = [{"name": p.get("name", "")} for p in facts_draft.get("products", [])]
    if "products" in by_topic and by_topic["products"]["status"] == "answered":
        facts["products"] = _apply_list_edit(draft_products, _ans(by_topic["products"]))

    if "sectors" in by_topic and by_topic["sectors"]["status"] == "answered":
        base = [{"name": s.get("name", "")} for s in
                facts_draft.get("_draft", {}).get("sector_candidates", [])]
        facts["sectors"] = _apply_list_edit(base, _ans(by_topic["sectors"]))

    return facts


def _build_terms(terms_draft: dict, by_topic: dict[str, dict], today: str) -> dict:
    terms = [dict(t) for t in terms_draft.get("terms", [])]
    languages = list(terms_draft.get("languages", []))

    if "terms" in by_topic and by_topic["terms"]["status"] == "answered":
        a = _ans(by_topic["terms"])
        if not a.get("approved") and not a.get("value"):
            raise ApplyError("terms cevabı 'approved: true' (düzenlemelerle) veya 'value' içermeli.")
        removed = {str(r).strip().lower() for r in a.get("remove", [])}
        terms = [t for t in terms if t.get("correct", "").strip().lower() not in removed]
        traps_by_key = {(t.get("lang"), str(t.get("correct", "")).strip().lower()): t.get("traps", [])
                        for t in a.get("traps", [])}
        for t in terms:
            key = (t.get("lang"), t.get("correct", "").strip().lower())
            if key in traps_by_key:
                t["traps"] = list(traps_by_key[key])
            t["evidence"] = f"Tur 2 onayı {today}"
        for add in a.get("add", []):
            if not isinstance(add, dict) or "lang" not in add or "correct" not in add:
                raise ApplyError(f"terms 'add' öğesi lang+correct içermeli: {add!r}")
            add = dict(add)
            add.setdefault("traps", [])
            add.setdefault("evidence", f"Tur 2 onayı {today} (kullanıcı ekledi)")
            terms.append(add)
            if add["lang"] not in languages:
                languages.append(add["lang"])
    else:
        # Terim sorusu cevaplanmadıysa (ertelenmişse) taslak terimler canlıya
        # ONAYSIZ geçemez (§9) — boş sözlük yazılır.
        terms = []

    return {"languages": languages, "terms": terms}


def _validate_schemas(facts: dict, terms: dict) -> None:
    """Şemaların zorunlu koşullarını stdlib ile denetle (jsonschema yok)."""
    for req in ("brand_name", "approved_at"):
        if not facts.get(req):
            raise ApplyError(f"facts.json şema ihlali: '{req}' zorunlu.")
    if facts["moq"] is not None and not isinstance(facts["moq"], (int, dict)):
        raise ApplyError("facts.json şema ihlali: moq integer/object/null olmalı.")
    for lst in ("products", "certificates", "named_references", "not_offered"):
        if not isinstance(facts.get(lst), list):
            raise ApplyError(f"facts.json şema ihlali: '{lst}' liste olmalı.")
    if not isinstance(facts.get("lead_times"), dict):
        raise ApplyError("facts.json şema ihlali: lead_times nesne olmalı.")
    for t in terms.get("terms", []):
        if "lang" not in t or "correct" not in t:
            raise ApplyError(f"terms.json şema ihlali: lang+correct zorunlu: {t!r}")


def cmd_apply(args) -> int:
    session = _load_json(args.session)
    facts_draft = _load_json(os.path.join(args.draft, "facts.draft.json"))
    terms_draft = _load_json(os.path.join(args.draft, "terms.draft.json"))
    today = _today()

    live_facts = os.path.join(args.live, "facts.json")
    live_terms = os.path.join(args.live, "terms.json")
    if not args.force and (os.path.exists(live_facts) or os.path.exists(live_terms)):
        raise ApplyError(f"{args.live} altında canlı paket zaten var — üzerine yazmak için --force.")

    questions = session.get("questions", [])
    _check_answers(questions)
    by_topic: dict[str, dict] = {}
    for q in questions:
        # Aynı konuda birden çok soru varsa (keşif + çelişki) cevaplanmış
        # olan öncelenir; birden çok cevaplı varsa sondaki esas alınır.
        if q["topic"] not in by_topic or q["status"] == "answered":
            by_topic[q["topic"]] = q

    facts = _build_facts(facts_draft, by_topic, today)
    terms = _build_terms(terms_draft, by_topic, today)
    _validate_schemas(facts, terms)

    log = {
        "applied_at": today,
        "session_file": args.session,
        "draft_source": session.get("source", {}),
        "entries": [{
            "id": q["id"], "topic": q["topic"], "question": q["question"],
            "status": q["status"],
            "answer": q.get("answer"),
            "defer_reason": q.get("defer_reason"),
        } for q in questions],
    }

    _write_json(live_facts, facts)
    _write_json(live_terms, terms)
    _write_json(os.path.join(args.live, "approval_log.json"), log)
    n_def = sum(1 for q in questions if q["status"] == "deferred")
    print(f"[confirm] canlı paket yazıldı: {args.live} "
          f"({len(questions)} soru; {n_def} ertelendi — ertelenenler canlıya İŞLENMEDİ)",
          file=sys.stderr)
    return 0


# --- CLI ---------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Faz 0 Tur 2 — teyit akışı")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("prepare", help="Soru gündemini (session.json) üret")
    p.add_argument("--draft", default="brandpack/draft", help="Keşif taslağı klasörü")
    p.add_argument("--survey", default="", help="Anket cevap metni (düz metin dosya)")
    p.add_argument("--out", default="brandpack/confirm/session.json")
    p.set_defaults(fn=cmd_prepare)

    a = sub.add_parser("apply", help="Onaylı cevapları brandpack/live'a işle")
    a.add_argument("--session", default="brandpack/confirm/session.json")
    a.add_argument("--draft", default="brandpack/draft")
    a.add_argument("--live", default="brandpack/live")
    a.add_argument("--force", action="store_true", help="Var olan canlı paketin üzerine yaz")
    a.set_defaults(fn=cmd_apply)

    args = ap.parse_args(argv)
    try:
        return args.fn(args)
    except ApplyError as e:
        print(f"[confirm] HATA: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
