from pydantic_settings import BaseSettings, SettingsConfigDict
from functools import lru_cache


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    APP_NAME: str = "KBS - Knowledge Based System"
    DATABASE_URL: str = "postgresql+asyncpg://ims:ims@localhost:5432/kbs_db"
    DATABASE_URL_SYNC: str = "postgresql+psycopg2://ims:ims@localhost:5432/kbs_db"
    SECRET_KEY: str = "WCVSbAkpRpXT2vCYgY3BoyIfVqtYmv-eyONi3wA_6vQpoeeZQ7Vo7dU_yfCJXQf0DymtJm-ztbZlYGkeQY-XNg"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24

    # LLM configuration (OpenAI-compatible API)
    LLM_API_KEY: str = ""
    LLM_SYSTEM_PROMPT_PATH: str = "prompts/question_generator.system.md"

    # Avoid repeating recently answered items across CAT sessions for the same user/subject.
    # Set to 0 to disable cross-session repeat avoidance.
    CAT_RECENT_QUESTION_WINDOW: int = 120

@lru_cache()
def get_settings():
    return Settings()
