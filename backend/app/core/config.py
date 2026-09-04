from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    app_name: str = "ai-revenue-recovery-agent"
    env: str = "local"
    database_url: str = (
        "postgresql+asyncpg://recovery_user:recovery_pass@localhost:5432/recovery_db"
    )

    # LLM provider: if unset, diagnosis/intervention fall back to a deterministic
    # rule-based agent (see app/agents/llm_client.py) — no key required to run the app.
    openai_api_key: str | None = None
    llm_model: str = "gpt-4o-mini"

    # Event publishing: if unset, domain events are logged instead of
    # published (see app/events/) — no Kafka required to run the app.
    kafka_bootstrap_servers: str | None = None

    # Locking/idempotency: if unset, falls back to an in-process lock
    # (see app/core/locks.py) — no Redis required to run the app, but the
    # fallback only guards against races within this one process.
    redis_url: str | None = None


settings = Settings()
