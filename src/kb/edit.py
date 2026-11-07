"""AI 提出的修改：驗證、在記憶體中套用、顯示差異，使用者確認後才寫入。"""

import re
import shutil
import unicodedata
from dataclasses import dataclass, replace
from difflib import unified_diff
from pathlib import Path

import yaml

from kb.notes import split_frontmatter

ACTIONS = ("create", "append", "replace", "delete")
STYLE = "style.md"
AI_FOLDER = "notes/private/"


class EditError(Exception):
    pass


@dataclass
class Edit:
    action: str
    page: str
    content: str = ""
    section: str = ""
    old: str = ""
    summary: str = ""


_FIELDS = ("action", "page", "content", "section", "old", "summary")
# 給 LM Studio structured output 用；strict 模式要求每個欄位都必填，不用的欄位由模型填空字串
EDIT_SCHEMA = {
    "type": "object",
    "properties": {
        "edits": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {f: {"type": "string"} for f in _FIELDS} | {"action": {"type": "string", "enum": list(ACTIONS)}},
                "required": list(_FIELDS),
                "additionalProperties": False,
            },
        }
    },
    "required": ["edits"],
    "additionalProperties": False,
}


def join_frontmatter(meta: dict, body: str) -> str:
    if not meta:
        return body
    return "---\n" + yaml.safe_dump(meta, allow_unicode=True, sort_keys=False) + "---\n" + body


def check_path(e: Edit) -> None:
    if e.page == STYLE:
        if e.action not in ("append", "replace"):
            raise EditError("style.md 只能 append 或 replace")
        return
    p = Path(e.page)
    if p.is_absolute() or ".." in p.parts or not e.page.startswith(AI_FOLDER) or p.suffix != ".md":
        raise EditError(f"不允許的路徑 {e.page}：AI 只能修改 {AI_FOLDER} 底下的 .md 和 {STYLE}")


SOURCE_RE = re.compile(r"[（(]\s*來源\s*[：:]\s*\[\[[^\]]*\]\]\s*[）)]")
# 終端機控制字元可以在預覽中把內容藏起來，而預覽是唯一的把關
CONTROL_RE = re.compile(r"[\x00-\x08\x0b-\x1f\x7f-\x9f‪-‮⁦-⁩]")  # 含 C1 與文字方向覆寫字元


def hidden_chars(s: str) -> bool:
    """控制字元，或零寬字元、Unicode Tag 這類看不見的格式字元（emoji 組合用的 U+200D 除外）。"""
    return bool(CONTROL_RE.search(s)) or any(unicodedata.category(c) == "Cf" and c != "‍" for c in s)


def clean(s: str) -> str:
    """印到終端機前移除控制字元，避免模型輸出的跳脫序列改寫畫面或剪貼簿。"""
    return CONTROL_RE.sub("", s)


def with_source(content: str, source: str) -> str:
    """在每一行內容後面加上來源連結；標題和空行不加。模型自己寫的來源連結會先清掉。"""
    lines = []
    for line in content.strip("\n").splitlines():
        line = SOURCE_RE.sub("", line).rstrip()
        if line.strip() and not line.lstrip().startswith("#"):
            line = f"{line}（來源：[[{source}]]）"
        lines.append(line)
    return "\n".join(lines)


def same_line(a: str, b: str) -> bool:
    """比對一行時忽略空白和來源連結：模型抄寫原文時常常漏掉或多加空格。"""
    return re.sub(r"\s+", "", SOURCE_RE.sub("", a)) == re.sub(r"\s+", "", SOURCE_RE.sub("", b))


def append_to_section(body: str, section: str, content: str) -> str:
    # shortcut: 程式碼區塊裡以 # 開頭的行也會被當成標題；筆記裡有程式碼區塊時再處理
    lines = body.splitlines()
    hits = [i for i, l in enumerate(lines) if l.startswith("#") and l.lstrip("#").strip() == section]
    if len(hits) > 1:
        raise EditError(f"有 {len(hits)} 個段落都叫「{section}」，無法判斷要加在哪一個")
    if not hits:
        return f"{body.rstrip()}\n\n## {section}\n{content}\n".lstrip("\n")
    start = hits[0]
    end = next((i for i in range(start + 1, len(lines)) if lines[i].startswith("#")), len(lines))
    while end > start + 1 and not lines[end - 1].strip():  # 插在段落的空行之前
        end -= 1
    lines[end:end] = content.splitlines()
    return "\n".join(lines) + "\n"


def replace_line(body: str, old: str, content: str) -> str:
    lines = body.splitlines()
    ok = re.sub(r"\s+", "", SOURCE_RE.sub("", old)) and "\n" not in old.strip()
    hits = [i for i, l in enumerate(lines) if ok and same_line(l, old)]
    if len(hits) != 1:
        raise EditError(f"要替換的那一行必須在筆記中剛好出現一次，實際出現 {len(hits)} 次：{old!r}")
    lines[hits[0] : hits[0] + 1] = content.splitlines()
    return "\n".join(lines) + "\n"


def plan_changes(vault: Path, edits: list[Edit], source: str) -> dict[str, str | None]:
    """依序在記憶體中套用修改，回傳 {路徑: 新內容}，None 表示刪除。任何一項不合格就整批拒絕。"""
    changes: dict[str, str | None] = {}

    def current(page: str) -> str | None:
        if page in changes:
            return changes[page]
        f = vault / page
        return f.read_text(encoding="utf-8") if f.is_file() else None

    for n, e in enumerate(edits, 1):
        try:
            # notes/private//a.md、notes/private/./a.md 都視為同一篇
            e = replace(e, page=Path(e.page).as_posix(), section=e.section.strip().lstrip("#").strip())
            if e.action not in ACTIONS:
                raise EditError(f"不認得的動作 {e.action!r}")
            if any(hidden_chars(v) for v in (e.page, e.content, e.section, e.old, e.summary)):
                raise EditError("內容含有控制字元或看不見的字元")
            if "\n" in e.summary:  # 摘要會寫進 index.md 的一行，換行會多出假的條目
                raise EditError("summary 只能有一行")
            check_path(e)
            if e.page in changes and changes[e.page] is None:
                raise EditError("這篇在同一批修改中已經被刪除")  # 避免「先刪再建」繞過 .trash/
            text = current(e.page)

            if e.action == "append" and text is None and e.section:
                # 小模型常對新主題用 append：視為新建（一樣會先給使用者確認）
                if e.page == STYLE:
                    changes[STYLE] = f"# 寫作偏好\n\n{e.content.strip()}\n"
                    continue
                stem = Path(e.page).stem
                e = Edit("create", e.page, f"# {stem}\n\n## {e.section}\n{e.content}", summary=e.summary or stem)
            content = e.content if e.page == STYLE else with_source(e.content, source)

            if e.action == "create":
                if text is not None:
                    raise EditError("筆記已經存在")
                if not e.summary.strip() or not e.content.strip():
                    raise EditError("新建筆記時 content 和 summary 都必填")
                changes[e.page] = join_frontmatter({"summary": e.summary.strip()}, content + "\n")
                continue
            if text is None:
                raise EditError("筆記不存在")
            if e.action == "delete":
                if not (vault / e.page).is_file():
                    raise EditError("只能刪除已經存在的筆記")
                changes[e.page] = None
                continue
            if not e.content.strip():
                raise EditError("content 不能是空的")

            meta, body = split_frontmatter(text)
            prefix = text[: len(text) - len(body)]  # 沒有更新摘要時，原樣保留使用者的 frontmatter
            if e.action == "append":
                if not e.section:
                    raise EditError("append 需要指定 section")
                body = append_to_section(body, e.section, content)
            else:  # replace
                if same_line(e.content, e.old):
                    raise EditError("替換前後的內容一樣，沒有實際變更")
                body = replace_line(body, e.old, content)
            if e.summary.strip() and e.page != STYLE:
                changes[e.page] = join_frontmatter(meta | {"summary": e.summary.strip()}, body)
            else:
                changes[e.page] = prefix + body
        except EditError as err:
            raise EditError(f"第 {n} 項修改（{e.action!r} {e.page!r}）不合格：{err}") from None
    return changes


def render_diff(vault: Path, changes: dict[str, str | None]) -> str:
    out = []
    for page, new in changes.items():
        f = vault / page
        old = f.read_text(encoding="utf-8") if f.is_file() else ""
        if new is None:
            out.append(f"=== 刪除 {page}（會移到 .trash/）===\n{old}")
        else:
            # 比較時統一補上結尾換行，否則最後一行會黏在一起
            a, b = (s if s.endswith("\n") or not s else s + "\n" for s in (old, new))
            out.append("".join(unified_diff(a.splitlines(True), b.splitlines(True), f"a/{page}", f"b/{page}")))
    return "\n".join(out)


def write_new(f: Path, text: str) -> None:
    f.parent.mkdir(parents=True, exist_ok=True)
    with f.open("x", encoding="utf-8") as fh:  # inbox、imported 不覆蓋既有檔案
        fh.write(text)


def save(vault: Path, changes: dict[str, str | None], request: str, stamp: str,
         imported: tuple[str, str] | None = None) -> None:
    """使用者確認後才呼叫：寫入原話、附件、筆記，刪除的移到 .trash/，更新 index.md 和 log.md。"""
    kinds = {p: "刪除" if new is None else ("修改" if (vault / p).exists() else "新增") for p, new in changes.items()}
    targets = [vault / "inbox" / f"{stamp}.md"] + ([vault / "imported" / imported[0]] if imported else [])
    if existing := [t.name for t in targets if t.exists()]:  # 先檢查，避免寫到一半才失敗
        raise FileExistsError(f"檔案已經存在，沒有寫入任何檔案：{existing}")
    attached = f"\n附加檔案：[[imported/{Path(imported[0]).stem}]]\n" if imported else ""
    write_new(vault / "inbox" / f"{stamp}.md", request.strip() + "\n" + attached)
    if imported:
        write_new(vault / "imported" / imported[0], imported[1])
    for page, new in changes.items():
        f = vault / page
        if new is None:
            dest = vault / ".trash" / page
            if dest.exists():
                dest = dest.with_name(f"{dest.stem}-{stamp}.md")
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(f, dest)
        else:
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_text(new, encoding="utf-8")
    write_index(vault)
    append_log(vault, stamp, kinds, imported[0] if imported else None)


def write_index(vault: Path) -> None:
    """依資料夾列出所有筆記和一句話摘要。使用者手動新增或刪除的筆記也會反映出來。"""
    lines = ["# 筆記目錄", "", "> 由程式自動產生，請勿手動編輯。"]
    folder = None
    notes = vault / "notes"
    for f in sorted(notes.rglob("*.md"), key=lambda f: (f.parent, f.name)) if notes.is_dir() else []:
        rel = f.relative_to(vault)
        if rel.parent.as_posix() != folder:
            folder = rel.parent.as_posix()
            lines += ["", f"## {folder}", ""]
        summary = split_frontmatter(f.read_text(encoding="utf-8"))[0].get("summary", "")
        lines.append(f"- [[{rel.with_suffix('').as_posix()}]]" + (f"：{summary}" if summary else ""))
    (vault / "index.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def append_log(vault: Path, stamp: str, kinds: dict[str, str], imported_name: str | None) -> None:
    f = vault / "log.md"
    lines = [] if f.exists() else ["# 變動紀錄", "", "> 由程式自動產生，只會追加。", ""]
    lines += [f"## {stamp}", f"- 原話：[[inbox/{stamp}]]"]
    if imported_name:
        lines.append(f"- 附加檔案：[[imported/{Path(imported_name).stem}]]")
    lines += [f"- {kind} {page}" for page, kind in kinds.items()]
    with f.open("a", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n\n")
