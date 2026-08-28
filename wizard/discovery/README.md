# Kaynak keşfi — Faz 0, Tur 1

Girdi: marka web sitesi (+ ileride: tanıtım broşürü PDF).
Çıktı: taslak bilgi paketi + Tur 2 teyit soru listesi.

## Çalıştırma

```bash
python -m wizard.discovery.discover https://www.example.com \
    --max-pages 30 --delay 3 --out brandpack/draft
```

veya GitHub Actions'ta elle: **Actions → discovery → Run workflow** (site_url gir).
Actions koşusu depoya veri yazmaz; taslak, 14 gün saklanan workflow artifact'i olarak iner
ve özet, koşunun Summary sayfasında görünür.

## Çıktı dosyaları

| Dosya | İçerik |
|---|---|
| `facts.draft.json` | `facts.schema.json` uyumlu taslak: marka adı, ürün/sektör adayları, sertifika adayları, MOQ/termin adayları — hepsi kanıt URL'leriyle. `_draft` bloğu taslak meta bilgisini taşır. |
| `terms.draft.json` | `terms.schema.json` uyumlu taslak terim sözlüğü (başlık sıklığı temelli adaylar; SERP doğrulaması Tur 2'de). |
| `open_questions.json` | Tur 2 dinamik teyit soruları: boşluklar + ÇELİŞKİLER (kanıt URL'leriyle). |
| `pages.json` | (`--save-pages` ile) ham tarama dökümü. |

## İlkeler

- **§6 Çelişki kuralı:** aynı bilgi için farklı değerler bulunursa (ör. iki sayfada iki
  farklı MOQ) motor SEÇMEZ, ORTALAMAZ — `open_questions.json`a çelişki sorusu yazar.
- **§8 Nazik tarama:** robots.txt'ye uyulur, istekler arası bekleme, `.crawl-stop`
  acil durdurma anahtarı, sayfa tavanı, yalnız hedef alan adı.
- **§9 Sıfır-başlangıç:** taslak ONAY DEĞİLDİR. `named_references` ve `not_offered`
  daima boş üretilir (yalnız kullanıcı onayıyla dolar); taslak, Tur 2 tamamlanmadan
  `brandpack/live/`e kopyalanamaz. Şablon depoya hiçbir marka verisi işlenmez.
- Harici bağımlılık yok — saf Python stdlib (3.11+).
