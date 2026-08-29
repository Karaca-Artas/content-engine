# Tarama sonuçları veri sözleşmesi — v1.0

Sürüm 1.0 · 29 Ağustos 2026 (Adım 8). Bu belge, kalite taraması sonuçlarının marka
deposuna nasıl yazıldığını ve panonun (dashboard) bu dosyaları nasıl okuyacağını tanımlar.
Sözleşme sürümlenir: alan eklenmesi geriye uyumluysa küçük sürüm, alan değişir/kalkarsa
büyük sürüm artar ve pano her iki sürümü de tanıyana kadar eski dosyalar dönüştürülmez.
Her dosya kendi `contract` + `contract_version` alanını taşır — pano önce bunu doğrular.

## Dosya düzeni (marka deposunda)

```
results/
  quality/
    latest.json          # son koşunun tam dökümü — pano varsayılan olarak bunu okur
    index.json           # koşu listesi (özet satırlar, en yeni en üstte) — trend için
    history/
      <run-id>.json      # her koşunun arşivi (latest ile birebir aynı içerik)
```

- `run-id`: UTC zaman damgası `YYYYMMDDTHHMMSSZ` (örn. `20260829T141500Z`).
- Yazan taraf: marka deposundaki `quality-scan` workflow'u (otomatik `GITHUB_TOKEN`,
  `permissions: contents: write`; secret yok). Motor `--out-dir results/quality` ile
  dosyaları üretir, workflow commit+push eder.
- `history/` asla silinmez/yeniden yazılmaz: geri bildirim döngüsü (6-8 hafta kuralı)
  eski koşulara bakmayı gerektirir.

## quality-scan-result (latest.json ve history/*.json)

```jsonc
{
  "contract": "quality-scan-result",
  "contract_version": "1.0",
  "run": {
    "id": "20260829T141500Z",
    "timestamp_utc": "2026-08-29T14:15:00Z",
    "site": "https://www.example.com",
    "engine_rev": "<content-engine commit SHA>",
    "brandpack_rev": "<marka deposu commit SHA>",
    "workflow_run": "4",                  // Actions koşu numarası; olmayabilir (null)
    "rubric_versions": {"product_page": "1.0", "blog_post": "1.1", "sector_page": "1.1"},
    "rubric_note": "şablon cetvel, uyarlanmamış (v1)",
    "max_pages": 30,
    "pages_ok": 30                        // HTTP 200 dönen ve işlenen sayfa sayısı
  },
  "totals": {
    "scored_pages": 20,                   // cetvelle puanlanan
    "unscored_pages": 10,                 // archive/other: yalnız tuzak+çelişki tarandı
    "avg_auto_pct": 81.5,                 // puanlananların ortalama oto-%'si
    "by_type": {"blog_post": {"pages": 19, "avg_auto_pct": 80.6}},
    "trap_terms": 0,
    "fact_conflicts": 1
  },
  "pages": [
    {
      "url": "https://www.example.com/urun",
      "type": "product_page",             // product_page | sector_page | blog_post | archive | other
      "scored": true,                     // false ise puan alanları null olur
      "rubric_version": "1.0",
      "auto_earned": 25.5, "auto_possible": 26.0, "auto_pct": 98.1,
      "unassessed_weight": 54.0,          // model yargılı kriterlerin toplam ağırlığı
      "criteria": [                       // yalnız scored=true sayfalarda dolu
        {"key": "moq", "weight": 8.0, "auto": true, "ratio": 1.0, "points": 8.0,
         "note": "MOQ ifadesi var: ..."},
        {"key": "named_reference", "weight": 8.0, "auto": false, "ratio": null,
         "points": null, "note": "değerlendirilmedi (model yargısı — sonraki adım)"}
      ]
    }
  ],
  "findings": [                           // TÜM bulgular (cetvel dışı sayfalar dahil), düz liste
    {"kind": "trap_term", "url": "...", "trap": "...", "correct": "...", "count": 2},
    {"kind": "fact_conflict", "url": "...", "field": "moq",
     "page_value": "40.000", "approved_value": 1000, "note": "... insan kararı (§6)"}
  ],
  "changes": { /* aşağıda */ }
}
```

Dürüstlük kuralları (docs/method.md ile uyumlu):
- `auto_pct` yalnız OTOMATİK kriterlerin yüzdesidir; model yargılı ağırlık
  `unassessed_weight`te ayrı durur. Pano bu ikisini asla tek puanmış gibi göstermez.
- Vekil ölçümler kriterin `note` alanında açıkça yazılıdır; pano notu gösterebilmelidir.

## changes bloğu (koşular arası fark)

Motor, yazmadan önce `latest.json`'daki önceki koşuyu okur ve farkı üretir
(`engine/scoring/compare.py`). İlk kalıcı koşuda:

```jsonc
{"first_run": true, "prev_run_id": null, "note": "önceki kayıtlı koşu yok — fark üretilmedi"}
```

Sonraki koşularda:

```jsonc
{
  "first_run": false,
  "prev_run_id": "20260829T141500Z",
  "prev_timestamp_utc": "2026-08-29T14:15:00Z",
  "method_changed": {"engine": false, "rubrics": false, "brandpack": false},
  "new_pages": ["..."], "removed_pages": ["..."],
  "type_changes":  [{"url": "...", "prev": "other", "new": "blog_post"}],
  "score_changes": [{"url": "...", "prev_pct": 37.0, "new_pct": 80.0, "delta_pct": 43.0}],
  "new_findings": [ /* finding nesneleri */ ],
  "resolved_findings": [ /* önceki koşuda olup artık olmayanlar */ ],
  "summary": {"pages_changed": 1, "new_pages": 0, "removed_pages": 0,
              "new_findings": 0, "resolved_findings": 1}
}
```

- `method_changed` alanlarından biri true ise puan farkları siteden değil yöntem
  değişikliğinden gelebilir — pano bu koşuları ⚠️ ile işaretler, yorum insana kalır.
- Bulgu kimliği: trap_term için (url + tuzak terim); fact_conflict için
  (url + alan + sayfadaki değer). Sayfadaki değer değişirse eski bulgu "kapandı",
  yenisi "açıldı" görünür — bu bilinçlidir (40.000→3.000 hâlâ çelişkidir ama farklı).
- `score_changes` yalnız |Δ| ≥ 0.1 satırları içerir, |Δ| büyükten küçüğe sıralı.

## quality-scan-index (index.json)

```jsonc
{
  "contract": "quality-scan-index",
  "contract_version": "1.0",
  "runs": [                               // en yeni en üstte
    {"id": "20260829T150000Z", "timestamp_utc": "2026-08-29T15:00:00Z",
     "file": "history/20260829T150000Z.json",
     "engine_rev": "...", "brandpack_rev": "...",
     "scored_pages": 20, "avg_auto_pct": 81.5,
     "trap_terms": 0, "fact_conflicts": 1,
     "changed_pages": 0}                  // ilk koşuda null
  ]
}
```

Pano kullanım deseni: trend çizgisi ve koşu listesi için önce küçük `index.json`,
detay için `latest.json`, geçmiş bir koşunun detayı için `history/<id>.json`.

## Panonun private depodaki veriye erişimi — AÇIK KARAR

Sonuç dosyaları marka deposunda (private) yaşar. Pano hangi yoldan okur — bu
SÖZLEŞMENİN değil, pano adımının kararıdır. Seçenekler: (a) marka deposunun kendi
Pages'i (private depoda Pages plana bağlıdır), (b) ayrıştırılmış/anonim özet JSON'un
public bir hedefe kopyalanması, (c) panonun yerel/oturum içi açılması. Karar Ali'yle
pano adımında verilecek; sözleşme her üç yolda da aynıdır.
