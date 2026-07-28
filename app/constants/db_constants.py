"""Database-related constants and connection pool defaults."""

DATABASE_URL_DEFAULT = "postgresql+psycopg://postgres:postgres123@localhost:5432/costdb"
POSTGRES_HOST_DEFAULT = "localhost"
POSTGRES_PORT_DEFAULT = 5432
POSTGRES_DB_DEFAULT = "costdb"
POSTGRES_USER_DEFAULT = "postgres"
POSTGRES_PASSWORD_DEFAULT = "postgres123"

DB_POOL_SIZE_DEFAULT = 10
DB_MAX_OVERFLOW_DEFAULT = 20
DB_POOL_TIMEOUT_DEFAULT = 30
BATCH_INSERT_SIZE_DEFAULT = 1000
