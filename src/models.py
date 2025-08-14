# ABOUTME: Data models for OpenSPP deployments and application configuration
# ABOUTME: Defines Deployment and AppConfig dataclasses with all required fields

from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Dict, Optional
from enum import Enum


class DeploymentStatus(str, Enum):
    """Deployment status values"""
    CREATING = "creating"
    RUNNING = "running"
    STOPPED = "stopped"
    ERROR = "error"
    UPDATING = "updating"


@dataclass
class Deployment:
    """Represents a single OpenSPP deployment instance"""
    id: str                    # Unique ID: "{tester}-{name}"
    name: str                  # Display name
    tester_email: str          # Tester's email
    openspp_version: str       # Tag/branch (e.g., "openspp-17.0.1.2.1")
    dependency_versions: Dict[str, str] = field(default_factory=dict)  # {"openg2p_registry": "17.0-develop-openspp", ...}
    environment: str = "devel"  # devel|test|prod
    status: DeploymentStatus = DeploymentStatus.CREATING
    created_at: datetime = field(default_factory=datetime.now)
    last_updated: datetime = field(default_factory=datetime.now)
    port_base: int = 0         # Base port (e.g., 18000)
    port_mappings: Dict[str, int] = field(default_factory=dict)  # {"odoo": 18000, "smtp": 18025, "pgweb": 18081}
    subdomain: str = ""        # e.g., "tester1-dev"
    modules_installed: List[str] = field(default_factory=list)  # Installed modules
    last_action: str = ""      # Last executed action
    notes: str = ""            # Tester notes
    auth_password: str = ""    # Random password for nginx basic auth
    
    def to_dict(self) -> dict:
        """Convert deployment to dictionary for JSON serialization"""
        return {
            "id": self.id,
            "name": self.name,
            "tester_email": self.tester_email,
            "openspp_version": self.openspp_version,
            "dependency_versions": self.dependency_versions,
            "environment": self.environment,
            "status": self.status,
            "created_at": self.created_at.isoformat(),
            "last_updated": self.last_updated.isoformat(),
            "port_base": self.port_base,
            "port_mappings": self.port_mappings,
            "subdomain": self.subdomain,
            "modules_installed": self.modules_installed,
            "last_action": self.last_action,
            "notes": self.notes,
            "auth_password": self.auth_password
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> 'Deployment':
        """Create deployment from dictionary"""
        data = data.copy()
        data['created_at'] = datetime.fromisoformat(data['created_at'])
        data['last_updated'] = datetime.fromisoformat(data['last_updated'])
        return cls(**data)


@dataclass
class AppConfig:
    """Application configuration settings"""
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
    
    # Health check settings
    docker_health_check_timeout: int = 300  # seconds
    docker_skip_health_check: bool = False
    
    # Development mode settings
    dev_mode: bool = False  # Preserve failed deployments for debugging
    
    # Git cache settings
    git_cache_enabled: bool = True
    git_cache_path: str = "./.git_cache"
    
    # Service wait times
    services_wait_time: int = 10  # Seconds to wait after start
    
    # Available versions (fetched from git)
    available_openspp_versions: List[str] = field(default_factory=list)
    available_dependency_branches: Dict[str, List[str]] = field(default_factory=dict)
    
    # Nginx configuration
    nginx_enabled: bool = True
    nginx_config_path: str = "/etc/nginx/sites-available"
    nginx_reload_command: str = "sudo nginx -s reload"
    
    @classmethod
    def from_yaml(cls, data: dict) -> 'AppConfig':
        """Create config from YAML data"""
        config = cls()
        
        # Update from nested structure
        if 'deployment' in data:
            config.base_deployment_path = data['deployment'].get('base_path', config.base_deployment_path)
            config.max_deployments_per_tester = data['deployment'].get('max_per_tester', config.max_deployments_per_tester)
        
        if 'git' in data:
            config.openspp_docker_repo = data['git'].get('openspp_docker_repo', config.openspp_docker_repo)
            config.default_branch = data['git'].get('default_branch', config.default_branch)
        
        if 'docker' in data:
            if 'resource_limits' in data['docker']:
                config.docker_cpu_limit = data['docker']['resource_limits'].get('cpu', config.docker_cpu_limit)
                config.docker_memory_limit = data['docker']['resource_limits'].get('memory', config.docker_memory_limit)
            if 'health_check' in data['docker']:
                config.docker_health_check_timeout = data['docker']['health_check'].get('timeout', config.docker_health_check_timeout)
                config.docker_skip_health_check = data['docker']['health_check'].get('skip', config.docker_skip_health_check)
        
        if 'ports' in data:
            config.port_range_start = data['ports'].get('range_start', config.port_range_start)
            config.port_range_end = data['ports'].get('range_end', config.port_range_end)
        
        if 'domain' in data:
            config.base_domain = data['domain'].get('base', config.base_domain)
        
        if 'nginx' in data:
            config.nginx_enabled = data['nginx'].get('enabled', config.nginx_enabled)
        
        if 'development' in data:
            config.dev_mode = data['development'].get('preserve_failed_deployments', config.dev_mode)
        
        return config


@dataclass
class TaskResult:
    """Result of an invoke task execution"""
    success: bool
    output: str
    error: str = ""
    execution_time: float = 0.0


@dataclass
class DeploymentParams:
    """Parameters for creating a new deployment"""
    tester_email: str
    name: str
    environment: str = "devel"
    openspp_version: str = "17.0"  # Can be branch (e.g., "17.0") or tag (e.g., "openspp-17.0.1.2.1")
    dependency_versions: Dict[str, str] = field(default_factory=dict)  # repo_name -> version/branch
    notes: str = ""
    
    @property
    def tester(self) -> str:
        """Extract tester identifier from email"""
        return self.tester_email.split('@')[0].replace('.', '-').lower()
    
    def validate(self) -> List[str]:
        """Validate deployment parameters"""
        errors = []
        
        if not self.tester_email or '@' not in self.tester_email:
            errors.append("Invalid tester email")
        
        if not self.name:
            errors.append("Deployment name is required")
        
        # Validate name format (alphanumeric + dash, 3-20 chars)
        import re
        if not re.match(r'^[a-z0-9][a-z0-9-]{1,18}[a-z0-9]$', self.name.lower()):
            errors.append("Name must be 3-20 characters, alphanumeric and hyphens only")
        
        if self.environment not in ['devel', 'test', 'prod']:
            errors.append("Environment must be devel, test, or prod")
        
        return errors