from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from .routes.analyse import router as analyse_router
from .routes.compare import router as compare_router
from ..scorer.knowledge import load_knowledge_nodes
import os


app = FastAPI(title="ClauseIQ API", version="1.0.0")


@app.on_event("startup")
async def seed_knowledge():
    """
    On startup, eagerly load knowledge nodes.
    - If Supabase is connected: reads from DB (no insert, seed.sql already ran).
    - If no DB: parses seed.sql into in-memory store via load_knowledge_nodes().
    Either way, nodes are warm in memory before the first request hits.
    """
    load_knowledge_nodes()


app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register API routers
app.include_router(analyse_router)
app.include_router(compare_router)


@app.get("/health")
def health():
    return {"status": "ok"}


# Serve frontend static files
_frontend_dir = os.path.join(os.path.dirname(__file__), '..', '..', '..', 'frontend')
if os.path.isdir(_frontend_dir):
    @app.get("/")
    async def serve_root():
        return FileResponse(os.path.join(_frontend_dir, 'index.html'))

    app.mount("/", StaticFiles(directory=_frontend_dir), name="frontend")

    #python -m uvicorn src.api.main:app --reload --port 8000