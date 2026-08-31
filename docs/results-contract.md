# Tarama sonuçları veri sözleşmesi — v1.3

Sürüm 1.3 · 31 Ağustos 2026 (Adım 16: YENİ, bağımsız `action-queue-result`
sözleşmesi eklendi — belgenin sonunda. Kalite sözleşmesi v1.1'e EKLEMELİ
alanlar: `findings[]` yeni `broken_page` türü + `totals.broken_pages` —
erişilemeyen tohum sayfalar artık sonuç dosyasına yazılır; eski dosyalarda bu
alanların yokluğu "bulgu yok" okunur).
Sürüm 1.2 · 30 Ağustos 2026 (Adım 14: YENİ, bağımsız `performance-scan-result`
sözleşmesi eklendi — belgenin sonunda. Kalite sözleşmesi 1.1'de değişmeden durur;
her sözleşme kendi `contract` + `contract_version` alanıyla sürümlenir).
Sürüm 1.1 · 29 Ağustos 2026 (Adım 10: model yargısı alanları eklendi — geriye
uyumlu ekleme, küçük sürüm artışı; v1.0 dosyaları dönüşümsüz okunmaya devam eder,
yeni alanlar yoksa pano "değerlendirilmedi" gösterir).
İlk sürüm 1.0 · 29 Ağustos 2026 (Adım 8). Bu belge, kalite taraması sonuçlarının marka
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
  `permissions: contents: write`). Motor `--out-dir results/quality` ile
  dosyaları üretir, workflow commit+push eder. Depo yazımı secret'sızdır;
  model yargısı için `ANTHROPIC_API_KEY` repo secret'ı kullanılır (Adım 10 kararı —
  sıfır-secret deseninin bilinçli tek istisnası; anahtar yoksa yargı atlanır, koşu düşmez).
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
    "judge": {                            // v1.1: model yargısı yöntemi (Adım 10)
      "enabled": true,                    // false ise: {"enabled": false, "reason": "..."}
      "model": "claude-haiku-4-5",        // model kimliği — yöntemin parçası
      "prompt_version": "1.0",            // judge_prompts.yml sürümü — yöntemin parçası
      "requests": 20, "failures": 0,
      "vision_enabled": true,             // v1.1 eklemeli alanlar (Adım 12): görsel
      "vision_requests": 3,               // kriterlerin (real_photos, tech_drawing) görüş
      "vision_failures": 0                // modeli yargısı; eski kayıtlarda bu alanlar yok
    },
    "max_pages": 30,
    "page_selection": {                   // v1.1 eklemeli alan (Adım 15): sayfa seçim modu.
      "mode": "performance-priority",     // "default" | "performance-priority" | "pages-json".
      "perf_run_id": "20260830T101112Z",  // kaynak performans koşusu (yalnız priority modda)
      "perf_window": {"start_date": "…", "end_date": "…"},
      "seeded": 30                        // gösterime göre tohumlanan URL sayısı (kök dahil).
    },                                    // Seçim sıralaması YALNIZ gösterimle yapılır; kalite/
                                          // model puanı seçime karışmaz. Eski kayıtlarda alan yok.
    "pages_ok": 30                        // HTTP 200 dönen ve işlenen sayfa sayısı
  },
  "totals": {
    "scored_pages": 20,                   // cetvelle puanlanan
    "unscored_pages": 10,                 // archive/other: yalnız tuzak+çelişki tarandı
    "avg_auto_pct": 81.5,                 // puanlananların ortalama oto-%'si
    "judged_pages": 20,                   // v1.1: model yargısı alan sayfa sayısı
    "avg_judged_pct": 63.0,               // v1.1: ortalama model-% (oto'dan AYRI; yoksa null)
    "by_type": {"blog_post": {"pages": 19, "avg_auto_pct": 80.6}},
    "trap_terms": 0,
    "fact_conflicts": 1,
    "broken_pages": 9                     // v1.1 eklemeli alan (Adım 16); eski kayıtlarda yok
  },
  "pages": [
    {
      "url": "https://www.example.com/urun",
      "type": "product_page",             // product_page | sector_page | blog_post | archive | other
      "scored": true,                     // false ise puan alanları null olur
      "rubric_version": "1.0",
      "auto_earned": 25.5, "auto_possible": 26.0, "auto_pct": 98.1,
      "judged_earned": 19.0, "judged_possible": 30.0, "judged_pct": 63.3,
                                          // v1.1: model puanı — oto alanlardan AYRI; yargı yoksa null
      "unassessed_weight": 24.0,          // yargılanmamış kriterlerin toplam ağırlığı
                                          // (v1.1: model puanladıkları artık burada sayılmaz)
      "criteria": [                       // yalnız scored=true sayfalarda dolu
        {"key": "moq", "weight": 8.0, "auto": true, "ratio": 1.0, "points": 8.0,
         "note": "MOQ ifadesi var: ..."},
        {"key": "sampling", "weight": 5.0, "auto": false, "ratio": 0.5, "points": 2.5,
         "judged_by": "model",            // v1.1: model puanı; ratio yalnız 0 / 0.5 / 1
         "note": "model: <sayfadan kısa kanıt gerekçesi>"},
        {"key": "real_photos", "weight": 6.0, "auto": false, "ratio": 1.0,
         "points": 6.0, "judged_by": "vision", // v1.1 eklemeli (Adım 12): görüş modeli
         "note": "model(görsel): <hangi görsellere dayandığı>"},
        {"key": "faq_coverage", "weight": 10.0, "auto": false, "ratio": null,
         "points": null, "note": "değerlendirilmedi (bilgi paketinde müşteri sık-soru verisi henüz yok)"}
      ]
    }
  ],
  "findings": [                           // TÜM bulgular (cetvel dışı sayfalar dahil), düz liste
    {"kind": "trap_term", "url": "...", "trap": "...", "correct": "...", "count": 2},
    {"kind": "fact_conflict", "url": "...", "field": "moq",
     "page_value": "40.000", "approved_value": 1000, "note": "... insan kararı (§6)"},
    {"kind": "broken_page", "url": "...", "http_status": 404, "error": null,
     "note": "sayfa canlıda erişilemedi — 301/geri getirme kararı insana aittir"}
                                          // v1.1 eklemeli tür (Adım 16); kimlik = url + http_status
  ],
  "changes": { /* aşağıda */ }
}
```

Dürüstlük kuralları (docs/method.md ile uyumlu):
- `auto_pct` yalnız OTOMATİK kriterlerin yüzdesidir; `judged_pct` yalnız MODEL
  yargısının yüzdesidir; yargılanamayan ağırlık `unassessed_weight`te durur.
  Pano bu üçünü asla tek puanmış gibi göstermez, toplamaz.
- Model yargısının yöntemi = model kimliği + sabit rubrik sürümü (`run.judge`);
  ikisinden biri değişirse (yargının açılıp kapanması dahil) `changes.method_changed.judge`
  true olur ve model puan farkları yorumsuz kıyaslanamaz.
- Model erişilemezse koşu düşmez: kriterler "değerlendirilmedi" kalır,
  neden `note`ta ve `run.judge`ta yazılıdır.
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
  "method_changed": {"engine": false, "rubrics": false, "brandpack": false,
                     "judge": false},  // v1.1: model/rubrik sürümü değişti veya yargı açılıp kapandı
  "new_pages": ["..."], "removed_pages": ["..."],
  "type_changes":  [{"url": "...", "prev": "other", "new": "blog_post"}],
  "score_changes": [{"url": "...", "prev_pct": 37.0, "new_pct": 80.0, "delta_pct": 43.0}],
  "judged_score_changes": [ /* v1.1: model-% farkları — score_changes ile aynı yapı, AYRI liste */ ],
  "summary": {"pages_changed": 1, "judged_pages_changed": 0,  // judged_* v1.1
              "new_pages": 0, "removed_pages": 0,
              "new_findings": 0, "resolved_findings": 1},
  "new_findings": [ /* finding nesneleri */ ],
  "resolved_findings": [ /* önceki koşuda olup artık olmayanlar */ ]
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
     "avg_judged_pct": 63.0,              // v1.1: ortalama model-% (yargı yoksa null)
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

## performance-scan-result — v1.0 (Adım 14, Faz 2 / Kanal B veri tarafı)

Search Console + GA4 verisinin koşu başına dökümü. Kalite sözleşmesinden
BAĞIMSIZ sürümlenir. Dosya düzeni aynı desendir:

```
results/
  performance/
    latest.json          # son koşu — pano/sentez varsayılan olarak bunu okur
    index.json           # koşu listesi (en yeni en üstte)
    history/<run-id>.json
```

Yazan taraf: marka deposundaki `perf-scan` workflow'u. Google kimliği kısa
ömürlü OAuth jetonudur (anahtarsız WIF — GitHub OIDC → Google STS; depoda
kalıcı Google secret'ı YOKTUR, sıfır-secret deseni korunur). Salt okuma
kapsamları: webmasters.readonly + analytics.readonly.

```jsonc
{
  "contract": "performance-scan-result",
  "contract_version": "1.0",
  "run": {
    "id": "20260830T160000Z", "timestamp_utc": "...", "site": "...",
    "engine_rev": "...", "brandpack_rev": "...", "workflow_run": "1",
    "window": {"start_date": "2026-07-31", "end_date": "2026-08-27",
               "days": 28, "end_lag_days": 3},   // GSC 2-3 gün geriden gelir
    "sources": {                                  // kaynak düşerse koşu düşmez
      "gsc": {"property": "sc-domain:example.com", "ok": true, "rows": 120, "error": null},
      "ga4": {"property": "336534572", "ok": true, "rows": 95, "error": null}
    },
    "quality_run_id": "20260830T104649Z"          // puanların alındığı kalite koşusu; yoksa null
  },
  "totals": {"pages": 130, "clicks": 210, "impressions": 9800, "sessions": 1400,
             "matched_quality_pages": 20, "cannibal_queries": 3},
  "pages": [                                      // gösterime göre azalan
    {"path": "/products", "url": "https://www.example.com/products",
     "clicks": 12, "impressions": 800, "ctr": 0.015, "position": 8.7,
     "sessions": 40, "engaged_sessions": 22, "users": 35, "engagement_rate": 0.55,
     "in_gsc": true, "in_ga4": true,
     "top_queries": [{"query": "...", "clicks": 5, "impressions": 300, "position": 8.2}],
     "quality": {"type": "product_page", "scored": true, "auto_pct": 62.0,
                 "judged_pct": 70.0, "run_id": "..."},  // kalite eşleşmesi; yoksa null
     "priority_auto": 30400.0}                    // (100 − auto_pct) × impressions — ÖNİZLEME
  ],
  "findings": [
    {"kind": "cannibal_query", "query": "...", "total_impressions": 500,
     "pages": [{"path": "...", "clicks": 1, "impressions": 220, "position": 9.1}],
     "note": "vekil tespit, nihai yorum insana aittir"}
  ],
  "changes": {                                    // v1.0'da yalnız toplam farkları
    "first_run": false, "prev_run_id": "...", "prev_timestamp_utc": "...",
    "clicks_delta": 12, "impressions_delta": -40, "sessions_delta": 3,
    "note": "pencereler örtüşebilir — 6-8 hafta kuralı; sayfa bazlı fark sonraki adım"
  }
}
```

Dürüstlük kuralları:
- `priority_auto` bir ÖNİZLEMEDİR: yalnız OTO yüzdesiyle hesaplanır
  ((100 − auto_pct) × gösterim, yöntem docs/method.md). Oto ve model puanı
  burada da birleştirilmez; tam Kanal C sentezi (aksiyon kuyruğu, dört kutu,
  aylık tavan) AYRI adımın sözleşmesidir.
- Kanibalizm bulgusu vekil tespittir (sayfa ≥ 10 gösterim VE sorgu toplamının
  ≥ %15'i olan ≥ 2 sayfa); menü/etiket etkisi ayrıştırılamaz, yorum insana kalır.
- Kaynaklardan biri erişilemezse `sources.<k>.ok=false` + hata özeti yazılır,
  koşu düşmez; İKİSİ de düşerse sonuç yazılmaz ve koşu başarısız sayılır.
- GA4 `pagePath` sorgu dizesinden arındırılır; GSC tam URL'si yol'a indirgenir
  (kök dışında sondaki `/` atılır) — birleştirme anahtarı bu normalleştirilmiş yoldur.

### performance-scan-index (index.json)

```jsonc
{"contract": "performance-scan-index", "contract_version": "1.0",
 "runs": [{"id": "...", "timestamp_utc": "...", "file": "history/....json",
           "engine_rev": "...", "brandpack_rev": "...",
           "window_start": "2026-07-31", "window_end": "2026-08-27",
           "pages": 130, "clicks": 210, "impressions": 9800, "sessions": 1400,
           "matched_quality_pages": 20, "cannibal_queries": 3}]}
```

## action-queue-result — v1.0 (Adım 16, Faz 3 / Kanal C sentezi)

Aylık aksiyon kuyruğu: son performans + son kalite koşusunun sentezi
(docs/method.md §2-3 — öncelik formülü, aylık tavan, dört kutu).

```
results/
  actions/
    latest.json
    index.json           # contract: action-queue-index
    history/<run-id>.json
```

Yazan taraf: marka deposundaki `synthesis` workflow'u (otomatik `GITHUB_TOKEN`,
secret'sız; model çağrısı yoktur, koşu maliyeti 0).

```jsonc
{
  "contract": "action-queue-result",
  "contract_version": "1.0",
  "run": {
    "id": "20260831T170000Z", "timestamp_utc": "...", "site": "...",
    "engine_rev": "...", "brandpack_rev": "...", "workflow_run": "1",
    "inputs": {                       // sentezin dayandığı iki koşu — dürüstlük
      "performance_run_id": "...", "performance_window": {...},
      "quality_run_id": "...", "quality_rubric_note": "..."
    },
    "thresholds": {                   // sabit kutu eşikleri, dosyada açık durur
      "priority": "(100 − auto_pct) × impressions — yalnız oto puan",
      "cap": 4,
      "a_title_meta": {"min_auto_pct": 70, "max_position": 10,
                        "min_impressions": 100, "max_ctr": 0.01},
      "b_enrich": {"max_auto_pct": 70, "min_impressions": 1}
    }
  },
  "totals": {"queue": 4, "waiting": 12, "urgent_broken": 9,
             "consolidation_candidates": 3, "watch_pages": 6,
             "unscored_with_impressions": 40, "skipped_rejected": 0,
             "strategic": 1,
             "boxes": {"title_meta": 1, "enrich": 15,
                        "merge_or_remove": 12, "new_page": null}},
  "queue": [                          // aylık kuyruk — en fazla cap satır
    {"rank": 1, "path": "/...", "url": "...", "type": "product_page",
     "box": "enrich",                 // title_meta | enrich
     "reason": "atamanın gerekçe metni",
     "auto_pct": 33.7, "judged_pct": 41.0,   // model puanı BİLGİDİR, hesaba karışmaz
     "impressions": 523, "clicks": 2, "ctr": 0.004, "position": 12.3,
     "top_query": "...", "priority_auto": 34674.9,
     "quality_run_id": "...",
     "missing_criteria": [{"key": "size_table", "points": 0, "weight": 12, "gap": 12}],
     "effort": "yüksek"}              // düşük | orta | yüksek
  ],
  "waiting": [ /* kuyruk satırıyla aynı yapı; tavan dışı, en fazla 20 */ ],
  "urgent": [                         // 404'ler — (c) ADAYI, aylık tavanı YEMEZ
    {"path": "/...", "box": "merge_or_remove", "http_status": 404,
     "impressions": 1457, "clicks": 3, "position": 8.6, "reason": "..."}
  ],
  "consolidation": [                  // kanibal etiket/arşiv sayfaları — (c) ADAYI
    {"path": "/tag/...", "box": "merge_or_remove", "queries": ["..."],
     "competing_with": ["/..."], "impressions": 220, "reason": "..."}
  ],
  "unscored_top": [{"path": "/...", "impressions": 300}],  // önceliklenemedi (bilgi)
  "skipped_rejected": [{"path": "/...", "reason": "...", "rejected_on": "..."}],
  "strategic": [                      // site genelinde hep sıfır kriter → TEK satır
    {"criterion": "tech_drawing", "pages_scored": 12, "weight": 8, "note": "..."}
  ],
  "notes": ["dürüstlük notları — üretim kuralları"],
  "changes": {"first_run": false, "prev_run_id": "...", "prev_timestamp_utc": "...",
              "queue_added": ["/..."], "queue_removed": [],
              "urgent_added": [], "urgent_resolved": ["/..."],
              "note": "kuyruk her ay yeniden sıralanır; çıkan satır 'çözüldü' demek değildir"}
}
```

Dürüstlük kuralları:
- Öncelik ve kutu ataması YALNIZ oto puan + GSC/GA4 metrikleriyle yapılır;
  model puanı (`judged_pct`) satırda bilgi olarak taşınır, hesaba karışmaz.
- Öncelik kalite `latest.json`'ından YENİDEN hesaplanır (performans
  dosyasındaki `priority_auto` önizlemesi eski bir kalite koşusuna dayanabilir);
  iki girdinin koşu kimliği `run.inputs`'ta durur.
- (d) `new_page` kutusu otomatik atanmaz (`boxes.new_page: null`): gerçek
  talep tespiti Kapı 1 / Kanal A işidir.
- `urgent` ve `consolidation` (c) kutusunun ADAYLARIDIR; 301/birleştirme/
  kaldırma kararı insana aittir ve bu listeler aylık `cap` tavanını yemez.
- Ret hafızası (`brandpack/live/rejections.json`) uygulanır; atlanan sayfalar
  `skipped_rejected`'ta görünür kalır.
- Girdi dosyalarından biri yoksa/sözleşmeye uymuyorsa koşu BAŞARISIZ olur —
  boş kuyruk yazılmaz (yanıltıcı olur).

### action-queue-index (index.json)

```jsonc
{"contract": "action-queue-index", "contract_version": "1.0",
 "runs": [{"id": "...", "timestamp_utc": "...", "file": "history/....json",
           "engine_rev": "...", "brandpack_rev": "...",
           "performance_run_id": "...", "quality_run_id": "...",
           "queue": 4, "waiting": 12, "urgent_broken": 9,
           "consolidation_candidates": 3, "strategic": 1}]}
```
