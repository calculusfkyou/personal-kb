import re
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

import yaml

from kb.config import MAX_CHUNK_CHARS, VAULT

# [[睡眠]]、[[睡眠|別名]]、[[睡眠#作息]] 都只取「睡眠」
LINK_RE = re.compile(r"\[\[([^\]|#]+)")

# 只有這些資料夾會建立索引；inbox、index.md、log.md、style.md、.trash 都不建
INDEXED = ("notes/", "imported/")

FRONTMATTER_RE = re.compile(r"\A---\n(.*?)\n---\n", re.S)


def split_frontmatter(text: str) -> tuple[dict, str]:
    """拆開筆記開頭的 --- frontmatter ---，回傳 (欄位, 內文)。"""
    m = FRONTMATTER_RE.match(text)
    if not m:
        return {}, text
    try:
        meta = yaml.safe_load(m.group(1))
    except yaml.YAMLError:  # 使用者手動改壞時，當作沒有 frontmatter
        return {}, text
    if not isinstance(meta, dict):  # 不是 key: value 格式時保留原文，以免被切掉
        return {}, text
    return meta, text[m.end():]


@dataclass
class Chunk:
    path: str      # 相對於 vault 的路徑，例如 notes/private/睡眠.md
    title: str     # 例如「睡眠 > 作息」
    text: str      # 要被搜尋的內容（開頭包含 title）
    private: bool
    mtime: float


def is_private(path: str) -> bool:
    # 只有 notes/shared/ 算可分享，其他（含 inbox、imported）一律當私人
    return not path.startswith("notes/shared/")


def md_files(vault: Path = VAULT):
    for f in sorted(vault.rglob("*.md")):
        rel = f.relative_to(vault).as_posix()
        if not rel.startswith("."):  # 跳過 .obsidian、.trash
            yield f, rel


def split_sections(md: str):
    """依 # 標題切段，回傳 (標題, 內文)。程式碼區塊裡的 # 不算標題。"""
    heading, lines, in_code = "", [], False
    for line in md.splitlines():
        if line.startswith("```"):
            in_code = not in_code
        if line.startswith("#") and not in_code:
            if "".join(lines).strip():
                yield heading, lines
            heading, lines = line.lstrip("#").strip(), []
        else:
            lines.append(line)
    if "".join(lines).strip():
        yield heading, lines


def pack(lines: list[str], limit: int):
    """把一段的多行，裝成每塊不超過 limit 字的小塊。"""
    # shortcut: 單一行超過 limit 時不再切開；遇到很長的段落再改
    buf = ""
    for line in lines:
        if buf.strip() and len(buf) + len(line) > limit:
            yield buf.strip()
            buf = ""
        buf += line + "\n"
    if buf.strip():
        yield buf.strip()


def load_chunks(vault: Path = VAULT) -> list[Chunk]:
    chunks = []
    for f, rel in md_files(vault):
        if not rel.startswith(INDEXED):
            continue
        mtime = f.stat().st_mtime
        for heading, lines in split_sections(split_frontmatter(f.read_text(encoding="utf-8"))[1]):
            title = f"{f.stem} > {heading}" if heading and heading != f.stem else f.stem
            for piece in pack(lines, MAX_CHUNK_CHARS):
                chunks.append(Chunk(rel, title, f"{title}\n{piece}", is_private(rel), mtime))
    return chunks


def link_targets(text: str) -> list[str]:
    """原始的連結目標，可能帶路徑，例如 inbox/2026-11-08-153000。"""
    return [t.strip() for t in LINK_RE.findall(text)]


def load_links(vault: Path = VAULT) -> dict[str, set[str]]:
    """雙向連結表：筆記名 → 相連的筆記名（連出去、連進來都算）。"""
    # shortcut: 用檔名當筆記名，兩個資料夾有同名筆記時會混在一起
    graph = defaultdict(set)
    for f, rel in md_files(vault):
        if not rel.startswith(INDEXED):  # index.md 連到每一篇，算進來就沒有孤兒筆記了
            continue
        for target in link_targets(f.read_text(encoding="utf-8")):
            # [[inbox/xxx]] 和 [[xxx]] 視為同一個；不用 .stem，以免「v1.0 計畫」被截成「v1」
            target = Path(target).name.removesuffix(".md")
            if target != f.stem:
                graph[f.stem].add(target)
                graph[target].add(f.stem)
    return dict(graph)