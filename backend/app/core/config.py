import os
import platform
import sys
from typing import List, Any
from pathlib import Path

# Prevent Windows Python 3.12 multiprocessing WMI COM query hang on SQLAlchemy/platform import
if sys.platform == "win32":
    try:
        platform.win32_ver = lambda release="", version="", csd="", ptype="": ("10", "10.0.19041", "", "Multiprocessor Free")
    except Exception:
        pass

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Base directory anchored to project root
BASE_DIR = Path(__file__).resolve().parent.parent.parent


class Settings(BaseSettings):
    PROJECT_NAME: str = "DiaDoc AI — Clinical Multimodal Intelligence Platform"
    API_V1_STR: str = "/api/v1"
    DEBUG: bool = True

    # CORS Allowed Origins (the Flutter mobile app is native and needs no CORS;
    # these remain for Swagger / local web tooling)
    CORS_ORIGINS: List[str] = [
        "http://localhost:80",
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ]

    @field_validator("CORS_ORIGINS", mode="before")
    @classmethod
    def parse_cors_origins(cls, v: Any) -> List[str]:
        if isinstance(v, str):
            v = v.strip()
            if v.startswith("[") and v.endswith("]"):
                try:
                    import json
                    return json.loads(v)
                except Exception:
                    pass
            return [origin.strip() for origin in v.split(",") if origin.strip()]
        elif isinstance(v, (list, tuple)):
            return [str(origin).strip() for origin in v if str(origin).strip()]
        return v

    # JWT authentication — set JWT_SECRET_KEY in .env for any non-debug deployment.
    # When empty and DEBUG=True an insecure development key is used.
    JWT_SECRET_KEY: str = ""
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60
    REFRESH_TOKEN_EXPIRE_DAYS: int = 30

    # Gemini model used for Vision AI meal analysis
    GEMINI_VISION_MODEL: str = "gemini-3.5-flash-lite"
    VISION_MAX_UPLOAD_MB: int = 8

    # Database — SQLite for local dev; swap to PostgreSQL URL in .env for production
    DATABASE_URL: str = f"sqlite:///{BASE_DIR / 'diabetes_assistant.db'}"

    # Google Gemini API — MUST be set in .env, never hardcode here
    GEMINI_API_KEY: str = ""

    # LLM Provider: "gemini" (default) or "ollama"
    LLM_PROVIDER: str = "gemini"
    OLLAMA_BASE_URL: str = "http://127.0.0.1:11434"
    OLLAMA_MODEL: str = "gpt-oss:120b-cloud"
    OLLAMA_FALLBACK_TO_GEMINI: bool = True
    OLLAMA_SHOW_THINKING: bool = False

    # ColPali / Byaldi vector index
    COLPALI_MODEL_NAME: str = "vidore/colpali-v1.2"
    INDEX_STORE_PATH: str = str(BASE_DIR / "byaldi_index")

    # Optional Qdrant vector database (disabled by default, uses Byaldi local index)
    QDRANT_HOST: str = "localhost"
    QDRANT_PORT: int = 6333
    USE_QDRANT: bool = False

    # File storage paths
    PAPERS_DIR: str = str(BASE_DIR / "data" / "papers")
    RENDERED_PAGES_DIR: str = str(BASE_DIR / "rendered_pages")

    model_config = SettingsConfigDict(
        env_file=[str(BASE_DIR / ".env"), ".env"],
        env_file_encoding="utf-8",
        extra="ignore",
    )


settings = Settings()
