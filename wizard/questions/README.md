# Müşteri sık-soru alımı (wizard/questions)

Müşteri yazışmalarından çıkarılan ANONİM sık-soru taslağını doğrular ve
onayla canlı pakete (`brandpack/live/customer_questions.json`) yazar.
Dosya pakete girince `faq_coverage` kriteri model yargısında canlanır ve
cetveller yeniden uyarlanır (`wizard/rubrics/adapt.py`, b sayacı artar).

Kurallar (docs/method.md + brandpack/SCHEMA.md):

- **Sihirbaz posta kutusuna erişmez, veri uydurmaz.** Taslağı oturum içinde,
  insan gözetiminde Claude çıkarır; bu modül yalnız doğrular ve yazar.
- **Anonimlik zorunlu:** ad, firma, fiyat, e-posta, telefon dosyaya giremez.
  Mekanik kalıplar (e-posta/telefon/para) burada RED edilir; isim/firma
  denetimi listeyi onaylayan insandadır — ikisi birlikte gerekir.
- **Tek seferlik tarama, ay etiketli kayıt:** her kayıt `first_seen`/`last_seen`
  taşır; motor yeni kayıtlara daha çok ağırlık verir.
- **Varsayılan dry-run:** `--apply` verilmeden pakete dosya yazılmaz
  (önce anlat, onayla uygula).

Kullanım:

    python -m wizard.questions.ingest \
        --draft draft_customer_questions.json \
        --brandpack ../brandpack/live [--apply]
