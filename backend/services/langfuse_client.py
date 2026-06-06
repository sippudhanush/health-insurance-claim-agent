from core.config import settings

try:
    from langfuse import Langfuse
    _langfuse = Langfuse(
        secret_key=settings.langfuse_secret_key,
        public_key=settings.langfuse_public_key,
        host=settings.langfuse_base_url,
    )
    _ = _langfuse.trace  # verify the method exists
except Exception:
    _langfuse = None

langfuse = _langfuse
