import kb.search
from kb.llm import allowed
from kb.notes import Chunk, pack, split_sections
from kb.search import EXPAND_FROM, MAX_EXPAND, expand, rrf


def test_split_sections_skips_code_blocks():
    md = "# A\n文字\n```\n# 這不是標題\n```\n## B\n更多"
    sections = list(split_sections(md))
    assert [h for h, _ in sections] == ["A", "B"]
    assert "# 這不是標題" in sections[0][1]


def test_pack_respects_limit():
    pieces = list(pack(["一" * 30, "二" * 30, "三" * 30], 70))
    assert len(pieces) == 2 and all(len(p) <= 70 for p in pieces)


def test_rrf_order():
    # c 在兩份排名都靠前，應該排第一
    assert rrf(["a", "c", "b"], ["c", "d"])[0] == "c"


def doc(name: str, i: int = 0) -> dict:
    return {"id": f"{name}{i}", "path": f"notes/private/{name}.md"}


def test_expand_only_from_top(monkeypatch):
    monkeypatch.setattr(kb.search, "load_links", lambda: {"A": {"X"}, "B": {"Y"}, "C": {"Z"}})
    top = [doc("A"), doc("B"), doc("C")]
    docs = {d["id"]: d for d in top + [doc("X"), doc("Y"), doc("Z")]}
    assert EXPAND_FROM == 2
    # C 排第 3，超出 EXPAND_FROM，所以它的鄰居 Z 不會被帶進來
    assert {d["path"] for d in expand(top, docs)} == {"notes/private/X.md", "notes/private/Y.md"}


def test_expand_respects_max(monkeypatch):
    monkeypatch.setattr(kb.search, "load_links", lambda: {"A": {"X"}})
    docs = {d["id"]: d for d in [doc("A")] + [doc("X", i) for i in range(5)]}
    assert len(expand([doc("A")], docs)) == MAX_EXPAND


def test_allowed_filters_private_for_remote():
    chunks = [{"private": True}, {"private": False}]
    objs = [Chunk("notes/private/a.md", "a", "a", True, 0), Chunk("notes/shared/b.md", "b", "b", False, 0)]
    assert allowed(chunks, "http://localhost:1234/v1") == chunks
    assert allowed(chunks, "https://api.example.com/v1") == [{"private": False}]
    assert [c.path for c in allowed(objs, "https://api.example.com/v1")] == ["notes/shared/b.md"]
