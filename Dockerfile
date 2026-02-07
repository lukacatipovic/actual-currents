FROM python:3.11-slim

# Install system dependencies for numpy, scipy, netCDF4
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    g++ \
    libhdf5-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy backend requirements and install dependencies first (cache layer)
COPY backend/requirements.txt backend/requirements.txt
COPY backend/lib/ttide_py-master backend/lib/ttide_py-master

# Install ttide from local copy (non-editable for container)
RUN pip install --no-cache-dir backend/lib/ttide_py-master

# Install remaining Python dependencies (skip the -e ttide line)
RUN grep -v "ttide_py-master" backend/requirements.txt | pip install --no-cache-dir -r /dev/stdin

# Copy backend application code
COPY backend/app backend/app

# Copy frontend static files
COPY frontend frontend

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')" || exit 1

WORKDIR /app/backend

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
