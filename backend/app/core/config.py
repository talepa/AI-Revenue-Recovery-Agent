from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    app_name: str = "ai-revenue-recovery-agent"
    env: str = "local"
    database_url: str = (
        "postgresql+asyncpg://recovery_user:recovery_pass@localhost:5432/recovery_db"
    )


settings = Settings()
