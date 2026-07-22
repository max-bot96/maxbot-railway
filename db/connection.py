import os
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from db.models import Base


DATABASE_URL = os.getenv("DATABASE_URL", "")
_ASYNC_DSN = None


def _build_async_dsn():
    global _ASYNC_DSN
    if _ASYNC_DSN:
        return _ASYNC_DSN
    if not DATABASE_URL:
        return None
    dsn = DATABASE_URL.replace("postgresql://", "postgresql+asyncpg://")
    dsn = dsn.replace("postgres://", "postgresql+asyncpg://")
    _ASYNC_DSN = dsn
    return _ASYNC_DSN


engine = None
async_session = None


async def init_db():
    global engine, async_session
    dsn = _build_async_dsn()
    if not dsn:
        print("[DB] ⚠️ DATABASE_URL not set — skipping DB init")
        return
    engine = create_async_engine(dsn, pool_size=10, max_overflow=20, pool_pre_ping=True)
    async_session = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    print("[DB] ✅ Tables created / verified")


async def get_session() -> AsyncSession:
    if async_session is None:
        raise RuntimeError("DB not initialized. Call init_db() first.")
    return async_session()


async def close_db():
    global engine
    if engine:
        await engine.dispose()
        print("[DB] Connection pool closed")
