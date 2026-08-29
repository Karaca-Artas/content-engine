# Cetvel uyarlama (sihirbaz, Adım 11)

Şablon cetvelleri onaylı bilgi paketiyle (facts + terms) markaya uyarlar ve
`brandpack/live/rubrics/` altına yazar. Kriter listesi, ağırlıklar ve eşik
şablondaki gibi kalır; uyarlama, markaya özgü bağlamın (`brand_context`)
kriterlere enjeksiyonudur. Ayrıntı ve ilkeler: `adapt.py` modül başlığı.

- Varsayılan **dry-run**: cetveller yalnız çıktıya yazılır; `--apply` ile pakete yazılır.
- Sürümleme: şablon `1.1` → uyarlanmış `1.1+b1` (içerik değişince `b2`, değişmeyince dosyaya dokunulmaz).
- Motor, paketteki `rubrics/` dizinini otomatik bulur ve uyarlanmış cetveli şablona tercih eder
  (`engine/scoring/quality_scan.py`); cetvel sürümü değişince `method_changed.rubrics` ⚠️ üretilir.
- Pakette olmayan veri için bağlam üretilmez (§9); alıcı profili gibi pakete işlenmemiş onaylar
  `--audience` ile açıkça verilir (§6 — varsayılmaz).
