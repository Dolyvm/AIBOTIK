from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
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
from shared.models import get_async_session
from shared.services.prompt_service import init_prompt_cache

app = FastAPI(title="AI RP Bot WebApp")

SECRET_KEY = os.getenv("SECRET_KEY")
app.add_middleware(SessionMiddleware, secret_key=SECRET_KEY)


@app.on_event("startup")
async def startup_event():
    import logging
    try:
        async for db in get_async_session():
            await init_prompt_cache(db)
            break
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
