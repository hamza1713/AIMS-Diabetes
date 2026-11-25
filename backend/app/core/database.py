from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker, declarative_base
from app.core.config import settings

# Engine setup
engine = create_engine(
    settings.DATABASE_URL,
    connect_args={"check_same_thread": False} if "sqlite" in settings.DATABASE_URL else {}
)

if "sqlite" in settings.DATABASE_URL:
    @event.listens_for(engine, "connect")
    def set_sqlite_pragma(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL;")
        cursor.execute("PRAGMA synchronous=NORMAL;")
        cursor.close()

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()

# Additive column migrations for tables that pre-date the column.
# New *tables* are created by Base.metadata.create_all (app/main.py), which never
# drops or alters existing tables, so data in diabetes_assistant.db is preserved.
ADDITIVE_COLUMNS = {
    "research_papers": [("file_hash", "VARCHAR(64)")],
    "glucose_logs": [("context", "VARCHAR")],
    "meal_logs": [
        ("name", "VARCHAR"),
        ("calories", "FLOAT"),
        ("protein_g", "FLOAT"),
        ("fat_g", "FLOAT"),
    ],
}


def run_migrations(bind=None):
    """Safely apply additive schema changes (ADD COLUMN) to an existing database. Idempotent."""
    from sqlalchemy import inspect

    bind = bind or engine
    try:
        with bind.connect() as conn:
            inspector = inspect(conn)
            existing_tables = set(inspector.get_table_names())
            for table, columns in ADDITIVE_COLUMNS.items():
                if table not in existing_tables:
                    continue  # create_all will build it with every column
                present = {c["name"] for c in inspector.get_columns(table)}
                for name, ddl in columns:
                    if name not in present:
                        conn.exec_driver_sql(f"ALTER TABLE {table} ADD COLUMN {name} {ddl};")
            conn.commit()
    except Exception as exc:  # never block startup on a migration hiccup
        import logging
        logging.getLogger(__name__).warning("Schema migration skipped: %s", exc)

run_migrations()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

