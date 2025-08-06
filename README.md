# OpenSPP Deployment Manager

A web-based tool to manage multiple OpenSPP Docker test deployments, allowing testers to easily deploy, configure, and manage OpenSPP instances with different versions and configurations.

![Python](https://img.shields.io/badge/python-3.11%2B-blue)
![Streamlit](https://img.shields.io/badge/streamlit-1.29%2B-red)
![Docker](https://img.shields.io/badge/docker-required-blue)
![License](https://img.shields.io/badge/license-Apache%202.0-green)
[![Tests](https://github.com/OpenSPP/openspp-deployment-manager/actions/workflows/test.yml/badge.svg)](https://github.com/OpenSPP/openspp-deployment-manager/actions/workflows/test.yml)

## ⚠️ SECURITY WARNING
**This application has NO AUTHENTICATION and should NEVER be exposed to the public internet!**
- The admin UI allows full control over Docker deployments without any login
- Anyone with access can create, modify, and delete deployments
- This tool is designed for:
  - Internal use behind a VPN
  - Local development environments
  - Private networks with restricted access
- **DO NOT** deploy this on a public-facing server
- **DO NOT** expose port 8501 (Streamlit) to the internet

For production use, ensure this application is only accessible through:
- Corporate VPN
- Private network with firewall rules
- Local development machine

## Features

- ✅ **Easy Deployment**: Deploy multiple isolated OpenSPP instances with a few clicks
- 🔄 **Version Management**: Select specific OpenSPP versions and dependency branches
- 🌐 **Domain Mapping**: Automatic subdomain configuration (e.g., tester1-dev.test.openspp.org)
- ⚡ **Task Execution**: Execute invoke tasks through the web UI
- 📊 **Monitoring**: Real-time container status and resource usage
- 📋 **Log Streaming**: View logs from any service
- 🔧 **Lifecycle Management**: Start, stop, update, and delete deployments
- 🧹 **Automatic Cleanup**: Clean up old deployments and Docker resources
## Prerequisites
- Python 3.11+ with `uv` package manager
- Docker and Docker Compose
- Git
- Nginx (for domain routing)
- Sudo access (for Nginx configuration)
- OpenSPP Docker repository access
## Quick Start
### 1. Clone the Repository
```bash
git clone https://github.com/OpenSPP/openspp-deployment-manager.git
cd openspp-deployment-manager
```

### 2. Install Dependencies

```bash
# Using uv (recommended)
uv sync

# Or using pip
pip install -r requirements.txt
```

### 3. Configure Environment

```bash
# Copy example environment file
cp .env.example .env

# Edit .env with your settings
nano .env
```

Key configuration options:
- `DEPLOYMENT_BASE_PATH`: Where to store deployments (default: `./deployments`)
- `BASE_DOMAIN`: Your base domain for subdomains (default: `test.openspp.org`)
- `PORT_RANGE_START/END`: Port range for deployments (default: 18000-19000)

### 4. Initialize Database

```bash
python -m src.database init
```

### 5. Run the Application

⚠️ **Security Reminder**: Only run this on a secure, private network. There is NO authentication!

```bash
# Using streamlit directly
streamlit run app.py

# Or using uv
uv run streamlit run app.py
```

The application will be available at http://localhost:8501

**IMPORTANT**: Do not expose port 8501 to the internet. Use VPN or firewall rules to restrict access.
## Usage Guide
### Creating a Deployment

1. Click "➕ New Deployment" button
2. Fill in the required fields:
   - **Tester Email**: Email of the person creating the deployment
   - **Deployment Name**: Unique name (3-20 chars, alphanumeric + hyphens)
   - **Environment**: Choose between devel, test, or prod
   - **OpenSPP Version**: Select from available versions
3. Optionally override dependency versions in Advanced Options
4. Click "🚀 Create Deployment"
The system will:
- Clone openspp-docker repository
- Configure versions in repos.yaml
- Generate environment variables
- Build and start all services
- Configure Nginx for subdomain access
### Managing Deployments

Each deployment card shows:
- Status indicator (🟢 Running, 🔴 Stopped, etc.)
- Version information
- Resource usage (CPU/Memory)
- Quick action buttons

Available actions:
- **▶️ Start**: Start stopped deployment
- **⏹️ Stop**: Stop running deployment
- **📋 Logs**: View recent logs
- **⚙️ Manage**: Open management panel
- **🗑️ Delete**: Remove deployment
### Executing Tasks
In the management panel, you can execute various invoke tasks:
- **Lifecycle**: start, stop, restart
- **Database**: resetdb, snapshot, restore-snapshot
- **Development**: logs, install, update, test
- **Git**: git-aggregate
### Viewing Logs

1. Click the 📋 button or go to the management panel
2. Select service (all, odoo, db, smtp)
3. Choose number of lines (50-500)
4. Click "🔄 Refresh Logs" to update
## Configuration
### config.yaml
Main application configuration:
```yaml
deployment:
  base_path: "./deployments"
  max_per_tester: 3

docker:
  resource_limits:
    cpu: "2"
    memory: "4GB"
    
ports:
  range_start: 18000
  range_end: 19000

domain:
  base: "test.openspp.org"
```
### Port Allocation
Each deployment gets a port range:
- Base port (e.g., 18000)
- SMTP: base + 25
- PGWeb: base + 81
- Debugger: base + 84
### Nginx Configuration
The system automatically generates Nginx configurations for each deployment:
```nginx
server {
    listen 80;
    server_name tester1-dev.test.openspp.org;
    
    location / {
        proxy_pass http://localhost:18000;
        # ... proxy settings
    }
}
```

To manually regenerate all Nginx configs:

```bash
python -m src.domain_manager generate-nginx
sudo nginx -s reload
```
## Git Cache Management
The deployment manager includes an optimized Git caching system that significantly reduces disk usage and speeds up deployments. The Odoo repository, which normally takes 13GB+, is automatically shallow-cloned to under 1.5GB.
### Cache Management Commands
```bash
# Analyze cache usage and statistics
uv run python manage_git_cache.py analyze
# Optimize cache (garbage collection)
uv run python manage_git_cache.py optimize
# Aggressive optimization (converts large repos to shallow clones)
uv run python manage_git_cache.py optimize --aggressive
# Clean up old repositories (default: 30 days)
uv run python manage_git_cache.py cleanup --max-age 7
# Optimize Odoo repository specifically
uv run python manage_git_cache.py odoo
# Clear entire cache (requires confirmation)
uv run python manage_git_cache.py clear
```
### Features
- **Automatic Shallow Cloning**: Large repositories (Odoo, OCA/OCB) are automatically shallow-cloned with depth=1
- **Space Savings**: Reduces Odoo from ~13GB to ~1GB (90%+ reduction)
- **Smart Caching**: 5-minute TTL prevents unnecessary fetches
- **Branch-Specific Fetching**: Only fetches required branches
- **Automatic Cleanup**: Remove repositories not accessed in X days
- **Repository Statistics**: Track sizes and optimization potential
### Configuration
In `config.yaml`:
```yaml
git_cache_path: "./.git_cache"  # Where to store cached repositories
```

The cache manager automatically:
- Detects and optimizes large repositories
- Maintains shallow clones for space efficiency
- Provides detailed statistics on cache usage
- Cleans up unused repositories
## Architecture
### Components
1. **Streamlit UI** (`app.py`): Web interface
2. **Deployment Manager** (`src/deployment_manager.py`): Core orchestration
3. **Docker Handler** (`src/docker_handler.py`): Container management
4. **Database** (`src/database.py`): SQLite persistence
5. **Domain Manager** (`src/domain_manager.py`): Nginx configuration
6. **Git Cache Manager** (`src/git_cache.py`): Optimized repository caching
### Data Flow
1. User creates deployment via UI
2. Manager allocates resources (ports, subdomain)
3. Git clones openspp-docker
4. Updates configuration (repos.yaml, .env)
5. Executes invoke tasks (build, start)
6. Configures Nginx
7. Monitors container status
## Troubleshooting
### Common Issues

**Port allocation failed**
- Check if ports 18000-19000 are available
- Increase port range in config.yaml

**Docker build errors**
- Ensure Docker daemon is running
- Check Docker disk space
- Verify openspp-docker repository access

**Nginx configuration failed**
- Ensure sudo access is configured
- Check Nginx is installed
- Verify sites-available/enabled paths

**Services not starting**
- Check logs: `docker compose logs -f odoo`
- Verify .env file is correct
- Ensure sufficient system resources
### Maintenance Tasks

**Sync deployment states**
```bash
# From UI: Click "🔄 Sync States" in sidebar
```

**Clean up Docker resources**
```bash
# From UI: Click "🧹 Cleanup Resources"
# Or manually:
docker system prune -a
```

**Remove old deployments**
```bash
# Automatic cleanup configured in config.yaml
# cleanup.stopped_deployment_days: 7
```
## Development
### Project Structure

```
openspp-deployment-manager/
├── app.py                    # Streamlit application
├── manage_git_cache.py      # Git cache management utility
├── src/
│   ├── deployment_manager.py # Core logic
│   ├── docker_handler.py     # Docker operations
│   ├── database.py          # SQLite operations
│   ├── domain_manager.py    # Nginx management
│   ├── git_cache.py         # Git repository caching
│   ├── models.py           # Data models
│   └── utils.py            # Utilities
├── deployments/            # Deployment storage
├── .git_cache/             # Cached git repositories
├── config.yaml            # Configuration
└── requirements.txt       # Dependencies
```
### Adding New Invoke Tasks
Edit `ALLOWED_INVOKE_TASKS` in `app.py`:
```python
ALLOWED_INVOKE_TASKS = {
    "new-task": {
        "params": ["param1", "param2"],
        "description": "Task description",
        "icon": "⚙️"
    }
}
```
### Database Schema

SQLite tables:
- `deployments`: Deployment metadata
- `port_allocations`: Port range tracking
## Security Considerations

⚠️ **CRITICAL: This application has NO AUTHENTICATION!**

- **MUST** run behind VPN or private network - NEVER expose to public internet
- The admin UI (port 8501) provides unrestricted access to:
  - Create/delete Docker deployments
  - Execute system commands via invoke tasks
  - Access deployment logs and configurations
  - Manage system resources
- Nginx configurations use security headers for deployed instances
- Environment variables contain sensitive data (database passwords, etc.)
- Database is local SQLite file with no access control
- Docker containers run with resource limits but still have system access

**Recommended Security Measures:**
1. Run only on internal networks or behind VPN
2. Use firewall rules to restrict access to port 8501
3. Monitor access logs regularly
4. Consider adding a reverse proxy with authentication if broader access is needed
5. Regularly audit deployed instances and remove unused ones
## Testing

The project includes a comprehensive test suite:

```bash
# Run all tests
uv run pytest

# Run with coverage
uv run pytest --cov=src --cov-report=html

# Run specific test file
uv run pytest tests/test_deployment_manager.py -v
```

## Contributing

We welcome contributions! Please see [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines on:
- Development setup
- Code style and standards
- Testing requirements
- Pull request process
- Security considerations

## License

This project is licensed under the Apache License 2.0 - see the [LICENSE](LICENSE) file for details.

## Support

For issues and questions:
- Check the troubleshooting guide above
- Review logs in `logs/` directory
- Open a [GitHub issue](https://github.com/OpenSPP/openspp-deployment-manager/issues) with details
- For OpenSPP-specific questions, visit [OpenSPP documentation](https://docs.openspp.org)
