from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from webapp.api.health import router as health_router
from webapp.api import characters, worlds, user, chat
from webapp.api.image_gen.routes.generate import router as image_router

app = FastAPI(title="AI RP Bot WebApp")

app.include_router(characters.router)
app.include_router(worlds.router)
app.include_router(user.router)
app.include_router(chat.router)
app.include_router(image_router)
app.include_router(health_router)

base_dir = Path(__file__).resolve().parent
static_dir = base_dir / "static"

app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")
app.mount("/content", StaticFiles(directory="/app/content"), name="content")

@app.get("/")
async def root():
    """Serve index.html"""
    return FileResponse(static_dir / "index.html")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8080)