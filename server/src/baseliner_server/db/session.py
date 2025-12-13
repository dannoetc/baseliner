from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from baseliner_server.core.config import settings

engine = create_engine(settings.database_url, future=True, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
