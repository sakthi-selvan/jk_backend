from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.core.config import settings

# Create database engine
# TCP keepalives + recycle so connections silently dropped by Neon / the network
# are detected quickly instead of hanging a request.
_CONNECT_ARGS = {
    "keepalives": 1,
    "keepalives_idle": 30,
    "keepalives_interval": 10,
    "keepalives_count": 3,
    "connect_timeout": 10,
}

engine = create_engine(
    settings.DATABASE_URL,
    pool_pre_ping=True,
    pool_size=10,
    max_overflow=20,
    pool_recycle=280,
    connect_args=_CONNECT_ARGS,
)

# PgBouncer-backed Neon URLs are right for normal application traffic. DDL and
# migrations need a direct connection because they can rely on session state.
schema_engine = engine
if settings.DATABASE_URL_UNPOOLED and settings.DATABASE_URL_UNPOOLED != settings.DATABASE_URL:
    schema_engine = create_engine(
        settings.DATABASE_URL_UNPOOLED,
        pool_pre_ping=True,
        pool_size=2,
        max_overflow=2,
        pool_recycle=280,
        connect_args=_CONNECT_ARGS,
    )

# Create session factory
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
