#!/bin/bash
# Development server launcher for Actual Currents

echo "🌊 Starting Actual Currents Development Server"
echo "=============================================="
echo ""

# Activate virtual environment
source backend/tides/bin/activate

# Run FastAPI server
echo "Starting FastAPI server on http://localhost:8000"
echo "Frontend available at http://localhost:8000"
echo "API docs at http://localhost:8000/docs"
echo ""
echo "Press Ctrl+C to stop"
echo ""

cd backend && uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
