"""Nazik site tarayıcısı (method.md §8).

Kurallar: düşük eşzamanlılık, istekler arası bekleme, acil durdurma anahtarı
(config.crawler.kill_switch_file varsa tarama derhal durur). Hedef sitenin
önbellek/altyapı ayarlarına asla dokunulmaz.
"""


def crawl(config: dict) -> list[dict]:
    raise NotImplementedError("Faz 1")
