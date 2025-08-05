#!/bin/bash
# ABOUTME: Startup script for OpenSPP Deployment Manager
# ABOUTME: Handles environment setup and launches the Streamlit application

set -e

echo "🚀 Starting OpenSPP Deployment Manager..."

# Check if .env exists
if [ ! -f .env ]; then
    echo "⚠️  No .env file found. Copying from .env.example..."
    cp .env.example .env
    echo "✅ Created .env file. Please edit it with your configuration."
fi

# Check if database exists
if [ ! -f deployments.db ]; then
    echo "📦 Initializing database..."
    python -m src.database init
fi

# Create required directories
mkdir -p deployments logs

# Check Docker
if ! command -v docker &> /dev/null; then
    echo "❌ Docker is not installed or not in PATH"
    exit 1
fi

# Check if Docker daemon is running
if ! docker info &> /dev/null; then
    echo "❌ Docker daemon is not running"
    exit 1
fi

echo "✅ All checks passed"
echo "🌐 Starting Streamlit server..."
echo "📍 Access the application at: http://localhost:8501"
echo ""

# Run with uv if available, otherwise use python
if command -v uv &> /dev/null; then
    uv run streamlit run app.py
else
    streamlit run app.py
fi