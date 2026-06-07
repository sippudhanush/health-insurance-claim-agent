from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

_PATH = Path(__file__).resolve().parent.parent
load_dotenv(_PATH / ".env")

OPENAI_API_KEY: str | None = os.getenv("OPENAI_API_KEY")
CLAIM_AGENT_MODEL: str = os.getenv("CLAIM_AGENT_MODEL", "gpt-5.4-mini")
CLAIM_AGENT_LOG_LEVEL: str = os.getenv("CLAIM_AGENT_LOG_LEVEL", "INFO")
