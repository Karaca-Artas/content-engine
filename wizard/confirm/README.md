# Teyit akışı — Faz 0, Tur 2

Girdi: keşif taslağı (Tur 1 çıktısı: `facts.draft.json`, `terms.draft.json`,
`open_questions.json`) + isteğe bağlı anket cevap metni (anket formunun
"derle" çıktısı).
Çıktı: `brandpack/live/` altında onaylı bilgi paketi. Motor ancak bundan sonra çalışır.

## Akış

```
prepare ──► session.json ──► soru-cevap turu (kullanıcıyla) ──► apply ──► brandpack/live/
```

1. **`prepare`** — keşif sorularını, anket ön-cevaplarıyla zenginleştirilmiş tek
   bir gündem dosyasında (`session.json`) toplar. Marka adı ve sektör adayları
   için ek teyit soruları üretir. Anket ile site ÇELİŞİRSE (ör. iki farklı MOQ)
   motor seçmez, çelişki sorusu ekler (§6).

   ```bash
   python -m wizard.confirm.confirm prepare \
       --draft brandpack/draft --survey anket-cevaplari.txt \
       --out brandpack/confirm/session.json
   ```

2. **Soru-cevap turu** — `session.json` içindeki her soru kullanıcıya sorulur;
   cevaplar dosyadaki `answer` alanına, sorunun `answer_format` şablonuna uygun
   yapılandırılmış nesne olarak işlenir ve `status` `"answered"` (veya gerekçeli
   `"deferred"`) yapılır. Bu turu bir insan ya da bir yardımcı (ör. sohbette
   Claude) yürütebilir — modül kanaldan bağımsızdır.

3. **`apply`** — cevapları doğrular ve canlı paketi yazar:

   ```bash
   python -m wizard.confirm.confirm apply \
       --session brandpack/confirm/session.json \
       --draft brandpack/draft --live brandpack/live
   ```

## Doğrulama kuralları

- Cevapsız (`open`) soru varken canlıya yazım REDDEDİLİR.
- `conflict: true` (ÇELİŞKİ) soruları ERTELENEMEZ (§6); diğer sorular ancak
  `defer_reason` ile ertelenebilir — ertelenen konu canlıya İŞLENMEZ.
- `named_references` yalnız `permission_confirmed: true` ile dolar (§9 yazılı izin).
- `not_offered` yalnız kullanıcı cevabından gelir (§9).
- Terim sorusu cevaplanmadıysa taslak terimler canlıya ONAYSIZ geçmez — boş sözlük yazılır.
- Çıktılar `brandpack/schema/` zorunlu koşullarına karşı denetlenir; var olan
  canlı paketin üzerine yazmak `--force` ister.
- `approval_log.json`: her sorunun cevabı/erteleme gerekçesiyle iz kaydı.

Harici bağımlılık yok — saf Python stdlib (3.11+).
