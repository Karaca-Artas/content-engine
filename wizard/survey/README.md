# Anket formu

`index.html` — Marka Kurulum Anketi (v1.2, 12 soru). Onaylı tasarımın kaynağı:
https://claude.ai/code/artifact/996e2c2c-2d78-4780-802a-62fe90fb636e

Tasarım ilkeleri: ~10 soru (7-13 bandı) · uygun maddelerde üç modlu format
(kendim yazarım / kaynaktan-keşiften alınsın / sentez) · kapasite sorusu aylık öneri listesinin
uzunluğunu ve onay kanalını belirler.

Teknik notlar: tek dosya, bağımlılık yok (yalnız Google Fonts) · cevaplar tarayıcıda
`localStorage`'a taslak olarak kaydedilir · "Cevapları derle" tüm cevapları tek düz metin
halinde üretir; kullanıcı bu metni motoru kuran tarafa gönderir.
