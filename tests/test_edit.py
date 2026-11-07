from pathlib import Path

import pytest

from kb.edit import Edit, EditError, plan_changes, render_diff, save, write_index
from kb.notes import split_frontmatter

SRC = "inbox/S"
LINK = "（來源：[[inbox/S]]）"
SLEEP = "notes/private/睡眠.md"


@pytest.fixture
def vault(tmp_path: Path) -> Path:
    f = tmp_path / SLEEP
    f.parent.mkdir(parents=True)
    f.write_text("# 睡眠\n\n## 作息\n- 12 點半睡\n\n## 改善方向\n- 早點睡\n", encoding="utf-8")
    (tmp_path / "style.md").write_text("# 寫作偏好\n- 用條列\n", encoding="utf-8")
    return tmp_path


def snapshot(vault: Path) -> dict[str, str]:
    return {p.relative_to(vault).as_posix(): p.read_text(encoding="utf-8") for p in vault.rglob("*") if p.is_file()}


def test_append_to_section(vault):
    new = plan_changes(vault, [Edit("append", SLEEP, "- 11 點睡", section="作息")], SRC)[SLEEP]
    lines = new.splitlines()
    assert lines.index(f"- 11 點睡{LINK}") == lines.index("- 12 點半睡") + 1
    assert lines.index(f"- 11 點睡{LINK}") < lines.index("## 改善方向")


def test_append_missing_section(vault):
    new = plan_changes(vault, [Edit("append", SLEEP, "- 每天走路", section="運動")], SRC)[SLEEP]
    assert new.rstrip().endswith(f"## 運動\n- 每天走路{LINK}")


def test_replace_one_line(vault):
    new = plan_changes(vault, [Edit("replace", SLEEP, "- 11 點睡", old="- 12 點半睡")], SRC)[SLEEP]
    assert f"- 11 點睡{LINK}" in new and "12 點半" not in new


@pytest.mark.parametrize("old", ["- 不存在的一行", "", "- 早點睡\n- 12 點半睡"])
def test_replace_missing_line_rejected(vault, old):
    with pytest.raises(EditError):
        plan_changes(vault, [Edit("replace", SLEEP, "x", old=old)], SRC)


def test_replace_duplicate_line_rejected(vault):
    (vault / SLEEP).write_text("- 一樣\n- 一樣\n", encoding="utf-8")
    with pytest.raises(EditError):
        plan_changes(vault, [Edit("replace", SLEEP, "x", old="- 一樣")], SRC)


def test_create_sets_summary(vault):
    page = "notes/private/運動.md"
    new = plan_changes(vault, [Edit("create", page, "# 運動\n- 每天走路", summary="運動習慣")], SRC)[page]
    meta, body = split_frontmatter(new)
    assert meta == {"summary": "運動習慣"}
    assert body == f"# 運動\n- 每天走路{LINK}\n"


@pytest.mark.parametrize("edit", [
    Edit("create", SLEEP, "x", summary="s"),               # 已經存在
    Edit("create", "notes/private/新.md", "x"),             # 沒有 summary
    Edit("append", "notes/private/沒有.md", "x"),           # 不存在、也沒有 section
    Edit("append", SLEEP, "x"),                             # 沒有 section
    Edit("replace", SLEEP, "- 12 點半睡", old="- 12 點半睡"),  # 前後一樣
    Edit("delete", "notes/private/沒有.md"),
    Edit("rename", SLEEP),                                  # 不認得的動作
])
def test_invalid_edits_rejected(vault, edit):
    with pytest.raises(EditError):
        plan_changes(vault, [edit], SRC)


def test_append_to_missing_note_creates_it(vault):
    page = "notes/private/運動.md"
    new = plan_changes(vault, [Edit("append", page, "- 每週跑三次", section="頻率")], SRC)[page]
    meta, body = split_frontmatter(new)
    assert meta == {"summary": "運動"}
    assert body == f"# 運動\n\n## 頻率\n- 每週跑三次{LINK}\n"


def test_diff_without_trailing_newline(vault):
    (vault / SLEEP).write_text("# 睡眠\n- 最後一行", encoding="utf-8")
    diff = render_diff(vault, {SLEEP: "# 睡眠\n- 最後一行\n- 新的\n"})
    assert "\n+- 新的" in diff and "最後一行+" not in diff


def test_non_dict_frontmatter_kept(vault):
    (vault / SLEEP).write_text("---\n一段引言\n---\n## 作息\n- a\n", encoding="utf-8")
    new = plan_changes(vault, [Edit("append", SLEEP, "- b", section="作息")], SRC)[SLEEP]
    assert new.startswith("---\n一段引言\n---\n")


def test_user_frontmatter_untouched_without_summary(vault):
    fm = "---\ntags: [睡眠, 健康]  # 註解\n---\n"
    (vault / SLEEP).write_text(fm + "## 作息\n- a\n", encoding="utf-8")
    new = plan_changes(vault, [Edit("append", SLEEP, "- b", section="作息")], SRC)[SLEEP]
    assert new.startswith(fm)


@pytest.mark.parametrize("edits", [
    [Edit("delete", SLEEP), Edit("create", SLEEP, "# 新", summary="s")],     # 先刪再建會繞過 .trash
    [Edit("create", "notes/private/新.md", "# 新", summary="s"), Edit("delete", "notes/private/新.md")],
    [Edit("delete", SLEEP), Edit("append", "notes/private//睡眠.md", "- x", section="作息")],
])
def test_delete_conflicts_rejected(vault, edits):
    with pytest.raises(EditError):
        plan_changes(vault, edits, SRC)


def test_section_with_hashes_and_duplicates(vault):
    new = plan_changes(vault, [Edit("append", SLEEP, "- b", section="## 作息")], SRC)[SLEEP]
    assert "## ## 作息" not in new and new.count("## 作息") == 1
    (vault / SLEEP).write_text("## 平日\n### 備註\n- a\n## 假日\n### 備註\n- b\n", encoding="utf-8")
    with pytest.raises(EditError):
        plan_changes(vault, [Edit("append", SLEEP, "- c", section="備註")], SRC)


def test_model_written_source_link_replaced(vault):
    new = plan_changes(vault, [Edit("append", SLEEP, "- y（來源：[[inbox/假的]]）", section="作息")], SRC)[SLEEP]
    assert f"- y{LINK}" in new and "假的" not in new


def test_replace_tolerates_spacing_and_source(vault):
    (vault / SLEEP).write_text(f"- 12 點半睡{LINK}\n", encoding="utf-8")
    new = plan_changes(vault, [Edit("replace", SLEEP, "- 11 點睡", old="- 12點半睡")], SRC)[SLEEP]
    assert new == f"- 11 點睡{LINK}\n"


def test_style_created_when_missing(vault):
    (vault / "style.md").unlink()
    new = plan_changes(vault, [Edit("append", "style.md", "- 寫精簡", section="寫作偏好")], SRC)["style.md"]
    assert new == "# 寫作偏好\n\n- 寫精簡\n"


def test_save_checks_before_writing(vault):
    (vault / "imported").mkdir()
    (vault / "imported/講義.md").write_text("舊的", encoding="utf-8")
    with pytest.raises(FileExistsError):
        save(vault, {}, "x", "S", imported=("講義.md", "新的"))
    assert not (vault / "inbox").exists()


def test_control_characters_rejected(vault):
    with pytest.raises(EditError):
        plan_changes(vault, [Edit("append", SLEEP, "- hidden\x1b[1A\x1b[2K", section="作息")], SRC)


@pytest.mark.parametrize("content", ["- 看不見​的字", "- tag\U000e0041", "- ﻿bom"])
def test_invisible_characters_rejected(vault, content):
    with pytest.raises(EditError):
        plan_changes(vault, [Edit("append", SLEEP, content, section="作息")], SRC)


def test_emoji_joiner_allowed(vault):
    plan_changes(vault, [Edit("append", SLEEP, "- 👨‍👩‍👧", section="作息")], SRC)


def test_multiline_summary_rejected(vault):
    with pytest.raises(EditError):
        plan_changes(vault, [Edit("create", "notes/private/a.md", "# a", summary="s\n- [[fake]]")], SRC)


def test_error_message_escapes_control_chars(vault):
    with pytest.raises(EditError) as err:
        plan_changes(vault, [Edit("delete", "notes/private/\x1b]52;c;x\x07a.md")], SRC)
    assert "\x1b" not in str(err.value)


def test_replace_old_only_source_link_rejected(vault):
    (vault / SLEEP).write_text("# 睡眠\n\n- a\n", encoding="utf-8")
    with pytest.raises(EditError):
        plan_changes(vault, [Edit("replace", SLEEP, "- b", old="（來源：[[inbox/x]]）")], SRC)


def test_halfwidth_source_link_replaced(vault):
    new = plan_changes(vault, [Edit("append", SLEEP, "- y (來源: [[inbox/假的]])", section="作息")], SRC)[SLEEP]
    assert f"- y{LINK}" in new


def test_save_records_attachment_in_inbox(vault):
    save(vault, {}, "整理重點", "S", imported=("講義.md", "內容"))
    assert "[[imported/講義]]" in (vault / "inbox/S.md").read_text(encoding="utf-8")


def test_create_then_append_same_page(vault):
    page = "notes/private/運動.md"
    new = plan_changes(vault, [
        Edit("create", page, "# 運動\n\n## 頻率\n- 每週三次", summary="運動"),
        Edit("append", page, "- 週末打球", section="頻率"),
    ], SRC)[page]
    assert new.index("每週三次") < new.index("週末打球")


def test_delete_marks_none(vault):
    assert plan_changes(vault, [Edit("delete", SLEEP)], SRC) == {SLEEP: None}


@pytest.mark.parametrize("page", [
    "notes/private/../shared/x.md", "/etc/x.md", "notes/private/x.txt",
    "notes/shared/x.md", "index.md", "log.md", "inbox/x.md", "imported/x.md",
])
def test_rejects_bad_paths(vault, page):
    with pytest.raises(EditError):
        plan_changes(vault, [Edit("create", page, "x", summary="s")], SRC)


def test_style_rules(vault):
    new = plan_changes(vault, [Edit("append", "style.md", "- 寫精簡一點", section="寫作偏好")], SRC)["style.md"]
    assert "- 寫精簡一點" in new and "來源" not in new
    with pytest.raises(EditError):
        plan_changes(vault, [Edit("delete", "style.md")], SRC)


def test_one_bad_edit_rejects_batch(vault):
    before = snapshot(vault)
    with pytest.raises(EditError, match="第 2 項"):
        plan_changes(vault, [
            Edit("append", SLEEP, "- ok", section="作息"),
            Edit("create", "notes/shared/x.md", "x", summary="s"),
        ], SRC)
    assert snapshot(vault) == before


def test_plan_and_diff_write_nothing(vault):
    before = snapshot(vault)
    changes = plan_changes(vault, [Edit("append", SLEEP, "- 11 點睡", section="作息"), Edit("delete", SLEEP)], SRC)
    render_diff(vault, changes)
    assert snapshot(vault) == before


def test_render_diff_shows_changes(vault):
    diff = render_diff(vault, plan_changes(vault, [Edit("append", SLEEP, "- 11 點睡", section="作息")], SRC))
    assert f"+- 11 點睡{LINK}" in diff
    assert "12 點半睡" in render_diff(vault, {SLEEP: None})  # 刪除時顯示完整內容


def test_save_writes_everything(vault):
    page = "notes/private/運動.md"
    changes = plan_changes(vault, [Edit("create", page, "# 運動\n- 走路", summary="運動習慣")], SRC)
    changes |= {SLEEP: None}
    save(vault, changes, "我每天走路，睡眠那篇刪掉", "S", imported=("講義.md", "講義內容"))

    assert (vault / "inbox/S.md").read_text(encoding="utf-8").startswith("我每天走路，睡眠那篇刪掉\n")
    assert (vault / "imported/講義.md").read_text(encoding="utf-8") == "講義內容"
    assert (vault / page).is_file()
    assert not (vault / SLEEP).exists()
    assert (vault / ".trash" / SLEEP).is_file()
    index = (vault / "index.md").read_text(encoding="utf-8")
    assert "[[notes/private/運動]]：運動習慣" in index and "睡眠" not in index
    log = (vault / "log.md").read_text(encoding="utf-8")
    assert "[[inbox/S]]" in log and "新增 notes/private/運動.md" in log and "刪除 notes/private/睡眠.md" in log


def test_save_keeps_older_trash(vault):
    (vault / ".trash" / SLEEP).parent.mkdir(parents=True)
    (vault / ".trash" / SLEEP).write_text("舊的", encoding="utf-8")
    save(vault, {SLEEP: None}, "刪掉", "S")
    assert (vault / ".trash" / SLEEP).read_text(encoding="utf-8") == "舊的"
    assert (vault / ".trash/notes/private/睡眠-S.md").is_file()


def test_write_index_lists_notes_without_summary(vault):
    write_index(vault)
    assert "- [[notes/private/睡眠]]" in (vault / "index.md").read_text(encoding="utf-8")
