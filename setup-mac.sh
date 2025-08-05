#!/bin/bash
# Mac-specific setup script for OpenSPP Deployment Manager

echo "🍎 Setting up OpenSPP Deployment Manager for macOS..."

# Check Docker Desktop
if ! docker info &> /dev/null; then
    echo "❌ Docker Desktop is not running. Please start Docker Desktop first."
    exit 1
fi

# Check if running on Apple Silicon
if [[ $(uname -m) == "arm64" ]]; then
    echo "✅ Running on Apple Silicon (M1/M2/M3)"
else
    echo "✅ Running on Intel Mac"
fi

# Use Mac-specific config
if [ ! -f config.yaml ]; then
    echo "📋 Using Mac-specific configuration..."
    cp config-mac.yaml config.yaml
fi

# Create .env from example
if [ ! -f .env ]; then
    cp .env.example .env
    # Update .env for Mac
    sed -i '' 's|/etc/nginx/sites-available|/usr/local/etc/nginx/servers|g' .env
    echo "✅ Created .env file with Mac paths"
fi

# Initialize database
echo "🗄️  Initializing database..."
python -m src.database init

# Create required directories
mkdir -p deployments logs

echo "✅ Setup complete!"
echo ""
echo "📝 Note: On Mac, deployments will be accessible via:"
echo "   - Odoo: http://localhost:18000 (port varies by deployment)"
echo "   - PGWeb: http://localhost:18081"
echo "   - Mailhog: http://localhost:18025"
echo ""
echo "🚀 To start the application, run: ./run.sh"