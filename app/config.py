from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    telegram_bot_token: str
    openai_api_key: str
    database_url: str = "postgresql+asyncpg://telegpt:telegpt@localhost:5433/telegpt"

    chat_model: str = "gpt-4.1"
    extract_model: str = "gpt-4.1-mini"
    embedding_model: str = "text-embedding-3-small"
    stt_model: str = "whisper-1"
    image_model: str = "gpt-image-1"

    recent_messages: int = 16
    fact_top_k: int = 10
    fact_all_threshold: int = 30
    summarize_every: int = 20
    coalesce_debounce_ms: int = 700
    embedding_dims: int = 1536

    @property
    def coalesce_debounce_s(self) -> float:
        return self.coalesce_debounce_ms / 1000.0


@lru_cache
def get_settings() -> Settings:
    return Settings()
