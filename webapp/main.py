from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from starlette.middleware.sessions import SessionMiddleware
import sys
from pathlib import Path
import os

# Add parent directory to path for shared package
sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent))

from api import characters, worlds, user, chat
from api.image_gen.routes.generate import router as image_router
from api.create_character.cc_routes import router as create_character_router
from admin.router import router as admin_router
from shared.database import get_session
from shared.database.exceptions import (
    EntityNotFoundError,
    ValidationError,
    InsufficientBalanceError
)
from shared.services.prompt_service import init_prompt_cache

app = FastAPI(title="AI RP Bot WebApp")

SECRET_KEY = os.getenv("SECRET_KEY")
app.add_middleware(SessionMiddleware, secret_key=SECRET_KEY)


@app.exception_handler(EntityNotFoundError)
async def handle_not_found(request, exc: EntityNotFoundError):
    return JSONResponse(
        status_code=404,
        content={
            "error": "not_found",
            "message": exc.message,
            "code": f"{exc.entity_type.upper()}_NOT_FOUND"
        }
    )


@app.exception_handler(ValidationError)
async def handle_validation(request, exc: ValidationError):
    return JSONResponse(
        status_code=422,
        content={
            "error": "validation_error",
            "message": exc.message,
            "field": exc.field,
            "code": "VALIDATION_ERROR"
        }
    )


@app.exception_handler(InsufficientBalanceError)
async def handle_balance(request, exc: InsufficientBalanceError):
    return JSONResponse(
        status_code=400,
        content={
            "error": "insufficient_balance",
            "message": exc.message,
            "current_balance": exc.current,
            "required": exc.required,
            "code": "INSUFFICIENT_BALANCE"
        }
    )


@app.on_event("startup")
async def startup_event():
    import logging
    try:
        async with get_session() as db:
            await init_prompt_cache(db)
    except Exception as e:
        logging.error(f"Failed to initialize prompt cache: {e}")
        logging.warning("Application will use default prompts")

# Include API routers
app.include_router(characters.router)
app.include_router(worlds.router)
app.include_router(user.router)
app.include_router(chat.router)
app.include_router(image_router)
app.include_router(create_character_router)
app.include_router(admin_router)

# Mount static files
app.mount("/static", StaticFiles(directory="static"), name="static")
app.mount("/content", StaticFiles(directory="/app/content"), name="content")


@app.get("/")
async def root():
    """Serve index.html"""
    return FileResponse("static/index.html")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8080)
