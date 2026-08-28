"""Öncelik formülü ve dört kutulu fırsat sınıflandırması (docs/method.md §2-3)."""

BOXES = ("title_meta", "enrich", "merge_or_remove", "new_page")


def priority(score: int, impressions: int) -> int:
    """Öncelik = (100 - kalite_puanı) × gösterim."""
    return (100 - score) * impressions


def action_queue(items: list[dict], cap: int) -> tuple[list[dict], list[dict]]:
    """Önceliğe göre sıralar; (kuyruk, bekleme_listesi) döndürür. cap = aylık tavan."""
    ranked = sorted(items, key=lambda i: priority(i["score"], i["impressions"]), reverse=True)
    return ranked[:cap], ranked[cap:]
