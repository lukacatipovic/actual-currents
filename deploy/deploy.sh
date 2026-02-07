#!/bin/bash
# Deploy/Update Actual Currents on EC2
# Run from the project root: ./deploy/deploy.sh
#
# This script pulls latest code, rebuilds the Docker image, and restarts the container.

set -euo pipefail

# Ensure we're in the project root
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
cd "$PROJECT_DIR"

echo "=== Deploying Actual Currents ==="

# Pull latest code
echo "Pulling latest code from GitHub..."
git pull

# Build Docker image
echo "Building Docker image..."
docker compose build

# Stop existing container (if running)
echo "Stopping existing container..."
docker compose down || true

# Start new container
echo "Starting container..."
docker compose up -d

# Wait for health check
echo "Waiting for app to start (loading ~2GB dataset from S3)..."
echo "This may take 30-60 seconds on first launch."
for i in $(seq 1 60); do
    if curl -sf http://localhost/health > /dev/null 2>&1; then
        echo ""
        echo "=== Deployment Successful ==="
        # Get public IP
        PUBLIC_IP=$(curl -sf http://169.254.169.254/latest/meta-data/public-ipv4 2>/dev/null || echo "unknown")
        echo "App is running at: http://${PUBLIC_IP}"
        echo ""
        echo "Useful commands:"
        echo "  docker compose logs -f    # View logs"
        echo "  docker compose restart    # Restart"
        echo "  docker compose down       # Stop"
        exit 0
    fi
    printf "."
    sleep 5
done

echo ""
echo "WARNING: Health check did not pass within 5 minutes."
echo "Check logs: docker compose logs"
exit 1
