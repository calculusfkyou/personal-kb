import functools
from pathlib import Path

import typer

from kb.config import CHAT_MODEL, LLM_BASE_URL, ROOT, VAULT

app = typer.Typer(help="個人知識庫", no_args_is_help=True)

# 各指令在函式內才 import，避免每次執行都要載入 chromadb，指令啟動比較快


@app.callback()
def main():
    if not VAULT.is_dir():
        typer.echo(f"找不到 vault 資料夾：{VAULT}\n第一次使用請先建立：mkdir -p vault/notes/private vault/notes/shared")
        raise typer.Exit(1)


def needs_lm_studio(fn):
    """LM Studio 沒開時印出提示，而不是一整段 traceback。"""
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        import openai

        try:
            return fn(*args, **kwargs)
        except openai.APIConnectionError:
            typer.echo(f"連不上 LM Studio（{LLM_BASE_URL}），請先在 LM Studio 的 Developer 頁面開啟 Server。")
            raise typer.Exit(1)
    return wrapper


@app.command()
@needs_lm_studio
def index():
    """把 vault 的筆記同步進索引。"""
    from kb.edit import write_index
    from kb.index import build_index

    total, new, stale = build_index()
    write_index(VAULT)  # 使用者在 Obsidian 手動新增、刪除的筆記也反映到 index.md
    typer.echo(f"共 {total} 個段落：新增 {new}、刪除 {stale}")


@app.command()
@needs_lm_studio
def search(question: str, k: int = 5):
    """只搜尋，不呼叫 LLM。"""
    from kb.search import search as do_search

    top, extra = do_search(question, k)
    for n, d in enumerate(top, 1):
        typer.echo(f"{n}. [{d['path']}] {d['title']}")
    for d in extra:
        typer.echo(f"   ↳ 連結 [{d['path']}] {d['title']}")


@app.command()
@needs_lm_studio
def ask(question: str, model: str = CHAT_MODEL):
    """根據筆記回答問題，並附上出處。"""
    from kb.ask import ask as do_ask
    from kb.edit import clean

    answer, docs = do_ask(question, model)
    typer.echo(clean(answer))
    typer.echo("\n參考的筆記：" + "、".join(sorted({d["path"] for d in docs})))


def convert(file: Path) -> tuple[str, str]:
    """把檔案轉成 md，回傳 (imported/ 裡的檔名, 內容)；已存在或讀不到文字時結束。"""
    from markitdown import MarkItDown

    name = f"{file.stem}.md"
    if (VAULT / "imported" / name).exists():
        typer.echo(f"imported/{name} 已經存在，請先刪除或改名再匯入")
        raise typer.Exit(1)
    try:
        text = MarkItDown().convert(str(file)).text_content or ""
    except Exception as err:  # markitdown 對各種格式會丟出不同的例外
        typer.echo(f"無法轉換這個檔案：{err}")
        raise typer.Exit(1)
    if not text.strip():
        typer.echo("讀不到任何文字，可能是掃描檔")
        raise typer.Exit(1)
    return name, text


@app.command(name="import")
def import_file(file: Path = typer.Argument(..., exists=True, dir_okay=False)):
    """把 PDF、Word、PPT 等檔案轉成 md，放進 vault/imported/。"""
    name, text = convert(file)
    out = VAULT / "imported" / name
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text, encoding="utf-8")
    typer.echo(f"已建立 {out}，記得執行 kb index")


@app.command()
def note(
    request: str,
    file: Path | None = typer.Option(None, "--file", exists=True, dir_okay=False, help="附加一個檔案，請 AI 依照說明整理"),
    model: str = CHAT_MODEL,
):
    """請 AI 新增、修改或刪除筆記；先顯示差異，確認後才生效。"""
    from datetime import datetime

    import openai

    import kb.config
    from kb import note as note_mod
    from kb.edit import EditError, plan_changes, render_diff, save
    from kb.llm import is_local

    if not is_local(kb.config.LLM_BASE_URL):  # 說明和筆記都是私人資料，只能送到本機
        typer.echo("kb note 只能使用本機的模型，請把 LLM_BASE_URL 設為 localhost")
        raise typer.Exit(1)

    imported = convert(file) if file else None
    if imported and len(imported[1]) > note_mod.MAX_ATTACH_CHARS:
        typer.echo(f"附加檔案太長，AI 只會整理前 {note_mod.MAX_ATTACH_CHARS} 字。")
    stamp = datetime.now().strftime("%Y-%m-%d-%H%M%S")
    try:
        edits = note_mod.propose(VAULT, request, imported[1] if imported else None, model)
        changes = plan_changes(VAULT, edits, f"inbox/{stamp}")
    except (EditError, ValueError, openai.APIError) as err:
        typer.echo(f"沒有寫入任何檔案。原因：{err}\n可以換個說法重試，或用 --model 換成其他模型。")
        raise typer.Exit(1)

    if not changes:
        typer.echo("AI 認為不需要修改任何筆記，沒有寫入任何檔案。")
        return
    def snapshot() -> dict[str, str | None]:
        return {p: (VAULT / p).read_text(encoding="utf-8") if (VAULT / p).is_file() else None for p in changes}

    before = snapshot()
    typer.echo(render_diff(VAULT, changes))
    # 差異很長時前面會被捲出畫面，確認前再列一次總覽
    kinds = {p: "刪除" if new is None else ("修改" if before[p] is not None else "新增") for p, new in changes.items()}
    typer.echo("\n總覽：" + "、".join(f"{k} {p}" for p, k in kinds.items()))
    if "style.md" in changes:
        typer.echo("注意：這次會修改 style.md，它會影響之後每一次 AI 寫的筆記。")
    if not typer.confirm("存檔？"):
        typer.echo("已取消，沒有任何檔案被改動。")
        return
    if snapshot() != before:  # 預覽期間在 Obsidian 改過，直接寫入會蓋掉剛剛的修改
        typer.echo("預覽之後這些筆記被改動過，沒有寫入任何檔案。請重新執行 kb note。")
        raise typer.Exit(1)
    try:
        save(VAULT, changes, request, stamp, imported)
    except FileExistsError as err:
        typer.echo(str(err))
        raise typer.Exit(1)
    typer.echo("已存檔。記得執行 kb index，搜尋才會找到新的內容。")


@app.command(name="eval")
@needs_lm_studio
def eval_cmd(
    answers: bool = typer.Option(False, "--answers", help="也讓 LLM 回答，檢查出處和「找不到」"),
    questions: Path = typer.Option(ROOT / "eval" / "questions.yaml", exists=True, dir_okay=False),
    model: str = CHAT_MODEL,
):
    """用固定的題目衡量搜尋（hit@3、hit@5、MRR）和回答的品質。"""
    from kb.evaluate import run

    typer.echo("\n".join(run(questions, answers, model)))


@app.command()
def lint(
    no_llm: bool = typer.Option(False, "--no-llm", help="只做程式檢查，不呼叫模型"),
    model: str = CHAT_MODEL,
):
    """健檢筆記：孤兒筆記、失效連結、沒有摘要、互相矛盾。只產生報告，不修改任何檔案。"""
    import openai

    import kb.config
    from kb.lint import llm_checks, program_checks
    from kb.llm import is_local

    issues = program_checks(VAULT)
    if not no_llm:
        if not is_local(kb.config.LLM_BASE_URL):
            typer.echo("LLM 檢查只能使用本機的模型，這次只做程式檢查。")
        else:
            try:
                issues += llm_checks(VAULT, model)
            except (ValueError, openai.APIError) as err:
                issues.append(f"（LLM 檢查失敗，只顯示程式檢查的結果：{err}）")
    issues = list(dict.fromkeys(issues))  # 同一組矛盾可能在不同分組裡各被找到一次
    typer.echo("\n".join(f"- {i}" for i in issues) if issues else "沒有發現問題。")