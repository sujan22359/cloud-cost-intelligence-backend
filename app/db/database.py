import logging

from sqlalchemy import create_engine, text
from sqlalchemy.orm import declarative_base, sessionmaker

from app.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

POSTGRES_URL = (
    f"postgresql+psycopg://{settings.postgres_user}:{settings.postgres_password}"
    f"@{settings.postgres_host}:{settings.postgres_port}/{settings.postgres_db}"
)

engine = create_engine(
    POSTGRES_URL,
    pool_size=settings.db_pool_size,
    max_overflow=settings.db_max_overflow,
    pool_timeout=settings.db_pool_timeout,
    pool_pre_ping=True,
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def run_migrations(target_engine) -> None:
    """Migrate PostgreSQL database table schemas to modern versions."""
    if target_engine.dialect.name != "postgresql":
        logger.info("Not running on PostgreSQL. Skipping database migrations.")
        return

    logger.info("Running database migrations...")
    try:
        with target_engine.begin() as conn:
            # 1. Create account_master table if not exists
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS account_master (
                    account_id VARCHAR(50) PRIMARY KEY,
                    account_name VARCHAR(255) NOT NULL,
                    product VARCHAR(255),
                    team VARCHAR(255),
                    environment VARCHAR(50) NOT NULL,
                    developer_type VARCHAR(50),
                    created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT now(),
                    updated_at TIMESTAMP WITHOUT TIME ZONE DEFAULT now()
                )
            """))

            # 2. Create import_history table if not exists
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS import_history (
                    id SERIAL PRIMARY KEY,
                    file_name VARCHAR(255) NOT NULL,
                    billing_period VARCHAR(7) NOT NULL,
                    rows_read INTEGER NOT NULL DEFAULT 0,
                    rows_inserted INTEGER NOT NULL DEFAULT 0,
                    rows_updated INTEGER NOT NULL DEFAULT 0,
                    duplicates INTEGER NOT NULL DEFAULT 0,
                    started_at TIMESTAMP WITHOUT TIME ZONE NOT NULL,
                    completed_at TIMESTAMP WITHOUT TIME ZONE NOT NULL,
                    status VARCHAR(50) NOT NULL
                )
            """))

            # 3. Add columns to service_costs table
            columns = [
                ("account_id", "VARCHAR(50)"),
                ("account_name", "VARCHAR(255)"),
                ("product", "VARCHAR(255)"),
                ("team", "VARCHAR(255)"),
                ("environment", "VARCHAR(50)"),
                ("developer_type", "VARCHAR(50)"),
                ("raw_service_name", "VARCHAR(255)"),
                ("business_service_name", "VARCHAR(255)"),
                ("region", "VARCHAR(100)"),
            ]
            for col_name, col_type in columns:
                conn.execute(text(f"""
                    ALTER TABLE service_costs 
                    ADD COLUMN IF NOT EXISTS {col_name} {col_type}
                """))

            # 4. Migrate and drop obsolete service_name column if exists
            col_check = conn.execute(text("""
                SELECT column_name 
                FROM information_schema.columns 
                WHERE table_name='service_costs' AND column_name='service_name'
            """)).fetchone()

            if col_check:
                logger.info("Migrating existing service_name data in PostgreSQL...")
                conn.execute(text("""
                    UPDATE service_costs 
                    SET raw_service_name = service_name, 
                        business_service_name = service_name
                    WHERE raw_service_name IS NULL AND service_name IS NOT NULL
                """))
                conn.execute(text("""
                    ALTER TABLE service_costs DROP COLUMN IF EXISTS service_name
                """))
                logger.info("Dropped obsolete service_name column from PostgreSQL.")

            # 5. Clean up old unique index and unique constraint
            conn.execute(text("DROP INDEX IF EXISTS uq_service_costs_billing_account_service_region"))
            conn.execute(text("ALTER TABLE service_costs DROP CONSTRAINT IF EXISTS uq_service_costs_billing_account_service_region"))

            # 6. Clean up any existing duplicate records before applying index to prevent violations
            conn.execute(text("""
                DELETE FROM service_costs a USING service_costs b
                WHERE a.id < b.id 
                  AND a.billing_period = b.billing_period 
                  AND COALESCE(a.account_id, '') = COALESCE(b.account_id, '') 
                  AND COALESCE(a.raw_service_name, '') = COALESCE(b.raw_service_name, '') 
                  AND COALESCE(a.region, '') = COALESCE(b.region, '')
                  AND COALESCE(a.currency, '') = COALESCE(b.currency, '')
            """))

            # 7. Create unique index on (billing_period, account_id, raw_service_name, region, currency)
            conn.execute(text("""
                CREATE UNIQUE INDEX IF NOT EXISTS uq_service_costs_billing_account_service_region_currency
                ON service_costs (billing_period, account_id, raw_service_name, region, currency)
            """))

            # 8. Create organization_knowledge table if not exists
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS organization_knowledge (
                    id SERIAL PRIMARY KEY,
                    title VARCHAR(255) NOT NULL,
                    category VARCHAR(100) NOT NULL,
                    month VARCHAR(50),
                    tags VARCHAR(255),
                    content TEXT NOT NULL,
                    created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT now() NOT NULL,
                    updated_at TIMESTAMP WITHOUT TIME ZONE DEFAULT now() NOT NULL
                )
            """))
            
        logger.info("Database migrations completed successfully.")
    except Exception as exc:
        logger.error("Failed to run database migrations: %s", exc)
        raise


def initialize_database() -> None:
    """Create database tables on startup."""
    logger.info("Connecting to PostgreSQL...")
    try:
        from app.db import models  # noqa: F401

        Base.metadata.create_all(bind=engine)
        logger.info("PostgreSQL base metadata tables checked/created.")
        run_migrations(engine)
        logger.info("PostgreSQL connected successfully.")
        logger.info("Database connection established")
    except Exception:
        logger.exception("Failed to connect to PostgreSQL")
        raise
