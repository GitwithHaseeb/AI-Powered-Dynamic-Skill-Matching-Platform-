import os
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_BACKEND_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(_BACKEND_ROOT / ".env")
load_dotenv()


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=_BACKEND_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    APP_NAME: str = "Skill Mapping Platform"
    APP_VERSION: str = "1.0.0"
    DEBUG: bool = os.getenv("DEBUG", "False").lower() == "true"

    HOST: str = os.getenv("HOST", "0.0.0.0")
    PORT: int = int(os.getenv("PORT", 8000))

    # Prefer MONGO_URI if set (SDS naming); else MONGODB_URL
    MONGO_URI: Optional[str] = Field(default=None, description="Primary Mongo connection string")
    MONGODB_URL: str = Field(default="mongodb://localhost:27017")
    MONGODB_DB_NAME: str = Field(default="skill_mapping")
    MONGODB_TLS_INSECURE: bool = Field(
        default=False,
        description="Set true only if TLS handshake fails (e.g. broken corporate proxy). Dev escape hatch.",
    )

    SECRET_KEY: str = os.getenv("SECRET_KEY", "your-secret-key-here-change-in-production")
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", str(60 * 24 * 7)))

    ML_MODEL_PATH: str = "./app/ml/model.pkl"
    SPACY_MODEL: str = "en_core_web_sm"
    SENTENCE_MODEL: str = "all-MiniLM-L6-v2"

    UPLOAD_DIR: str = "./uploads"
    MAX_FILE_SIZE: int = 10 * 1024 * 1024
    ALLOWED_EXTENSIONS: list = [".pdf", ".doc", ".docx", ".txt"]

    CORS_ORIGINS: list = [
        "http://localhost:3000",
        "http://localhost:5173",
        "http://localhost:5174",
        "http://localhost:5175",
        "http://localhost:5176",
        "http://localhost:5177",
        "http://localhost:5178",
        "http://127.0.0.1:5173",
        "http://127.0.0.1:5174",
        "http://127.0.0.1:5175",
        "http://127.0.0.1:5176",
        "http://127.0.0.1:5177",
        "http://127.0.0.1:5178",
        "http://127.0.0.1:3000",
        "https://yourdomain.com",
    ]

    @model_validator(mode="after")
    def _warn_tls(self):
        if self.MONGODB_TLS_INSECURE:
            print("WARNING: MONGODB_TLS_INSECURE=True — not for production.")
        return self

    @property
    def mongo_url(self) -> str:
        raw = (self.MONGO_URI or self.MONGODB_URL or "").strip()
        return raw or "mongodb://localhost:27017"


settings = Settings()
