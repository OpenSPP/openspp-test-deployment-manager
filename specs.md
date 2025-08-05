# OpenSPP Docker Deployment Manager - Technical Specification v2

## 1. Overview

### Purpose
A web-based tool to manage multiple OpenSPP Docker test deployments, allowing testers to easily deploy, configure, and manage OpenSPP instances with different versions and configurations.

### Core Principles
- **Simple**: Minimal dependencies, straightforward architecture
- **Portable**: Can run in LXD, VM, or bare metal
- **Maintainable**: Clear code structure, follows openspp-docker patterns
- **Reliable**: Proper error handling and state management

### Key Features
- Deploy multiple isolated OpenSPP instances
- Version management through repos.yaml
- Domain mapping support (e.g., tester1-dev.test.openspp.org)
- Execute invoke tasks through UI
- Monitor deployment status and logs

## 2. Architecture

### High-Level Architecture
```
┌─────────────────────────────────────────┐
│         Streamlit Web UI                │
│    (Port 8501, behind VPN)              │
├─────────────────────────────────────────┤
│      Deployment Manager Core            │
│  (Python Business Logic)                │
├─────────────────────────────────────────┤
│   Storage Layer                         │
│   - SQLite (deployments.db)             │
│   - File System (deployments/)          │
├─────────────────────────────────────────┤
│   External Interfaces                   │
│   - Docker SDK & Compose                │
│   - Git/GitPython                       │
│   - Invoke Tasks                        │
└─────────────────────────────────────────┘
```

### Directory Structure
```
openspp-deployment-manager/
├── app.py                    # Streamlit main application
├── requirements.txt          # Python dependencies
├── config.yaml              # Application configuration
├── README.md                # Setup and usage documentation
├── .env.example             # Example environment variables
├── src/
│   ├── __init__.py
│   ├── deployment_manager.py # Core deployment logic
│   ├── docker_handler.py    # Docker operations wrapper
│   ├── database.py          # SQLite operations
│   ├── domain_manager.py    # Subdomain management
│   ├── utils.py             # Helper functions
│   └── models.py            # Data models
├── deployments/             # All deployment instances
│   └── {deployment_id}/     # Individual deployment
│       ├── openspp-docker/  # Cloned repository
│       ├── .env            # Deployment-specific env
│       └── deployment.json  # Deployment metadata
├── templates/               # Configuration templates
│   └── env.template        # Environment template
└── logs/                   # Application logs
```

## 3. Data Models

### Deployment Model
```python
@dataclass
class Deployment:
    id: str                    # Unique ID: "{tester}-{name}"
    name: str                  # Display name
    tester_email: str          # Tester's email
    openspp_version: str       # Tag/branch (e.g., "openspp-17.0.1.2.1")
    dependency_versions: dict  # {"openg2p_registry": "17.0-develop-openspp", ...}
    environment: str           # devel|test|prod
    status: str               # creating|running|stopped|error|updating
    created_at: datetime
    last_updated: datetime
    port_base: int            # Base port (e.g., 18000)
    port_mappings: dict       # {"odoo": 18000, "smtp": 18025, "pgweb": 18081}
    subdomain: str            # e.g., "tester1-dev"
    modules_installed: List[str]  # Installed modules
    last_action: str          # Last executed action
    notes: str                # Tester notes
```

### Configuration Model
```python
@dataclass
class AppConfig:
    # Paths
    base_deployment_path: str = "./deployments"
    openspp_docker_repo: str = "https://github.com/OpenSPP/openspp-docker.git"
    default_branch: str = "17.0"
    
    # Port management
    port_range_start: int = 18000
    port_range_end: int = 19000
    port_increment: int = 100  # Space between deployments
    
    # Domain configuration
    base_domain: str = "test.openspp.org"  # For subdomain generation
    
    # Resource limits
    max_deployments_per_tester: int = 3
    docker_cpu_limit: str = "2"
    docker_memory_limit: str = "4GB"
    
    # Service wait times
    services_wait_time: int = 10  # Seconds to wait after start
    
    # Available versions (fetched from git)
    available_openspp_versions: List[str]
    available_dependency_branches: Dict[str, List[str]]
```

## 4. Feature Specifications

### 4.1 Deployment Management

#### Create Deployment
**Input Fields:**
- Tester email (required)
- Deployment name (alphanumeric + dash)
- Environment (devel/test/prod)
- OpenSPP version (dropdown from git tags)
- Advanced: Override dependency versions

**Process Flow:**
```python
def create_deployment(params: DeploymentParams) -> Deployment:
    # 1. Validate inputs
    validate_deployment_params(params)
    check_deployment_limits(params.tester_email)
    
    # 2. Allocate resources
    deployment_id = f"{params.tester}-{params.name}"
    port_base = allocate_port_range()
    subdomain = f"{deployment_id}.{config.base_domain}"
    
    # 3. Create deployment directory
    deployment_path = f"{config.base_deployment_path}/{deployment_id}"
    os.makedirs(deployment_path)
    
    # 4. Clone openspp-docker
    git.clone(config.openspp_docker_repo, f"{deployment_path}/openspp-docker")
    git.checkout(config.default_branch)
    
    # 5. Update repos.yaml with versions
    update_repos_yaml(deployment_path, params.openspp_version, 
                     params.dependency_versions)
    
    # 6. Generate .env file
    generate_env_file(deployment_path, port_base, deployment_id)
    
    # 7. Run deployment sequence
    run_invoke_task("develop")
    run_invoke_task("img-pull")
    run_invoke_task("img-build")
    run_invoke_task("git-aggregate")
    run_invoke_task("resetdb")
    run_invoke_task("start")
    
    # 8. Save deployment info
    deployment = Deployment(...)
    save_to_database(deployment)
    
    return deployment
```

#### Update Deployment Version
**Process:**
1. Stop deployment
2. Update repos.yaml
3. Run git-aggregate
4. Optionally reset database
5. Start deployment

#### List Deployments
**Features:**
- Real-time status from Docker
- Resource usage (CPU/Memory)
- Quick actions per deployment
- Filter by: tester, status, version
- Search functionality

### 4.2 Invoke Task Execution

#### Supported Tasks
```python
ALLOWED_INVOKE_TASKS = {
    # Lifecycle
    "start": {"params": ["--detach"], "description": "Start services"},
    "stop": {"params": [], "description": "Stop services"},
    "restart": {"params": ["--quick"], "description": "Restart Odoo"},
    
    # Database
    "resetdb": {"params": ["--modules"], "description": "Reset database"},
    "snapshot": {"params": [], "description": "Create DB snapshot"},
    "restore-snapshot": {"params": ["--snapshot-name"], "description": "Restore snapshot"},
    
    # Development
    "logs": {"params": ["--tail", "--follow"], "description": "View logs"},
    "install": {"params": ["--modules"], "description": "Install modules"},
    "update": {"params": [], "description": "Update modules"},
    "test": {"params": ["--modules"], "description": "Run tests"},
    
    # Git operations
    "git-aggregate": {"params": [], "description": "Update dependencies"},
}
```

#### Task Execution UI
```python
# Streamlit implementation
def render_task_executor(deployment: Deployment):
    task = st.selectbox("Select Task", list(ALLOWED_INVOKE_TASKS.keys()))
    task_info = ALLOWED_INVOKE_TASKS[task]
    
    # Dynamic parameter inputs
    params = {}
    if "--modules" in task_info["params"]:
        params["modules"] = st.text_input("Modules (comma-separated)")
    
    if st.button(f"Execute {task}"):
        result = execute_invoke_task(deployment, task, params)
        st.code(result.output)
```

### 4.3 Version Management

#### Fetching Available Versions
```python
def fetch_openspp_versions() -> List[str]:
    """Fetch available OpenSPP versions from GitHub"""
    # Get tags from openspp-modules repo
    tags = git.get_tags("https://github.com/openspp/openspp-modules.git")
    # Filter for openspp-* tags
    return [t for t in tags if t.startswith("openspp-")]

def fetch_dependency_branches(repo_url: str) -> List[str]:
    """Fetch available branches for a dependency"""
    branches = git.get_branches(repo_url)
    return [b for b in branches if "openspp" in b or "develop" in b]
```

#### Updating repos.yaml
```python
def update_repos_yaml(deployment_path: str, versions: dict):
    """Update repos.yaml with selected versions"""
    repos_yaml_path = f"{deployment_path}/openspp-docker/odoo/custom/src/repos.yaml"
    
    with open(repos_yaml_path, 'r') as f:
        repos = yaml.safe_load(f)
    
    # Update openspp_modules version
    repos['openspp_modules']['target'] = f"openspp {versions['openspp']}"
    repos['openspp_modules']['merges'] = [f"openspp {versions['openspp']}"]
    
    # Update other dependencies if specified
    for dep, version in versions.get('dependencies', {}).items():
        if dep in repos:
            repos[dep]['merges'] = [f"openg2p {version}"]
    
    with open(repos_yaml_path, 'w') as f:
        yaml.dump(repos, f, default_flow_style=False)
```

### 4.4 Monitoring & Logs

#### Container Status
```python
def get_deployment_status(deployment_id: str) -> dict:
    """Get real-time status of deployment containers"""
    project_name = f"openspp_{deployment_id.replace('-', '_')}"
    
    containers = docker_client.containers.list(
        filters={"label": f"com.docker.compose.project={project_name}"}
    )
    
    return {
        "odoo": get_container_health("odoo"),
        "db": get_container_health("db"),
        "smtp": get_container_health("smtp"),
        "services_healthy": all_services_healthy(containers)
    }
```

#### Log Streaming
```python
def stream_logs(deployment_id: str, service: str = "odoo", lines: int = 100):
    """Stream logs from deployment containers"""
    deployment_path = get_deployment_path(deployment_id)
    
    with cd(deployment_path):
        # Use invoke logs task
        result = run_invoke_task("logs", {
            "tail": lines,
            "container": service
        })
    return result.output
```

### 4.5 Domain Management

#### Nginx Configuration Generator
```python
def generate_nginx_config(deployment: Deployment) -> str:
    """Generate Nginx reverse proxy configuration"""
    return f"""
server {{
    listen 80;
    server_name {deployment.subdomain}.{config.base_domain};
    
    location / {{
        proxy_pass http://localhost:{deployment.port_mappings['odoo']};
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }}
    
    # Websocket support
    location /websocket {{
        proxy_pass http://localhost:{deployment.port_mappings['odoo']};
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
    }}
}}
"""
```

## 5. User Interface Design

### 5.1 Main Dashboard
```python
# Streamlit layout
st.set_page_config(page_title="OpenSPP Deployment Manager", layout="wide")

# Header
col1, col2 = st.columns([3, 1])
with col1:
    st.title("OpenSPP Deployment Manager")
with col2:
    if st.button("➕ New Deployment", type="primary"):
        st.session_state.show_create = True

# Deployments grid
deployments = get_all_deployments()
for deployment in deployments:
    with st.container():
        col1, col2, col3, col4 = st.columns([3, 2, 2, 3])
        
        with col1:
            st.subheader(deployment.id)
            st.text(f"Version: {deployment.openspp_version}")
        
        with col2:
            status = get_deployment_status(deployment.id)
            st.metric("Status", status['status'], 
                     delta="Healthy" if status['healthy'] else "Issues")
        
        with col3:
            st.text(f"Created: {deployment.created_at}")
            st.text(f"Env: {deployment.environment}")
        
        with col4:
            c1, c2, c3, c4 = st.columns(4)
            with c1:
                st.link_button("Open Odoo", 
                              f"http://{deployment.subdomain}.{config.base_domain}")
            with c2:
                if st.button("📋", key=f"logs_{deployment.id}"):
                    show_logs(deployment)
            with c3:
                if st.button("⚙️", key=f"manage_{deployment.id}"):
                    show_management(deployment)
            with c4:
                if st.button("🗑️", key=f"delete_{deployment.id}"):
                    confirm_delete(deployment)
```

### 5.2 Create Deployment Form
```python
with st.form("create_deployment"):
    st.subheader("Create New Deployment")
    
    # Basic Information
    col1, col2 = st.columns(2)
    with col1:
        tester_email = st.text_input("Tester Email*", 
                                   placeholder="tester@example.com")
        deployment_name = st.text_input("Deployment Name*", 
                                      placeholder="my-test")
        environment = st.selectbox("Environment", 
                                 ["devel", "test", "prod"])
    
    with col2:
        versions = fetch_openspp_versions()
        openspp_version = st.selectbox("OpenSPP Version", versions)
        notes = st.text_area("Notes", 
                           placeholder="Purpose of this deployment...")
    
    # Advanced Options
    with st.expander("Advanced Options"):
        st.markdown("**Override Dependency Versions**")
        dependencies = {}
        for dep in ["openg2p_registry", "openg2p_program"]:
            branches = fetch_dependency_branches(dep)
            selected = st.selectbox(f"{dep} branch", 
                                  ["default"] + branches)
            if selected != "default":
                dependencies[dep] = selected
    
    submitted = st.form_submit_button("Create Deployment", type="primary")
```

### 5.3 Deployment Management Panel
```python
def show_management_panel(deployment: Deployment):
    st.subheader(f"Manage: {deployment.id}")
    
    # Status Overview
    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("CPU Usage", "45%")
    with col2:
        st.metric("Memory", "2.1GB / 4GB")
    with col3:
        st.metric("Uptime", "2d 4h")
    
    # Access URLs
    st.markdown("### Access URLs")
    urls = {
        "Odoo": f"http://{deployment.subdomain}.{config.base_domain}",
        "Mailhog": f"http://{deployment.subdomain}.{config.base_domain}:8025",
        "PGWeb": f"http://{deployment.subdomain}.{config.base_domain}:8081"
    }
    for service, url in urls.items():
        st.code(url)
    
    # Task Execution
    st.markdown("### Execute Tasks")
    render_task_executor(deployment)
    
    # Recent Logs
    st.markdown("### Recent Logs")
    log_lines = st.slider("Number of lines", 50, 500, 100)
    if st.button("Refresh Logs"):
        logs = stream_logs(deployment.id, lines=log_lines)
        st.code(logs, language="log")
```

## 6. Implementation Details

### 6.1 Core Dependencies
```txt
# requirements.txt
streamlit==1.29.0
docker==7.0.0
gitpython==3.1.40
pyyaml==6.0.1
invoke==2.2.0
python-dotenv==1.0.0
pandas==2.1.4
plotly==5.18.0
psutil==5.9.6
```

### 6.2 Environment Variables
```bash
# .env.example
# Base configuration
DEPLOYMENT_BASE_PATH=./deployments
PORT_RANGE_START=18000
PORT_RANGE_END=19000

# Domain configuration
BASE_DOMAIN=test.openspp.org
NGINX_CONFIG_PATH=/etc/nginx/sites-available

# Resource limits
MAX_DEPLOYMENTS_PER_TESTER=3
DOCKER_CPU_LIMIT=2
DOCKER_MEMORY_LIMIT=4GB

# Git configuration
OPENSPP_DOCKER_REPO=https://github.com/OpenSPP/openspp-docker.git
DEFAULT_BRANCH=17.0
```

### 6.3 Docker Compose Integration
```python
class DockerComposeHandler:
    """Handle Docker Compose operations for deployments"""
    
    def __init__(self, deployment_path: str):
        self.deployment_path = deployment_path
        self.compose_path = f"{deployment_path}/openspp-docker"
        
    def _run_compose_command(self, command: str, env: dict = None) -> subprocess.Result:
        """Run docker-compose command in deployment directory"""
        full_env = os.environ.copy()
        if env:
            full_env.update(env)
        
        # Set required environment variables
        full_env.update({
            "UID": str(os.getuid()),
            "GID": str(os.getgid()),
            "COMPOSE_PROJECT_NAME": self._get_project_name()
        })
        
        cmd = f"docker compose -f docker-compose.yml {command}"
        
        return subprocess.run(
            cmd,
            shell=True,
            cwd=self.compose_path,
            env=full_env,
            capture_output=True,
            text=True
        )
```

### 6.4 Invoke Task Wrapper
```python
def run_invoke_task(deployment_path: str, task: str, params: dict = None) -> TaskResult:
    """Execute invoke task in deployment directory"""
    cmd = ["invoke", task]
    
    # Add parameters
    if params:
        for key, value in params.items():
            if value:
                cmd.extend([f"--{key}", str(value)])
    
    # Set working directory
    working_dir = f"{deployment_path}/openspp-docker"
    
    # Run command
    result = subprocess.run(
        cmd,
        cwd=working_dir,
        capture_output=True,
        text=True,
        env={
            **os.environ,
            "UID": str(os.getuid()),
            "GID": str(os.getgid())
        }
    )
    
    return TaskResult(
        success=result.returncode == 0,
        output=result.stdout,
        error=result.stderr
    )
```

## 7. Security Considerations

### 7.1 Access Control
- Application runs behind VPN (no built-in auth initially)
- Future: OAuth2/SAML integration option

### 7.2 Input Validation
```python
def validate_deployment_name(name: str) -> bool:
    """Validate deployment name format"""
    import re
    # Only alphanumeric and hyphens, 3-20 chars
    pattern = r'^[a-z0-9][a-z0-9-]{1,18}[a-z0-9]$'
    return bool(re.match(pattern, name.lower()))

def validate_email(email: str) -> bool:
    """Validate email format"""
    import re
    pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    return bool(re.match(pattern, email))
```

### 7.3 Resource Protection
- Port range validation
- CPU/Memory limits enforced
- Deployment quota per tester
- Automatic cleanup of orphaned resources

## 8. Error Handling

### 8.1 Deployment Failures
```python
class DeploymentError(Exception):
    """Base exception for deployment errors"""
    pass

def handle_deployment_error(deployment_id: str, error: Exception):
    """Handle deployment failures gracefully"""
    logger.error(f"Deployment {deployment_id} failed: {error}")
    
    # Update status
    update_deployment_status(deployment_id, "error")
    
    # Cleanup partial deployment
    cleanup_failed_deployment(deployment_id)
    
    # Notify user
    st.error(f"Deployment failed: {str(error)}")
```

### 8.2 State Synchronization
```python
def sync_deployment_states():
    """Sync database with actual Docker states"""
    deployments = get_all_deployments()
    
    for deployment in deployments:
        actual_status = get_container_status(deployment.id)
        
        if deployment.status != actual_status:
            logger.info(f"Syncing state for {deployment.id}: "
                       f"{deployment.status} -> {actual_status}")
            update_deployment_status(deployment.id, actual_status)
```

## 9. Maintenance Features

### 9.1 Cleanup Tasks
```python
def cleanup_stopped_deployments(days_old: int = 7):
    """Remove deployments stopped for more than X days"""
    cutoff_date = datetime.now() - timedelta(days=days_old)
    
    stopped_deployments = get_deployments_by_status("stopped")
    for deployment in stopped_deployments:
        if deployment.last_updated < cutoff_date:
            delete_deployment(deployment.id)

def cleanup_orphaned_containers():
    """Remove Docker containers without deployments"""
    all_containers = docker_client.containers.list(all=True)
    
    for container in all_containers:
        project = container.labels.get("com.docker.compose.project", "")
        if project.startswith("openspp_"):
            deployment_id = project.replace("openspp_", "").replace("_", "-")
            if not deployment_exists(deployment_id):
                logger.info(f"Removing orphaned container: {container.name}")
                container.remove(force=True)
```

### 9.2 Backup/Restore
```python
def backup_deployment(deployment_id: str) -> str:
    """Create backup of deployment configuration"""
    deployment = get_deployment(deployment_id)
    backup_data = {
        "deployment": deployment.to_dict(),
        "repos_yaml": read_repos_yaml(deployment_id),
        "env_file": read_env_file(deployment_id),
        "timestamp": datetime.now().isoformat()
    }
    
    backup_file = f"backups/{deployment_id}_{timestamp}.json"
    with open(backup_file, 'w') as f:
        json.dump(backup_data, f, indent=2)
    
    return backup_file
```

## 10. Configuration File

```yaml
# config.yaml
app:
  title: "OpenSPP Deployment Manager"
  port: 8501
  debug: false

deployment:
  base_path: "./deployments"
  max_per_tester: 3
  
git:
  openspp_docker_repo: "https://github.com/OpenSPP/openspp-docker.git"
  default_branch: "17.0"
  
docker:
  compose_command: "docker compose"  # or "docker-compose" for older systems
  project_prefix: "openspp"
  resource_limits:
    cpu: "2"
    memory: "4GB"
    
ports:
  range_start: 18000
  range_end: 19000
  services:
    odoo: 0      # base + 0
    smtp: 25     # base + 25  
    pgweb: 81    # base + 81
    debugger: 84 # base + 84
    
domain:
  base: "test.openspp.org"
  ssl: false  # Enable if using HTTPS
  
monitoring:
  status_check_interval: 60  # seconds
  log_retention_days: 7
  
cleanup:
  auto_cleanup: true
  stopped_deployment_days: 7
  orphaned_check_interval: 3600  # seconds
```

## 11. Installation & Setup Guide

### Quick Start
```bash
# 1. Clone the repository
git clone <repo-url> openspp-deployment-manager
cd openspp-deployment-manager

# 2. Install dependencies
pip install -r requirements.txt

# 3. Copy and configure environment
cp .env.example .env
# Edit .env with your settings

# 4. Initialize database
python -m src.database init

# 5. Run the application
streamlit run app.py
```

### Nginx Setup (for domain support)
```bash
# Generate Nginx configs for all deployments
python -m src.domain_manager generate-nginx

# Reload Nginx
sudo nginx -s reload
```

## 12. Future Enhancements

### Phase 2
- REST API for CI/CD integration
- Deployment templates/profiles
- Scheduled deployments
- Email notifications
- Metrics dashboard with Grafana

### Phase 3
- Kubernetes deployment option
- Multi-node support
- Cost tracking
- Auto-scaling based on usage
- Integration with OpenSPP CI/CD
