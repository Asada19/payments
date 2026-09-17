from __future__ import annotations

from dishka import AsyncContainer, Provider, make_async_container
from faststream.rabbit import RabbitBroker

from app.core.broker import ApiBrokerProvider, WorkerBrokerProvider
from app.core.config import ConfigProvider, Settings
from app.core.db import DbProvider


def get_api_providers(settings: Settings) -> list[Provider]:
    return [ConfigProvider(settings), DbProvider(), ApiBrokerProvider()]


def get_worker_providers(settings: Settings) -> list[Provider]:
    return [ConfigProvider(settings), DbProvider(), WorkerBrokerProvider()]


def build_api_container(settings: Settings) -> AsyncContainer:
    return make_async_container(*get_api_providers(settings))


def build_worker_container(settings: Settings, broker: RabbitBroker) -> AsyncContainer:
    return make_async_container(
        *get_worker_providers(settings),
        context={RabbitBroker: broker},
    )
