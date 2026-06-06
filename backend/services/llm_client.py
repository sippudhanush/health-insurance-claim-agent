import json
import logging
from openai import AsyncOpenAI
from core.config import settings

logger = logging.getLogger("plum.llm")

OPENAI_BASE_URL = "https://api.openai.com/v1"

_client: AsyncOpenAI | None = None


def get_client() -> AsyncOpenAI:
    global _client
    if _client is None:
        _client = AsyncOpenAI(
            api_key=settings.groq_api_key,
            base_url=OPENAI_BASE_URL,
        )
    return _client


async def extract_json(prompt: str, content: str, model: str | None = None, max_tokens: int = 4000) -> dict:
    client = get_client()
    messages = [
        {"role": "system", "content": prompt},
        {"role": "user", "content": content},
    ]
    resp = await client.chat.completions.create(
        model=model or "gpt-4o-mini",
        messages=messages,
        temperature=0.1,
        max_tokens=max_tokens,
    )
    raw = resp.choices[0].message.content or ""
    raw = raw.strip()
    if raw.startswith("```"):
        lines = raw.split("\n")
        raw = "\n".join(lines[1:-1])
    return json.loads(raw)
