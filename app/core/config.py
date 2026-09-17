from functools import cache

from dishka import Provider, Scope, provide
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    api_key: str = "local-development-key"
    database_url: str = "postgresql+asyncpg://payments:payments@localhost:5432/payments"
    rabbitmq_url: str = "amqp://guest:guest@localhost:5672/"
    outbox_poll_interval_seconds: float = 1.0
    outbox_batch_size: int = 50
    publish_timeout_seconds: float = 5.0
    webhook_timeout_seconds: float = 10.0
    consumer_prefetch_count: int = 10
    gateway_success_rate: float = 0.9
    gateway_min_delay_seconds: float = 2.0
    gateway_max_delay_seconds: float = 5.0


@cache
def get_settings() -> Settings:
    return Settings()


class ConfigProvider(Provider):
    scope = Scope.APP

    def __init__(self, settings: Settings) -> None:
        super().__init__()
        self._settings = settings

    @provide
    def get_settings(self) -> Settings:
        return self._settings
