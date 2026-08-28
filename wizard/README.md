# Kurulum sihirbazı — Faz 0

Yeni bir marka kurulumunu SIFIRDAN veriyle yapar. İki turludur:

**Tur 1 — Anket + kaynak keşfi**
- `survey/` içindeki anket formu doldurulur (~10 soru, 7-13 bandı).
- Bazı sorularda üç mod vardır: (1) kendim yazarım · (2) kaynaktan/keşiften alınsın · (3) sentez.
  (Rakipler, üstünlükler, referanslar vb. maddelerde geçerli.)
- `discovery/` motoru verilen kaynakları (web sitesi, tanıtım broşürü) tarar ve
  taslak bilgi paketi türetir.

**Tur 2 — Dinamik teyit soruları** (`confirm/`)
- Taslak paketteki boşluklar ve ÇELİŞKİLER kullanıcıya sorulur (motor varsaymaz — method.md §6).
- `confirm/` modülü soru gündemini üretir (`prepare`) ve onaylı cevapları
  `brandpack/live/`e işler (`apply`).
- Ticari terimler SERP kanıtıyla doğrulanır; tuzak terimler sözlüğe işlenir.
- Cetvel şablonları markaya uyarlanır.

Çıktı: `brandpack/live/` altında onaylanmış bilgi paketi. Motor ancak bundan sonra çalışır.
