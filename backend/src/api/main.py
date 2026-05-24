from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from .routes.analyse import router as analyse_router
from .routes.compare import router as compare_router

app = FastAPI(title="ClauseIQ API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allow flexible origin for dev environment
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register routers
app.include_router(analyse_router)
app.include_router(compare_router)

@app.get("/health")
def health():
    return {"status": "ok"}
