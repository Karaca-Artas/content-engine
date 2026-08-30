"""GA4 bağlayıcısı (Data API v1beta) — Faz 2 (Adım 14).

Kimlik: kısa ömürlü OAuth erişim jetonu (Actions'ta anahtarsız WIF ile üretilir).
Gerekli kapsam: https://www.googleapis.com/auth/analytics.readonly
Bağımlılık: saf stdlib.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request

from engine.sources.gsc import SourceError

API_BASE = "https://analyticsdata.googleapis.com/v1beta/properties"
ROW_LIMIT = 25000


def _post(url: str, token: str, body: dict, timeout: float = 60.0) -> dict:
    req = urllib.request.Request(
        url,
        data=json.dumps(body).encode("utf-8"),
        headers={"Authorization": f"Bearer {token}",
                 "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")[:300]
        raise SourceError("ga4", e.code, detail) from e
    except (urllib.error.URLError, TimeoutError, ValueError) as e:
        raise SourceError("ga4", None, str(e)[:300]) from e


def fetch_pages(property_id: str, token: str,
                start_date: str, end_date: str) -> list[dict]:
    """Sayfa yolu bazlı oturum/etkileşim/kullanıcı.

    property_id: sayısal GA4 mülk numarası (örn. "336534572").
    Dönen satır: {"path", "sessions", "engaged_sessions", "users"}
    (etkileşim oranı çağıran tarafta engaged_sessions/sessions olarak türetilir).
    """
    pid = str(property_id).removeprefix("properties/")
    url = f"{API_BASE}/{pid}:runReport"
    body = {
        "dateRanges": [{"startDate": start_date, "endDate": end_date}],
        "dimensions": [{"name": "pagePath"}],
        "metrics": [{"name": "sessions"}, {"name": "engagedSessions"},
                    {"name": "totalUsers"}],
        "limit": str(ROW_LIMIT),
    }
    data = _post(url, token, body)
    out = []
    for r in data.get("rows") or []:
        vals = [v.get("value", "0") for v in r.get("metricValues", [])]
        vals += ["0"] * (3 - len(vals))
        out.append({
            "path": r["dimensionValues"][0].get("value", ""),
            "sessions": int(float(vals[0])),
            "engaged_sessions": int(float(vals[1])),
            "users": int(float(vals[2])),
        })
    return out


def fetch(config: dict) -> dict:  # geriye dönük iskelet arayüzü
    raise NotImplementedError("fetch_pages kullanın (Adım 14)")
