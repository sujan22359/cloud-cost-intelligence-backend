import logging
from datetime import timedelta
from typing import Any

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, EmailStr, Field

from app.config import get_settings
from app.core.security import create_access_token

logger = logging.getLogger(__name__)
settings = get_settings()

router = APIRouter(tags=["Authentication"])


class LoginRequest(BaseModel):
    """Payload for login authentication."""

    email: str = Field(..., example="admin@company.com", description="Company email address")
    password: str = Field(..., example="StrongPassword123", description="Company account password")


class LoginResponse(BaseModel):
    """Successful login response containing access token."""

    success: bool = True
    access_token: str
    token_type: str = "Bearer"
    expires_in: int = 21600
    email: str


@router.post("/login", response_model=LoginResponse, summary="Authenticate company account")
def login(payload: LoginRequest) -> dict[str, Any]:
    """Validate company credentials and issue a 24-hour JWT Bearer token."""
    input_email = payload.email.strip().lower()
    expected_email = settings.login_email.strip().lower()

    if input_email != expected_email or payload.password != settings.login_password:
        logger.warning("Failed login attempt for email: %s", payload.email)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    expires_delta = timedelta(hours=settings.jwt_expire_hours)
    token = create_access_token(data={"email": expected_email}, expires_delta=expires_delta)

    expires_seconds = int(expires_delta.total_seconds())

    logger.info("Successful login for user: %s", expected_email)
    return {
        "success": True,
        "access_token": token,
        "token_type": "Bearer",
        "expires_in": expires_seconds,
        "email": expected_email,
    }
