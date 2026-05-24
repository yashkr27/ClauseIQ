from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(title="ClauseIQ API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Routers will be registered here as layers are built
# from .routes import extract, chunk, compare, score
# app.include_router(extract.router, prefix="/api")

@app.get("/health")
def health():
    return {"status": "ok"}
