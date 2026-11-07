"""kb eval：用一組固定的題目衡量搜尋和回答的品質，改設定前後各跑一次比較。"""

from pathlib import Path

import yaml

NOT_FOUND = "找不到"


def hit_at_k(texts: list[str], evidence: list[str], k: int) -> bool:
    """前 k 個段落裡，是否包含所有證據片語。"""
    top = texts[:k]
    return all(any(ev in t for t in top) for ev in evidence)


def reciprocal_rank(texts: list[str], evidence: list[str]) -> float:
    """第一個包含任一證據片語的段落，名次的倒數；都沒有則為 0。"""
    for rank, t in enumerate(texts, 1):
        if any(ev in t for ev in evidence):
            return 1 / rank
    return 0.0


def load_questions(path: Path) -> list[dict]:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def run(path: Path, answers: bool, model: str) -> list[str]:
    from kb.ask import ask
    from kb.config import VAULT
    from kb.search import search

    questions = load_questions(path)
    answerable = [q for q in questions if q.get("answerable", True)]
    lines, hit3, hit5, mrr = [], 0, 0, 0.0
    for q in answerable:
        top, _ = search(q["question"], k=5)  # 連結擴展之前
        texts = [d["text"] for d in top]
        h3, h5 = hit_at_k(texts, q["evidence"], 3), hit_at_k(texts, q["evidence"], 5)
        hit3, hit5, mrr = hit3 + h3, hit5 + h5, mrr + reciprocal_rank(texts, q["evidence"])
        if not h5:
            lines.append(f"  沒找到：{q['question']}")
    n = len(answerable) or 1
    lines.insert(0, f"搜尋（{len(answerable)} 題）：hit@3 {hit3 / n:.2f}　hit@5 {hit5 / n:.2f}　MRR {mrr / n:.2f}")
    # 題目是依照某個 vault 出的，用錯 vault 時分數沒有意義
    lines.insert(0, f"vault：{VAULT}　題目：{path}")

    if answers:
        ok = 0
        for q in questions:
            answer, _ = ask(q["question"], model)
            passed = (q["source"] in answer) if q.get("answerable", True) else (NOT_FOUND in answer)
            ok += passed
            if not passed:
                lines.append(f"  回答不合格：{q['question']}\n    → {answer[:120]}")
        lines.insert(2, f"回答（{len(questions)} 題，粗略的規則檢查）：{ok}/{len(questions)} 合格")
    return lines
