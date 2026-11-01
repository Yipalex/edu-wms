"""全局配置：全部走环境变量（pydantic-settings）。

生产由 docker compose 注入 PG DSN；本地默认 sqlite 便于跑通。
"""
from functools import lru_cache
from typing import List

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # 数据库：默认 sqlite（本地），生产注入 postgresql+psycopg://...
    DATABASE_URL: str = "sqlite:///./wms.db"

    # JWT
    JWT_SECRET: str = "change-me-in-production"
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRE_MINUTES: int = 120          # access token 2h
    JWT_REFRESH_EXPIRE_DAYS: int = 7       # refresh token 7d

    # 上传目录（照片），相对路径基于运行目录
    UPLOAD_DIR: str = "./uploads"

    # 标签字体（容器内 Noto Sans CJK；macOS 本地可指向 Hiragino）
    LABEL_FONT_REGULAR: str = "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"
    LABEL_FONT_BOLD: str = "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc"

    # CORS，逗号分隔
    CORS_ORIGINS: str = "*"

    # admin 初始账号（首次 seed 用；上线后必须改密）
    ADMIN_INIT_USERNAME: str = "admin"
    ADMIN_INIT_PASSWORD: str = "Zexi@2026"

    # 启动时自动跑幂等 seed
    AUTO_SEED: bool = True

    # 上传大小上限（字节），默认 10MB
    UPLOAD_MAX_SIZE: int = 10 * 1024 * 1024

    @field_validator("CORS_ORIGINS")
    @classmethod
    def _strip_origins(cls, v: str) -> str:
        return v.strip()

    @property
    def cors_origin_list(self) -> List[str]:
        if self.CORS_ORIGINS == "*":
            return ["*"]
        return [o.strip() for o in self.CORS_ORIGINS.split(",") if o.strip()]

    @property
    def is_sqlite(self) -> bool:
        return self.DATABASE_URL.startswith("sqlite")


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
