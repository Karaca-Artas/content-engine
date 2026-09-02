# İçerik Motoru Yol Haritası — v2.0 (tam metin)

> Kaynak belge (HTML): https://claude.ai/code/artifact/43ab5f48-5255-4520-a75f-75db4adc3349
> Bu dosya, kaynak belgenin tam metnidir; kaynakla çelişirse kaynak belge esas alınır.

Üç kanallı model: dış görüş rakipten fırsatı bulur, iç görüş kendi sayfanın eksiğini ölçer,
sentez ikisini ayda dört işlik bir kuyruğa çevirir. Sistem sıfır veriyle başlar: bilgi paketini
kurulum sihirbazı kurar, hiçbir hazır veri taşınmaz.

| | |
|---|---|
| Karar tarihi | 28 Ağustos 2026 |
| İlke | Sıfır-başlangıç |
| Ortam | GitHub Actions (pano yerelde) |
| Yayın dilleri | TR + EN |

---

## Model — Üç kanal, tek kuyruk

### Kanal A — Dış görüş: Global fırsat taraması
Rakip içerik davranışı, boşluk analizi, regülasyon radarı. Ne yazılacağını bulur.
Rakip listesi hazır alınmaz — sihirbazın keşfiyle sıfırdan kurulur ve onaydan geçer.
*Durum: uygulamada sıfırdan kurulacak · iki haftada bir.*

### Kanal B — İç görüş: Performans × sayfa kalitesi
Search Console + GA4 verisi, her sayfanın 100 puanlık kalite cetveliyle çaprazlanır.
Google'ın gördüğünü ve göremediğini aynı tabloya koyar.
*Durum: kurulacak · bu projenin ana işi.*

### Kanal C — Sentez: Aylık öneri kuyruğu
İki kanalın çıktısı tek formülle sıralanır, dört kutuya ayrılır (başlık düzelt / zenginleştir /
birleştir / yeni sayfa) ve ayda en fazla dört iş seçilir. Her işin sonucu 6–8 hafta sonra
otomatik yeniden ölçülür.

```
Öncelik = (100 − puan) × gösterim
```

> **Modelin ayırt edici parçası kalite cetvelidir.** GSC, GA4 ve Semrush yalnız Google'ın
> gördüğünü ölçer; ölçü tablosu, MOQ, termin, gerçek fotoğraf ve isimli referansın varlığını
> hiçbiri bilmez. Değer kesişimde çıkar: *"cylinder packaging — sıra 8 · 317 gösterim ·
> 0 tık · sayfada ölçü tablosu yok."*

---

## Verilmiş kararlar

| Karar | İçerik |
|---|---|
| **Sıfır-başlangıç ilkesi** | Motor, ArtasPack için bugüne dek biriktirilmiş hiçbir hazır veriyi kullanmaz; her şeyi anket + keşif + teyit turuyla kendisi sıfırdan toplar. Sıfırlanan şey veridir, yöntem değil: öncelik formülü, çelişkiyi sorma kuralı, 6–8 hafta kuralı gibi dersler jenerik tasarım kuralı olarak sistemde kalır. ArtasPack, sihirbazın 1 numaralı müşterisi olarak sistemin gerçek sınavıdır. |
| **Semrush** | Faz 4'te devreye girer. İlk tur GSC + GA4 ile döner; geri bildirim döngüsü bir kez tamamlanmadan yeni veri kaynağı eklenmez. |
| **Sentez kadansı** | Ayda bir öneri kuyruğu (kapasite: ayda 2–4 iş, kuyruk tavanı 4 satır). Global tarama iki haftada bir sürer, çıktısı aylık senteze girer. |
| **Çalışma ortamı** | Rutin işler GitHub Actions'ta, pano yerelde açılır. Rutin çalışma token harcamaz; token yalnız uygulama güncellenirken kullanılır. |
| **Model işbölümü** | Toplu puanlama ve rutin özet: Gemini. İçerik yazımı, görsel yargısı ve kodun tamamı: Claude. |
| **Yayın dilleri** | TR + EN (birbirinin çevirisi değil). FR/DE sayfaları yalnız puanlanır ve izlenir; taslak üretilmez. |
| **Onay akışı** | Motor yayınlamaz, taslak üretir. Taslaklar Google Drive'a düşer; bildirim ve onay e-posta ile. Onay her zaman Ali'de. |
| **Ticari gerçekler** | Sihirbaz turlarında sıfırdan toplanır ve onaydan geçer. Motor, onaylı gerçekler dosyasının dışında hiçbir sayı, süre veya iddia kullanamaz; kaynaklarda çelişki bulursa sessizce çözmez, sahibine sorar. |
| **Mimari — üç katman** | Motor kodu jeneriktir, hiçbir marka bilgisi içermez · bilgi paketi markaya özeldir (onaylı gerçekler, terim sözlüğü, cetvel, ret hafızası) ve yalnız sihirbaz + onay yoluyla dolar · kurulum sihirbazı bilgi paketini kaynaklardan (web sitesi + broşür), anketten ve kendi keşfinden türetir. |

---

## Eylem planı — Fazlar (her biri onayla başlar)

### Faz 0 — Kurulum sihirbazı: bilgi paketi sıfırdan kurulur
*İki turlu kurulum · ArtasPack = 1 numaralı müşteri*

**Tur 1:** 12 soruluk anket doldurulur; motor siteyi ve broşürü tarar, sektöre göre kalite
cetveli şablonunu önerir, hedef dillerde baş terimleri arayıp tuzak terimleri kanıta dayalı
çıkarır. **Tur 2:** keşfin ürettiği dinamik teyit soruları — bulunan çelişkiler ("iki farklı
MOQ var, hangisi?"), keşfedilen rakipler, çıkarılan iddia ve referans isimleri tek tek onaya
gelir. Çıktı: onaylı gerçekler, terim sözlüğü ve cetvel sıfırdan kurulmuş; ret hafızası ile
değişiklik kaydı boş ama aktif.

> **Bitti sayılır:** bilgi paketi tamamen sihirbaz + onayınla kuruldu, hazır veri taşınmadı.

### Faz 1 — Kanal B ilk çalışma
*GSC + GA4 + site envanteri*

Veri çekilir, sayfalar yavaş taramayla dolaşılır ve sihirbazın kurduğu cetvelle puanlanır;
ilk kesişim analizi çıkar. Paralel tek seferlik iş: son 2 yılın müşteri e-postalarından anonim
soru dosyası — cetvelin "alıcı sorusu karşılığı" kriteri onsuz ölçülemez.

> **Bitti sayılır:** tüm sayfaların puan tablosu + ilk kesişim raporu elimizde.

### Faz 2 — Sentez ve pano
*Öncelik formülü · dört kutu · yerel pano*

Öncelik formülü ve kanibalizm kontrolü çalışır, ilk aylık öneri kuyruğu (en fazla 4 satır)
üretilir. Pano yerelde açılır (GitHub Pages seçilmedi — Adım 9 kararı); aylık rutin Actions'a bağlanır.

> **Bitti sayılır:** pano çalışıyor, ilk kuyruk onayına sunuldu.

### Faz 3 — Geri bildirim döngüsü
*Ölçmeden öğrenilmez*

İnsanın sitede yaptığı her değişiklik değişiklik kaydına yazılır (kaydı insan girer); 6–8
hafta sonra motor o sayfayı kendisi yeniden ölçer (tık, sıra, puan). Motor değişiklik yapmaz. Kanal A çıktıları senteze bağlanır; ret hafızası sayesinde aynı öneri iki yerden
gelmez.

> **Bitti sayılır:** ilk önce/sonra ölçümü rapora düştü.

### Faz 4 — Genişletme
*Semrush · içerik üretimi · rakip hamle takibi*

Semrush eklenir (rakip kelimeleri, kelime boşluğu). İçerik üretimi üç kapıdan açılır — motor
önerir / konuyu sen verirsin / global tarama bulur; cetvelden 70 alamayan taslak onaya
sunulmaz. Rakip sayfalarının fotoğrafı saklanıp hamle farkı izlenir.

> **Bitti sayılır:** ilk taslak Drive'a düştü ve e-posta onayından geçti.

### Faz 5 — Sihirbazın paketlenmesi
*Başka markalara verilebilir hale getirme*

Faz 0'da ArtasPack kurulumunda çalışan sihirbaz, dış kullanıcıya verilebilir ürüne
dönüştürülür: kurulum akışı belgelenir, ArtasPack kurulumunda gereken elle müdahaleler jenerik
kurala çevrilir, anket + keşif + teyit zinciri tek paket olur. Değişmez kural: sihirbaz
çıktısı her zaman taslaktır — marka sahibi onaylamadan motor içerik üretemez.

> **Bitti sayılır:** bir dış kullanıcı, yardım almadan kendi bilgi paketini kurabiliyor.

---

## Değişmeyen çalışma kuralları

**Kalite eşikleri.** `70+` iyi, izlenir · `50–69` zenginleştirilecek · `<50` elden
geçirilecek. Cetvel sürümlenir; kriter değişirse tüm sayfalar yeniden puanlanır.

**Sabır kuralı.** Bir değişikliğin sonucu en erken 6 hafta sonra yorumlanır. Search Console
gecikmeli gelir; erken bakıp "işe yaramadı" denmez.

**Çıktı biçimi.** Uzun rapor değil öneri kuyruğu (uygulanmaz, sunulur): en fazla 5–10 satır, ayda en fazla 4 iş.
Gerisi bekleme listesinde, her ay yeniden sıralanır.

**Kapsam sınırı (2 Eyl 2026).** Motor yalnız tespit eder ve bilgilendirir: siteye, CMS'e,
önbelleğe, DNS'e, yönlendirmelere dokunmaz; bulgu, öneri ve taslak üretir, uygulama insanındır.

**Site güvenliği.** Tarama yavaş ve aralıklı yapılır; site altyapısına hiçbir koşulda dokunulmaz.
"Yapılmamış" demeden önce canlı sayfa kontrol edilir.

**Doğruluk kapısı.** Üretilen hiçbir metin onaylı gerçekler dosyasının dışında sayı, süre
veya iddia içeremez. Yasaklı/tuzak terim kullanan taslak onaya sunulmaz.

**Görsel dürüstlüğü.** Şema gerçek rakamdan üretilebilir; fabrika fotoğrafı asla üretilmez —
arşivden seçilir ya da çekim görevi açılır.

---

*ArtasPack İçerik Motoru · Yol haritası v2.0 — 28.08.2026 · Çerçeve kaynağı: içerik kalite
motoru kararları, 23.08.2026*
