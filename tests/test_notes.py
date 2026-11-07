from pathlib import Path

from kb.config import chroma_dir
from kb.notes import is_private, load_chunks, load_links


def write(vault: Path, rel: str, text: str) -> None:
    f = vault / rel
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(text, encoding="utf-8")


def test_is_private():
    assert not is_private("notes/shared/a.md")
    for path in ["notes/private/a.md", "inbox/a.md", "imported/a.md", "imported/shared/a.md"]:
        assert is_private(path)


def test_load_chunks_scope(tmp_path):
    for rel in [
        "notes/private/a.md", "imported/b.md", "inbox/c.md",
        "index.md", "log.md", "style.md", ".trash/d.md",
    ]:
        write(tmp_path, rel, "# t\n內容")
    assert {c.path for c in load_chunks(tmp_path)} == {"notes/private/a.md", "imported/b.md"}


def test_links_use_stem(tmp_path):
    write(tmp_path, "notes/private/a.md", "見 [[inbox/2026-11-08-153000]]、[[b]]、[[v1.0 計畫]]")
    assert load_links(tmp_path)["a"] == {"2026-11-08-153000", "b", "v1.0 計畫"}


def test_index_md_not_a_link_source(tmp_path):
    write(tmp_path, "index.md", "- [[a]]")
    write(tmp_path, "notes/private/a.md", "沒有連結")
    assert "a" not in load_links(tmp_path)


def test_chroma_dir_differs_per_vault():
    assert chroma_dir(Path("vault")) != chroma_dir(Path("other/vault"))
