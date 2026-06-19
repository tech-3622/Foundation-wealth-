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

        dep_cols = [row[1] for row in conn.execute(_sql_text("PRAGMA table_info(deposits)")).fetchall()]
        if 'direct_deposit' not in dep_cols:
            conn.execute(_sql_text("ALTER TABLE deposits ADD COLUMN direct_deposit BOOLEAN DEFAULT 0"))
        if 'receipt_path' not in dep_cols:
            conn.execute(_sql_text("ALTER TABLE deposits ADD COLUMN receipt_path VARCHAR"))
        table_names = [row[0] for row in conn.execute(_sql_text("SELECT name FROM sqlite_master WHERE type='table'")).fetchall()]
        if 'withdrawals' not in table_names:
            conn.execute(_sql_text("""
                CREATE TABLE IF NOT EXISTS withdrawals (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    amount FLOAT NOT NULL,
                    currency VARCHAR NOT NULL,
                    wallet_address VARCHAR NOT NULL,
                    network VARCHAR,
                    status VARCHAR DEFAULT 'pending',
                    receipt_path VARCHAR,
                    admin_id INTEGER,
                    admin_note VARCHAR,
                    created_at TIMESTAMP,
                    reviewed_at TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES users(id),
                    FOREIGN KEY (admin_id) REFERENCES users(id)
                )
            """))
        conn.commit()
    except Exception:
        pass
    finally:
        conn.close()
