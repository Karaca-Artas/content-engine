"""Kalite cetveli uygulayıcı.

Cetveller engine/scoring/rubrics/ altındaki jenerik ŞABLONLARDAN gelir; sihirbaz bunları
markaya uyarlayıp brandpack'e yazar. Puanlama her zaman brandpack'teki uyarlanmış cetvelle
yapılır ve cetvel sürümü çıktıya damgalanır (sürüm değişirse tüm sayfalar yeniden puanlanır).

İki tip kriter:
- otomatik ölçülen (varlık/yokluk: tablo, iç link, meta uyumu, dönüşüm çağrısı...)
- model yargısı gerektiren (görselin gerçekliği, dil doğruluğu, alıcı sorusu karşılığı...)
"""


def score_page(page: dict, rubric: dict, brandpack: dict) -> dict:
    """Tek sayfayı cetvelle puanlar; kriter bazında döküm döndürür."""
    raise NotImplementedError("Faz 1")
