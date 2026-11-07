import hashlib
import re

import chromadb
import jieba

from pathlib import Path

from kb.config import VAULT, chroma_dir
from kb.llm import allowed, embed
from kb.notes import load_chunks

jieba.setLogLevel(60)  # 關掉 jieba 載入字典時的訊息
BATCH = 64


def tokenize(text: str) -> list[str]:
    """給 BM25 用：中文用 jieba 斷詞，英文轉小寫，去掉空白和標點。"""
    return [t.lower() for t in jieba.lcut_for_search(text) if re.search(r"\w", t)]


def chunk_id(path: str, text: str) -> str:
    # 用內容算 hash 當 id：內容沒變，id 就不變，不用重新產生向量
    return hashlib.sha256(f"{path}\n{text}".encode()).hexdigest()[:16]


def collection(vault: Path = VAULT):
    client = chromadb.PersistentClient(path=str(chroma_dir(vault)))
    # embedding_function=None：不用 Chroma 內建的英文模型，向量由我們自己提供
    return client.get_or_create_collection(
        "notes", embedding_function=None, configuration={"hnsw": {"space": "cosine"}}
    )


def build_index() -> tuple[int, int, int]:
    """把 vault 同步進 Chroma，回傳 (總段落數, 新增, 刪除)。"""
    chunks = {chunk_id(c.path, c.text): c for c in allowed(load_chunks())}
    col = collection()
    existing = set(col.get(include=[])["ids"])

    new = [(i, c) for i, c in chunks.items() if i not in existing]
    for start in range(0, len(new), BATCH):
        batch = new[start : start + BATCH]
        col.add(
            ids=[i for i, _ in batch],
            embeddings=embed([c.text for _, c in batch]),
            documents=[c.text for _, c in batch],
            metadatas=[{"path": c.path, "title": c.title, "private": c.private} for _, c in batch],
        )

    stale = list(existing - chunks.keys())  # 筆記被改掉或刪掉的舊段落
    if stale:
        col.delete(ids=stale)
    return len(chunks), len(new), len(stale)