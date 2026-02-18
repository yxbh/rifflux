from rifflux.retrieval.rrf import rrf_fuse


def test_rrf_fusion_prioritizes_agreement() -> None:
    fused = rrf_fuse(
        {
            "lexical": ["a", "b", "c"],
            "semantic": ["b", "d", "a"],
        },
        k=60,
    )
    ids = list(fused.keys())
    assert ids[0] == "b"
    assert "a" in ids
