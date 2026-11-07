import json
from urllib.parse import urlparse

from openai import DefaultHttpxClient, OpenAI

from kb.config import CHAT_MODEL, EMBED_MODEL, LLM_BASE_URL

LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}

# LM Studio 不檢查 api_key，但 openai 套件規定一定要填。
# trust_env=False：不使用 HTTP_PROXY 等環境變數，以免筆記經過代理伺服器送出去
client = OpenAI(base_url=LLM_BASE_URL, api_key="lm-studio", http_client=DefaultHttpxClient(trust_env=False))


def is_local(base_url: str) -> bool:
    return urlparse(base_url).hostname in LOCAL_HOSTS


def allowed(chunks, base_url: str = LLM_BASE_URL):
    """私人內容只能送到本機；送往其他位址時，只留下可分享的段落。"""
    if is_local(base_url):
        return chunks
    return [c for c in chunks if not (c["private"] if isinstance(c, dict) else c.private)]


def embed(texts: list[str]) -> list[list[float]]:
    resp = client.embeddings.create(model=EMBED_MODEL, input=texts)
    return [d.embedding for d in resp.data]


def chat(system: str, user: str, model: str = CHAT_MODEL) -> str:
    resp = client.chat.completions.create(
        model=model,
        messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
    )
    # 會思考的模型有時只產生思考、沒有答案，content 會是 None
    return (resp.choices[0].message.content or "").strip()


def chat_json(system: str, user: str, schema: dict, model: str = CHAT_MODEL) -> dict:
    """要求模型照 JSON schema 回答（LM Studio 的 structured output）。只給 note、lint 用，內容都是私人的。"""
    if not is_local(str(client.base_url)):  # 檢查實際連線的位址，緊鄰送出的地方
        raise ValueError("私人內容只能送到本機的模型")
    resp = client.chat.completions.create(
        model=model,
        messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
        response_format={"type": "json_schema", "json_schema": {"name": "result", "schema": schema, "strict": True}},
        temperature=0.2,  # 修改清單要穩定，不需要創意；小模型溫度高時偶爾會換成別的語言
    )
    text = resp.choices[0].message.content or ""
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        raise ValueError(f"模型回傳的不是合法的 JSON：{text[:200]!r}") from None
    if not isinstance(data, dict):
        raise ValueError(f"模型回傳的格式不對：{text[:200]!r}")
    return data