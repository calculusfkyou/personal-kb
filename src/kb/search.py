from pathlib import Path

from rank_bm25 import BM25Okapi

from kb.config import TOP_K
from kb.index import collection, tokenize
from kb.llm import embed
from kb.notes import load_links

CANDIDATES = 20  # BM25 和向量各取前幾名
RRF_K = 60
MAX_EXPAND = 3   # 順著連結最多多帶幾塊
EXPAND_FROM = 2  # 只從前幾名主要結果做連結擴展，排名後面的可能不相關


def rrf(*rankings: list[str]) -> list[str]:
    """Reciprocal rank fusion：每份排名中，第 r 名得 1/(60+r) 分，加總後排序。"""
    scores: dict[str, float] = {}
    for ranking in rankings:
        for rank, cid in enumerate(ranking, 1):
            scores[cid] = scores.get(cid, 0) + 1 / (RRF_K + rank)
    return sorted(scores, key=scores.get, reverse=True)


def search(question: str, k: int = TOP_K) -> tuple[list[dict], list[dict]]:
    """回傳 (主要結果, 順著連結帶入的結果)。"""
    col = collection()
    data = col.get(include=["documents", "metadatas"])
    if not data["ids"]:
        return [], []
    docs = {i: {"id": i, "text": d, **m} for i, d, m in zip(data["ids"], data["documents"], data["metadatas"])}

    # 關鍵字：BM25，只保留有命中關鍵字的段落
    scores = BM25Okapi([tokenize(d) for d in data["documents"]]).get_scores(tokenize(question))
    bm25_rank = [i for s, i in sorted(zip(scores, data["ids"]), reverse=True)[:CANDIDATES] if s > 0]

    # 語意：向量
    n = min(CANDIDATES, len(data["ids"]))
    vec_rank = col.query(query_embeddings=embed([question]), n_results=n, include=[])["ids"][0]

    top = [docs[i] for i in rrf(bm25_rank, vec_rank)[:k]]
    return top, expand(top, docs)


def expand(top: list[dict], docs: dict[str, dict]) -> list[dict]:
    """知識圖譜擴展：把主要結果相連筆記的段落多帶一層進來。"""
    links = load_links()
    top_ids = {d["id"] for d in top}
    neighbors: list[str] = []  # 依主要結果的排名順序，排名越前的鄰居越優先
    for d in top[:EXPAND_FROM]:
        for name in sorted(links.get(Path(d["path"]).stem, ())):
            if name not in neighbors:
                neighbors.append(name)
    extra = [d for d in docs.values() if Path(d["path"]).stem in neighbors and d["id"] not in top_ids]
    extra.sort(key=lambda d: neighbors.index(Path(d["path"]).stem))
    return extra[:MAX_EXPAND]