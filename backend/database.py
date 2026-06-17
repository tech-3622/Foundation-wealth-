from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, DeclarativeBase
import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATABASE_URL = f"sqlite:///{os.path.join(BASE_DIR, 'foundation.db')}"

engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    Base.metadata.create_all(bind=engine)
    # Migrate: add columns if missing (SQLite)
    from sqlalchemy import text as _sql_text
    conn = engine.connect()
    try:
        cols = [row[1] for row in conn.execute(_sql_text("PRAGMA table_info(users)")).fetchall()]
        if 'profile_photo_path' not in cols:
            conn.execute(_sql_text("ALTER TABLE users ADD COLUMN profile_photo_path VARCHAR"))
        if 'notification_prefs' not in cols:
            conn.execute(_sql_text("ALTER TABLE users ADD COLUMN notification_prefs TEXT DEFAULT '{}'"))
        conn.commit()
    except Exception:
        pass
    finally:
        conn.close()
