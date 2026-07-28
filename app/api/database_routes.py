import logging

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.db.database import SessionLocal

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/database", tags=["Database"])


@router.get("/health", summary="Database health")
async def database_health() -> dict[str, object]:
    """Check PostgreSQL connectivity and return server details."""
    logger.info("Database health checked")
    try:
        with SessionLocal() as session:
            version_row = session.execute(text("SELECT version()"))
            db_row = session.execute(text("SELECT current_database()"))
            server_version = version_row.scalar()
            database_name = db_row.scalar()
            logger.info("Server version: %s", server_version)
            logger.info("Current database: %s", database_name)
            return {
                "status": "connected",
                "database": "PostgreSQL",
                "server_version": server_version,
                "database_name": database_name,
            }
    except SQLAlchemyError as exc:
        logger.exception("Database health check failed")
        return JSONResponse(status_code=500, content={"status": "failed", "error": str(exc)})
