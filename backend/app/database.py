import os

from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

load_dotenv()

DATABASE_URL = os.environ.get(
    "DATABASE_URL", "postgresql+psycopg://user:password@localhost:5432/quorum"
)

# Railway's (and Heroku's) provisioned Postgres plugin injects DATABASE_URL as
# "postgres://..." or "postgresql://..." with no driver specified; SQLAlchemy
# needs the +psycopg dialect suffix to pick the driver we actually installed
# (psycopg 3 - see requirements.txt; psycopg2-binary's build fails on Railway's
# Nixpacks image, which has no libpq-dev to compile it against).
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql+psycopg://", 1)
elif DATABASE_URL.startswith("postgresql://") and "+psycopg" not in DATABASE_URL.split("://", 1)[0]:
    DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgresql+psycopg://", 1)

engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=True, bind=engine)


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
