from pathlib import Path

import pytest
from typer.testing import CliRunner

import kb.cli
import kb.config
import kb.note
from kb.edit import Edit

SLEEP = "notes/private/睡眠.md"
runner = CliRunner()


@pytest.fixture
def vault(tmp_path, monkeypatch) -> Path:
    v = tmp_path / "vault"
    (v / SLEEP).parent.mkdir(parents=True)
    (v / SLEEP).write_text("# 睡眠\n\n## 作息\n- 12 點半睡\n", encoding="utf-8")
    monkeypatch.setattr(kb.cli, "VAULT", v)
    monkeypatch.setattr(kb.note, "propose", lambda *a, **k: [Edit("append", SLEEP, "- 11 點睡", section="作息")])
    return v


def snapshot(v: Path) -> dict[str, str]:
    return {p.relative_to(v).as_posix(): p.read_text(encoding="utf-8") for p in v.rglob("*") if p.is_file()}


def test_note_cancel_writes_nothing(vault):
    before = snapshot(vault)
    result = runner.invoke(kb.cli.app, ["note", "最近都 11 點睡"], input="n\n")
    assert "已取消" in result.output and "+- 11 點睡" in result.output
    assert "總覽：修改 notes/private/睡眠.md" in result.output
    assert snapshot(vault) == before


def test_note_cancel_with_file_writes_nothing(vault, tmp_path):
    attachment = tmp_path / "講義.txt"
    attachment.write_text("講義內容", encoding="utf-8")
    before = snapshot(vault)
    runner.invoke(kb.cli.app, ["note", "整理重點", "--file", str(attachment)], input="n\n")
    assert snapshot(vault) == before


def test_note_save_writes(vault):
    result = runner.invoke(kb.cli.app, ["note", "最近都 11 點睡"], input="y\n")
    assert result.exit_code == 0, result.output
    assert "- 11 點睡（來源：[[inbox/" in (vault / SLEEP).read_text(encoding="utf-8")
    assert len(list((vault / "inbox").glob("*.md"))) == 1
    assert "notes/private/睡眠" in (vault / "index.md").read_text(encoding="utf-8")
    assert "修改 notes/private/睡眠.md" in (vault / "log.md").read_text(encoding="utf-8")


def test_note_bad_json_writes_nothing(vault, monkeypatch):
    def bad(*a, **k):
        raise ValueError("模型回傳的不是合法的 JSON")
    monkeypatch.setattr(kb.note, "propose", bad)
    before = snapshot(vault)
    result = runner.invoke(kb.cli.app, ["note", "最近都 11 點睡"])
    assert result.exit_code != 0 and "沒有寫入任何檔案" in result.output
    assert snapshot(vault) == before


def test_note_invalid_edit_writes_nothing(vault, monkeypatch):
    monkeypatch.setattr(kb.note, "propose", lambda *a, **k: [Edit("create", "notes/shared/x.md", "x", summary="s")])
    before = snapshot(vault)
    result = runner.invoke(kb.cli.app, ["note", "x"])
    assert result.exit_code != 0 and "不允許的路徑" in result.output
    assert snapshot(vault) == before


def test_note_refuses_non_local(vault, monkeypatch):
    monkeypatch.setattr(kb.config, "LLM_BASE_URL", "https://api.example.com/v1")
    result = runner.invoke(kb.cli.app, ["note", "x"])
    assert result.exit_code != 0 and "本機" in result.output


def test_note_aborts_if_note_changed_during_preview(vault, monkeypatch):
    def confirm_after_user_edit(*a, **k):
        (vault / SLEEP).write_text("# 睡眠\n- 我在 Obsidian 改的\n", encoding="utf-8")
        return True
    monkeypatch.setattr(kb.cli.typer, "confirm", confirm_after_user_edit)
    result = runner.invoke(kb.cli.app, ["note", "最近都 11 點睡"])
    assert result.exit_code != 0 and "被改動過" in result.output
    assert (vault / SLEEP).read_text(encoding="utf-8") == "# 睡眠\n- 我在 Obsidian 改的\n"
    assert not (vault / "inbox").exists()


def test_note_existing_attachment_stops_before_model(vault, tmp_path, monkeypatch):
    (vault / "imported").mkdir()
    (vault / "imported/講義.md").write_text("舊的", encoding="utf-8")
    attachment = tmp_path / "講義.txt"
    attachment.write_text("新的", encoding="utf-8")
    monkeypatch.setattr(kb.note, "propose", lambda *a, **k: pytest.fail("不應該呼叫模型"))
    result = runner.invoke(kb.cli.app, ["note", "x", "--file", str(attachment)])
    assert result.exit_code != 0 and "已經存在" in result.output


def test_propose_rejects_non_string_fields(monkeypatch):
    monkeypatch.setattr(kb.note, "build_user", lambda *a: "")
    bad = {"edits": [{"action": "append", "page": 1, "content": "- a", "section": "作息", "old": "", "summary": ""}]}
    monkeypatch.setattr(kb.note, "chat_json", lambda *a, **k: bad)
    with pytest.raises(ValueError):
        kb.note.propose(Path("."), "x", None, "m")


def test_lm_studio_down_message(vault, monkeypatch):
    import httpx
    import openai

    import kb.index

    def down():
        raise openai.APIConnectionError(request=httpx.Request("POST", "http://localhost:1234/v1"))
    monkeypatch.setattr(kb.index, "build_index", down)
    result = runner.invoke(kb.cli.app, ["index"])
    assert result.exit_code == 1 and "LM Studio" in result.output


def test_missing_vault_message(tmp_path, monkeypatch):
    monkeypatch.setattr(kb.cli, "VAULT", tmp_path / "沒有")
    result = runner.invoke(kb.cli.app, ["index"])
    assert result.exit_code == 1 and "找不到 vault" in result.output


def test_propose_parses_edits(monkeypatch):
    fake = {"edits": [{"action": "append", "page": SLEEP, "content": "- a", "section": "作息", "old": "", "summary": ""}]}
    monkeypatch.setattr(kb.note, "build_user", lambda *a: "")
    monkeypatch.setattr(kb.note, "chat_json", lambda *a, **k: fake)
    assert kb.note.propose(Path("."), "x", None, "m") == [Edit("append", SLEEP, "- a", section="作息")]


def test_propose_rejects_wrong_shape(monkeypatch):
    monkeypatch.setattr(kb.note, "build_user", lambda *a: "")
    monkeypatch.setattr(kb.note, "chat_json", lambda *a, **k: {"edits": [{"wrong": 1}]})
    with pytest.raises(ValueError):
        kb.note.propose(Path("."), "x", None, "m")
