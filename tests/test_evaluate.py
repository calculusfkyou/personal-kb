from kb.evaluate import hit_at_k, reciprocal_rank

TEXTS = ["咖啡 一天最多兩杯", "睡眠 12 點半睡", "早晨 先喝溫水"]


def test_hit_at_k():
    assert hit_at_k(TEXTS, ["12 點半睡"], 2)
    assert not hit_at_k(TEXTS, ["溫水"], 2)
    assert hit_at_k(TEXTS, ["兩杯", "溫水"], 3)       # 所有證據都要出現
    assert not hit_at_k(TEXTS, ["兩杯", "寵物"], 3)


def test_reciprocal_rank():
    assert reciprocal_rank(TEXTS, ["兩杯"]) == 1
    assert reciprocal_rank(TEXTS, ["溫水"]) == 1 / 3
    assert reciprocal_rank(TEXTS, ["寵物"]) == 0
