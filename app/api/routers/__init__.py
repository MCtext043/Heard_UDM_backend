from fastapi import APIRouter

from app.api.routers import assistant, auth, catalog, events, favorites, uploads, users

api_router = APIRouter()
api_router.include_router(auth.router, prefix="/auth", tags=["auth"])
api_router.include_router(users.router, prefix="/users", tags=["users"])
api_router.include_router(favorites.router, prefix="/users", tags=["favorites"])
api_router.include_router(catalog.router, tags=["catalog"])
api_router.include_router(events.router, prefix="/events", tags=["events"])
api_router.include_router(uploads.router, tags=["uploads"])
api_router.include_router(assistant.router, prefix="/assistant", tags=["assistant"])
