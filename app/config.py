# app/config.py
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    duckdb_path: str = "app/stocks.duckdb"
    redis_host: str = "localhost"
    redis_port: int = 6379
    redis_db: int = 0
    cache_ttl_seconds: int = 60 * 10  # 10 minutes

    class Config:
        env_file = ".env"


settings = Settings()
