import hashlib
import os
from pathlib import Path

# src/kb/config.py 往上兩層就是專案根目錄
ROOT = Path(__file__).resolve().parents[2]
# 可以用環境變數 KB_VAULT 指定其他 vault 資料夾
VAULT = Path(os.environ.get("KB_VAULT", ROOT / "vault"))
DATA = ROOT / "data"


def chroma_dir(vault: Path) -> Path:
    """每個 vault 各自的 Chroma 資料夾，切換 vault 時索引不會混在一起。"""
    digest = hashlib.sha1(str(vault.resolve()).encode()).hexdigest()[:8]
    return DATA / "chroma" / f"{vault.name}-{digest}"


LLM_BASE_URL = "http://localhost:1234/v1"
CHAT_MODEL = "google/gemma-4-e4b"
EMBED_MODEL = "text-embedding-bge-m3"

MAX_CHUNK_CHARS = 500  # 每塊最多幾個字
TOP_K = 5              # 最後交給 LLM 幾塊

