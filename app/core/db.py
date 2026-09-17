from __future__ import annotations

from collections.abc import AsyncIterable

from dishka import Provider, Scope, provide
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import Settings

SessionFactory = async_sessionmaker[AsyncSession]


class DbProvider(Provider):
    scope = Scope.APP

    @provide
    async def get_engine(self, cfg: Settings) -> AsyncIterable[AsyncEngine]:
        engine = create_async_engine(cfg.database_url, pool_pre_ping=True)
        try:
            yield engine
        finally:
            await engine.dispose()

    @provide
    def get_session_factory(self, engine: AsyncEngine) -> SessionFactory:
        return async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

    @provide(scope=Scope.REQUEST)
    async def get_session(self, factory: SessionFactory) -> AsyncIterable[AsyncSession]:
        async with factory() as session:
            yield session
