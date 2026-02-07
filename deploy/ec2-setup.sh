#!/bin/bash
# EC2 Initial Setup Script for Actual Currents
# Run this once on a fresh Amazon Linux 2023 EC2 instance
# Usage: bash ec2-setup.sh <GITHUB_REPO_URL>
#
# Example: bash ec2-setup.sh https://github.com/yourusername/actual-currents.git

set -euo pipefail

REPO_URL="${1:-}"

if [ -z "$REPO_URL" ]; then
    echo "Usage: bash ec2-setup.sh <GITHUB_REPO_URL>"
    echo "Example: bash ec2-setup.sh https://github.com/yourusername/actual-currents.git"
    exit 1
fi

echo "=== Actual Currents EC2 Setup ==="

# Update system
echo "Updating system packages..."
sudo dnf update -y

# Install Docker
echo "Installing Docker..."
sudo dnf install -y docker git
sudo systemctl start docker
sudo systemctl enable docker
sudo usermod -aG docker ec2-user

# Install Docker Compose plugin
echo "Installing Docker Compose..."
sudo mkdir -p /usr/local/lib/docker/cli-plugins
COMPOSE_VERSION=$(curl -s https://api.github.com/repos/docker/compose/releases/latest | grep '"tag_name"' | head -1 | cut -d'"' -f4)
sudo curl -SL "https://github.com/docker/compose/releases/download/${COMPOSE_VERSION}/docker-compose-linux-$(uname -m)" -o /usr/local/lib/docker/cli-plugins/docker-compose
sudo chmod +x /usr/local/lib/docker/cli-plugins/docker-compose

# Verify installations
echo "Docker version: $(docker --version)"
echo "Docker Compose version: $(docker compose version)"

# Clone repository
echo "Cloning repository..."
cd /home/ec2-user
git clone "$REPO_URL" actual-currents
cd actual-currents

echo ""
echo "=== Setup Complete ==="
echo ""
echo "IMPORTANT: Log out and back in for docker group to take effect:"
echo "  exit"
echo "  ssh ec2-user@<your-ec2-ip>"
echo ""
echo "Then deploy the app:"
echo "  cd ~/actual-currents"
echo "  ./deploy/deploy.sh"
echo ""
echo "Make sure your EC2 instance has:"
echo "  1. An IAM role with S3 read access to 'actual-currents-data' bucket"
echo "  2. Security Group allowing inbound port 80 (HTTP) and 22 (SSH)"
