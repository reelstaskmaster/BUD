from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    telegram_bot_token: str
    openai_api_key: str = ""
    gemini_api_key: str = ""
    openrouter_api_key: str = ""
    database_url: str = "postgresql+asyncpg://telegpt:telegpt@localhost:5433/telegpt"

    ai_chain: str = "gemini,openrouter,openai"
    gemini_chat_model: str = "gemini-3.8-flash"
    openrouter_chat_model: str = "openrouter/free"

    chat_model: str = "gpt-4.1"
    extract_model: str = "gpt-4.1-mini"
    embedding_model: str = "text-embedding-3-small"
    stt_model: str = "whisper-1"
    image_model: str = "gpt-image-1"

    recent_messages: int = Field(default=16, ge=1, le=200)
    fact_top_k: int = Field(default=10, ge=1, le=100)
    fact_all_threshold: int = Field(default=30, ge=0, le=1000)
    summarize_every: int = Field(default=20, ge=1, le=1000)
    coalesce_debounce_ms: int = Field(default=700, ge=0, le=60_000)
    embedding_dims: int = Field(default=1536, gt=0, le=8192)

    @property
    def coalesce_debounce_s(self) -> float:
        return self.coalesce_debounce_ms / 1000.0

    @property
    def ai_providers(self) -> list[str]:
        return [item.strip().lower() for item in self.ai_chain.split(",") if item.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
