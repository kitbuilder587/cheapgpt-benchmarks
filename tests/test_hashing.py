from cheapgpt_benchmarks.hashing import content_sha256


def test_hash_is_canonical_across_key_order() -> None:
    assert content_sha256({"a": 1, "b": 2}) == content_sha256({"b": 2, "a": 1})
