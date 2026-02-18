from __future__ import annotations


def rrf_fuse(rankings: dict[str, list[str]], *, k: int = 60) -> dict[str, float]:
    scores: dict[str, float] = {}
    for ranked_ids in rankings.values():
        for rank, item_id in enumerate(ranked_ids, start=1):
            scores[item_id] = scores.get(item_id, 0.0) + (1.0 / (k + rank))
    return dict(sorted(scores.items(), key=lambda kv: kv[1], reverse=True))
