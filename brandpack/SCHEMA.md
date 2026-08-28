# Bilgi paketi (brandpack) şeması

Markaya özel HER ŞEY burada yaşar; motor kodu (`engine/`) marka bilgisi içermez.
Şablon depoda yalnız şema ve anonim örnek bulunur. Gerçek paket, türetilen marka
kopyasında `brandpack/live/` altında sihirbaz tarafından üretilir.

| Dosya | İçerik | Kural |
|---|---|---|
| `facts.json` | Onaylı gerçekler: ürün aralıkları, MOQ, terminler, sertifikalar, isim verilebilir referanslar, YAPILMAYAN işler | Model bu dosyanın dışında sayı/süre/iddia üretemez |
| `terms.json` | Dil başına doğru ticari terimler + tuzak terimler | Yasaklı terim içeren taslak yayına çıkamaz |
| `rejections.json` | Ret hafızası: reddedilen konular + gerekçeleri | Reddedilen konu bir daha önerilmez; tüm kanallar ortak kullanır |
| `actions.json` | Aksiyon kütüğü: tarih, sayfa, iş tipi, önce/sonra metrikleri | 6-8 hafta geri bildirim döngüsünün temeli |
| `rubrics/*.yml` | Sihirbazın markaya uyarladığı cetveller (şablon kütüphanesinden türetilir) | Cetvel sürümlenir; sürüm değişince tüm sayfalar yeniden puanlanır |
| `customer_questions.json` | (İsteğe bağlı) müşteri yazışmalarından çıkarılan ANONİM soru/terim dosyası | Ad, firma, fiyat içermez; kayıtlar tarih etiketlidir |

Çelişki kuralı: kaynaklar çelişirse sihirbaz varsaymaz, kullanıcıya sorar (docs/method.md §6).
