import os
import logging
from pathlib import Path
from dotenv import load_dotenv

dotenv_path = Path(__file__).resolve().parent.parent.parent / ".env"
load_dotenv(dotenv_path=dotenv_path)


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(name)-24s | %(levelname)-5s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("plum")


class Settings:
    db_host: str = os.getenv("DB_HOST")
    db_port: int = int(os.getenv("DB_PORT"))
    db_name: str = os.getenv("DB_NAME")
    db_user: str = os.getenv("DB_USER")
    db_password: str = os.getenv("DB_PASSWORD")
    groq_api_key: str = os.getenv("GROQ_API_KEY", "")
    groq_model: str = os.getenv("GROQ_MODEL", "llama3-70b-8192")
    database_url: str | None = os.getenv("DATABASE_URL")
    langfuse_secret_key: str = os.getenv("LANGFUSE_SECRET_KEY")
    langfuse_public_key: str = os.getenv("LANGFUSE_PUBLIC_KEY")
    langfuse_base_url: str = os.getenv("LANGFUSE_BASE_URL", "https://cloud.langfuse.com")

    @property
    def db_url(self) -> str:
        if self.database_url:
            return self.database_url
        return (
            f"postgresql+asyncpg://{self.db_user}:{self.db_password}"
            f"@{self.db_host}:{self.db_port}/{self.db_name}"
        )


settings = Settings()
