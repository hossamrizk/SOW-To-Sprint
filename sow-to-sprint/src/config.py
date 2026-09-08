from functools import lru_cache

from dotenv import find_dotenv
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    openai_api_key: str
    openai_model: str = "gpt-4o-mini"

    trello_api_key: str = ""
    trello_api_token: str = ""

    max_input_chars: int = 60_000

    model_config = SettingsConfigDict(
        env_file=find_dotenv(usecwd=True) or ".env",
        case_sensitive=False,
        extra="ignore",
    )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Cached accessor — avoids re-parsing `.env` on every import."""
    return Settings()  # type: ignore[call-arg]
