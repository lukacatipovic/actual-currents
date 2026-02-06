"""
Actual Currents API - Main application entry point
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pathlib import Path
from app.api import currents

app = FastAPI(
    title="Actual Currents API",
    description="Real-time tidal current predictions for the Western North Atlantic",
    version="0.1.0"
)

# CORS middleware for frontend access
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Update with specific origins in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include API routers
app.include_router(currents.router, prefix="/api/v1", tags=["currents"])

# Serve frontend static files
frontend_path = Path(__file__).parent.parent.parent / "frontend"
if frontend_path.exists():
    app.mount("/", StaticFiles(directory=str(frontend_path), html=True), name="frontend")


@app.get("/")
async def root():
    """Health check endpoint"""
    return {
        "status": "online",
        "service": "Actual Currents API",
        "version": "0.1.0"
    }


@app.get("/health")
async def health():
    """Detailed health check"""
    return {
        "status": "healthy",
        "data_source": "S3",
        "zarr_path": "s3://actual-currents-data/adcirc54.zarr"
    }
