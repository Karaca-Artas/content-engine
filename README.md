# content-engine

Bağımsız, dağıtılabilir bir **içerik kalite ve fırsat motoru** şablonu.
Bir web sitesinin mevcut sayfalarını sabit bir kalite cetveliyle puanlar, arama/analitik
verisiyle çaprazlar ve aylık, kısa bir aksiyon kuyruğu üretir. Onay verilirse içerik
taslağı hazırlar.

> **Şablon depo.** Bu depoda hiçbir markaya ait veri yoktur ve olmayacaktır.
> Her marka, "Use this template" ile kendi (genellikle private) kopyasını türetir ve
> kurulum sihirbazıyla kendi bilgi paketini sıfırdan oluşturur.

## Üç katman

| Katman | Klasör | İçerik |
|---|---|---|
| 1. Jenerik motor kodu | `engine/` | Kanal A/B/C, puanlayıcı, kaynak bağlayıcılar. Marka bilgisi içermez. |
| 2. Markaya özel bilgi paketi | `brandpack/` | Şablonda yalnız **şema + anonim örnek**. Gerçek paket, türetilen kopyada sihirbazla üretilir. |
| 3. Kurulum sihirbazı | `wizard/` | Faz 0: anket + kaynak keşfi (site, broşür) → taslak bilgi paketi → dinamik teyit soruları. |

## Üç kanal

- **Kanal A — dış görüş:** pazar/rakip taraması, içerik boşluğu, mevzuat–trend radarı.
- **Kanal B — iç görüş:** Search Console + GA4 performansı × kalite cetveli puanı.
- **Kanal C — sentez:** öncelik formülü → aylık aksiyon kuyruğu (kapasite tavanlı).

## Çalışma modeli

- Rutin işler **GitHub Actions**'ta zamanlanmış olarak döner; pano **GitHub Pages**'te yayımlanır.
- Motor **yayınlamaz**; taslak üretir, onay her zaman insandadır.
- Yöntem kuralları `docs/method.md`'dedir ve koddan bağımsız sürümlenir.

## Kurulum (özet)

1. Bu şablondan yeni depo türet (marka kopyası → private önerilir).
2. `wizard/` içindeki kurulum sihirbazını çalıştır: anket + kaynak keşfi, bilgi paketi taslağı, teyit turu.
3. `config.example.yml` → `config.yml` kopyala ve doldur.
4. Gerekli gizli anahtarları (Search Console / GA4 servis hesabı vb.) depo **Secrets**'ına ekle.
5. Workflow'ları etkinleştir (`.github/workflows/`).

Ayrıntılı yöntem: [`docs/method.md`](docs/method.md) · Yol haritası: [`docs/roadmap.md`](docs/roadmap.md)
