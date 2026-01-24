from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
import sys
from pathlib import Path

# Add parent directory to path for shared package
sys.path.insert(0, str(Path(__file__).parent.parent))

from api import characters, worlds, user, chat
from api.image_gen.routes.generate import router as image_router
from api.create_character.cc_routes import router as create_character_router

app = FastAPI(title="AI RP Bot WebApp")

# Include API routers
app.include_router(characters.router)
app.include_router(worlds.router)
app.include_router(user.router)
app.include_router(chat.router)
app.include_router(image_router)
app.include_router(create_character_router)

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
