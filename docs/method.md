# Yöntem kuralları (jenerik) — v1.0

Bu belge motorun **markadan bağımsız** yöntem kurallarını tanımlar. Marka verisi içermez;
markaya özel her değer `brandpack/` içinden okunur. Kurallar sürümlenir: kural değişirse
sürüm numarası artar ve puanlar yeniden üretilir (eski/yeni puanlar karışmaz).

## 1. Kalite cetveli ve şablon kütüphanesi

- Her sayfa tipi (ürün, sektör/hizmet, blog, mevzuat…) için ayrı cetvel şablonu vardır:
  `engine/scoring/rubrics/`. Sihirbaz, markaya göre şablonu uyarlayıp bilgi paketine yazar.
- Cetvel 100 puandır ve bilinçli olarak SEO'ya değil **kanıta** ağırlık verir (teknik veri,
  ticari şeffaflık, güven). Arama araçlarının ölçemediği şey budur.
- **Cetvel sürümlenir.** Kriter değişince tüm sayfalar yeniden puanlanır.
- Eşikler (varsayılan): 70+ iyi/izlenir · 50–69 zenginleştirilecek · <50 elden geçirilecek.
- Kalite kapısı: motorun ürettiği taslak, kendi cetvelinden eşik puanı alamıyorsa yayına önerilmez.

## 2. Öncelik formülü

```
Öncelik = (100 − kalite_puanı) × gösterim
```

Puan tek başına kullanılmaz; formül listeyi trafiğin (paranın) olduğu yere çevirir.
Aylık aksiyon kuyruğu **kapasite tavanlıdır** (varsayılan 4 satır; sihirbaz anketiyle belirlenir).
Gerisi bekleme listesinde kalır ve ertesi ay yeniden sıralanır.
Çıktı rapor değil **aksiyon kuyruğudur**: sayfa · puan · eksik kriter · metrik · iş tipi · tahmini emek.

## 3. Fırsat sınıflandırma — dört kutu

Her fırsat şu dördünden birine atanır; taslak yalnız (d) için yazılır:

- (a) **Başlık/meta düzelt** — sıralama iyi, tıklama yok. En ucuz kazanç.
- (b) **Mevcut sayfayı zenginleştir** — düşük puan, trafik var.
- (c) **Birleştir/kaldır** — zayıf, tıklama getirmeyen, konu dışı sayfa.
- (d) **Yeni sayfa** — karşılığında sayfa olmayan gerçek talep.

Ek kontroller: **kanibalizm** (aynı sorguya birden çok sayfa yarışıyorsa işaretle) ·
**boş kalan kriter = stratejik iş** (bir kriter site genelinde hep sıfırsa bu sayfa sorunu değil
şirket sorunudur; tek stratejik başlık olarak raporlanır).

## 4. İçerik üretimi — üç kapı

1. Motor önerir, kullanıcı seçer (en fazla 3–5 seçenek; hedef sorgu, dil, beslediği sayfa, emek).
2. Konuyu kullanıcı verir.
3. Küresel tarama: sitede hiç yer verilmemiş başlık/konu/yöntem.

Üç kapı da aynı denetimden geçer: onaylı gerçekler + terim sözlüğü + cetvel eşiği.
Motor **yayınlamaz**, taslak üretir; onay insandadır.

## 5. Bilgi paketi disiplini

- **Onaylı gerçekler:** model bu dosyanın dışında hiçbir sayı, süre veya iddia üretemez.
- **Terim sözlüğü:** dil başına doğru ticari terimler + tuzak terimler; yasaklı terim içeren taslak yayına çıkamaz.
- **Ret hafızası:** reddedilen konu bir daha önerilmez; tüm kanallar ortak kullanır.
- **Aksiyon kütüğü:** her işin tarihi, sayfası, tipi, öncesi/sonrası metriği.

## 6. Çelişkiyi sorma kuralı

Kaynaklar (site, broşür, anket cevabı, keşif bulgusu) birbiriyle çelişirse motor **varsaymaz,
seçmez, ortalamaz** — çelişkiyi kullanıcıya sorar ve cevabı onaylı gerçeklere işler.
Sihirbazın ikinci turu (dinamik teyit soruları) bu kuralın uygulamasıdır.

## 7. Geri bildirim döngüsü — 6-8 hafta kuralı

Her aksiyon tarih damgasıyla kütüğe yazılır; motor **6-8 hafta sonra** aynı sayfayı yeniden ölçer
(tıklama, sıra, puan). Search Console verisi 2-3 gün gecikmeli gelir; bir değişikliğin sonucu
**en erken 6 hafta sonra** yorumlanır — daha erken bakıp "işe yaramadı" denmez.

## 8. Tarama görgü kuralları

- Eşzamanlılık düşük, istekler arasında bekleme, acil durdurma anahtarı zorunlu.
- Hedef sitenin önbellek/altyapı ayarlarına dokunulmaz.
- "Yapılmamış" demeden önce canlı sayfa taranır; hafızadaki kayıt kanıt sayılmaz.
- Çıkarım yapmadan önce veriye bakılır; site sahibinin sektör bilgisi itirazı ciddiye alınır.

## 9. Sıfır-başlangıç ilkesi

Şablon depo hiçbir markaya ait veri içermez. Her kurulum, sihirbaz + kullanıcı onayıyla
sıfırdan veri toplar. Yöntem kuralları (bu belge) jeneriktir ve tüm kurulumlarda geçerlidir.
