from typing import Annotated

from fastapi import Header, HTTPException, status

from app.config import settings


def require_admin_key(x_admin_key: Annotated[str | None, Header()] = None) -> None:
    expected = (settings.admin_api_key or "").strip()
    if not expected:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin content API is disabled (set ADMIN_API_KEY)",
        )
    if not x_admin_key or x_admin_key.strip() != expected:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid admin key")
