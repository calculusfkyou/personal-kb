from pathlib import Path

import pytest

import kb.lint
from kb.lint import llm_checks, program_checks


def write(vault: Path, rel: str, text: str) -> None:
    f = vault / rel
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(text, encoding="utf-8")


@pytest.fixture
def vault(tmp_path: Path) -> Path:
    write(tmp_path, "notes/private/睡眠.md", "---\nsummary: 睡眠\n---\n- 見 [[咖啡]]（來源：[[inbox/S]]）")
    write(tmp_path, "notes/private/咖啡.md", "---\nsummary: 咖啡\n---\n- 見 [[睡眠]]、[[運動]]、[[inbox/不存在]]")
    write(tmp_path, "notes/private/閱讀.md", "- 只連到原話 [[inbox/S]]")
    write(tmp_path, "inbox/S.md", "原話")
    write(tmp_path, "index.md", "- [[notes/private/閱讀]]")  # index.md 的連結不算
    return tmp_path


def test_finds_orphan(vault):
    issues = program_checks(vault)
    assert any("孤兒" in i and "閱讀" in i for i in issues)
    assert not any("孤兒" in i and ("睡眠" in i or "咖啡" in i) for i in issues)


def test_finds_broken_links(vault):
    broken = [i for i in program_checks(vault) if "失效連結" in i]
    assert any("[[運動]]" in i for i in broken)
    assert any("[[inbox/不存在]]" in i for i in broken)
    assert not any("[[inbox/S]]" in i or "[[睡眠]]" in i for i in broken)


def test_finds_missing_summary(vault):
    missing = [i for i in program_checks(vault) if "沒有摘要" in i]
    assert len(missing) == 1 and "閱讀" in missing[0]


def test_attachment_links_not_broken(vault):
    write(vault, "notes/private/圖.md", "![[圖.png]] [[imported/講義.pdf]] [[沒有.png]]")
    (vault / "圖.png").write_bytes(b"")
    (vault / "imported").mkdir(exist_ok=True)
    (vault / "imported/講義.pdf").write_bytes(b"")
    broken = [i for i in program_checks(vault) if "失效連結" in i and "圖.md" in i]
    assert broken == ["失效連結：notes/private/圖.md → [[沒有.png]]"]


def fake_search(results):
    return lambda q, k=5: ([{"path": p} for p in results.get(q, [])], [])


def test_llm_checks(vault, monkeypatch):
    # 咖啡的搜尋結果裡有一篇已經被刪掉的筆記（索引過期），不應該當掉
    monkeypatch.setattr(kb.lint, "search", fake_search({"咖啡": ["notes/private/睡眠.md", "notes/private/已刪除.md"]}))
    reply = {"analysis": "", "issues": [
        {"pages": ["a", "b"], "lines": ["- 見 [[咖啡]]"], "problem": "真的問題"},
        {"pages": ["a"], "lines": ["編出來的一行"], "problem": "假的問題"},
    ]}
    monkeypatch.setattr(kb.lint, "chat_json", lambda *a, **k: reply)
    before = {p: p.read_bytes() for p in vault.rglob("*") if p.is_file()}
    issues = llm_checks(vault, "m")
    assert len(issues) == 1 and "真的問題" in issues[0]
    assert {p: p.read_bytes() for p in vault.rglob("*") if p.is_file()} == before


def test_llm_checks_without_index(vault, monkeypatch):
    monkeypatch.setattr(kb.lint, "search", fake_search({}))
    assert "kb index" in llm_checks(vault, "m")[0]


def test_lint_changes_nothing(vault):
    before = {p: p.read_bytes() for p in vault.rglob("*") if p.is_file()}
    program_checks(vault)
    assert {p: p.read_bytes() for p in vault.rglob("*") if p.is_file()} == before
