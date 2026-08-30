"""Search Console bağlayıcısı — Faz 2 (Adım 14).

Kimlik: kısa ömürlü OAuth erişim jetonu (Actions'ta anahtarsız WIF ile üretilir,
GOOGLE_OAUTH_TOKEN ortam değişkeninden gelir). Depoda kalıcı anahtar YOKTUR.
Gerekli kapsam: https://www.googleapis.com/auth/webmasters.readonly

Not: GSC verisi 2-3 gün gecikmelidir; değerlendirme 6-8 hafta kuralına tabidir
(method.md §7). Bu modül yalnız veri çeker; yorum üretmez.
Bağımlılık: saf stdlib.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request

API_BASE = "https://searchconsole.googleapis.com/webmasters/v3/sites"
ROW_LIMIT = 25000


class SourceError(Exception):
    """API hatası — çağıran taraf koşuyu düşürmeden raporlayabilsin diye
    durum kodu ve gövde özetini taşır."""

    def __init__(self, source: str, status: int | None, detail: str):
        self.source, self.status, self.detail = source, status, detail
        super().__init__(f"{source}: HTTP {status}: {detail}")


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
        raise SourceError("gsc", e.code, detail) from e
    except (urllib.error.URLError, TimeoutError, ValueError) as e:
        raise SourceError("gsc", None, str(e)[:300]) from e


def query(site_property: str, token: str, body: dict) -> list[dict]:
    """searchAnalytics/query — ham satır listesi döndürür (rows yoksa boş)."""
    url = f"{API_BASE}/{urllib.parse.quote(site_property, safe='')}/searchAnalytics/query"
    data = _post(url, token, body)
    return data.get("rows") or []


def fetch_pages(site_property: str, token: str,
                start_date: str, end_date: str) -> list[dict]:
    """Sayfa bazlı tıklama/gösterim/CTR/ortalama sıra.

    Dönen satır: {"page": <tam URL>, "clicks", "impressions", "ctr", "position"}
    """
    rows = query(site_property, token, {
        "startDate": start_date, "endDate": end_date,
        "dimensions": ["page"], "rowLimit": ROW_LIMIT,
    })
    return [{"page": r["keys"][0], "clicks": r.get("clicks", 0),
             "impressions": r.get("impressions", 0),
             "ctr": r.get("ctr", 0.0), "position": r.get("position", 0.0)}
            for r in rows]


def fetch_page_queries(site_property: str, token: str,
                       start_date: str, end_date: str,
                       row_limit: int = ROW_LIMIT) -> list[dict]:
    """Sayfa × sorgu dökümü — sayfa başına en iyi sorgular ve kanibalizm
    ön-tespiti (aynı sorguda gösterim alan birden çok sayfa) için.

    Dönen satır: {"page", "query", "clicks", "impressions", "position"}
    """
    rows = query(site_property, token, {
        "startDate": start_date, "endDate": end_date,
        "dimensions": ["page", "query"], "rowLimit": row_limit,
    })
    return [{"page": r["keys"][0], "query": r["keys"][1],
             "clicks": r.get("clicks", 0),
             "impressions": r.get("impressions", 0),
             "position": r.get("position", 0.0)}
            for r in rows]


def fetch(config: dict) -> dict:  # geriye dönük iskelet arayüzü
    raise NotImplementedError(
        "fetch_pages / fetch_page_queries kullanın (Adım 14)")
