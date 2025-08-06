# ABOUTME: Core deployment management logic orchestrating all operations
# ABOUTME: Handles deployment lifecycle, version management, and task execution

import os
import logging
import shutil
import json
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple
import subprocess
from concurrent.futures import ThreadPoolExecutor, as_completed

import git
import yaml

from src.models import Deployment, DeploymentParams, AppConfig, TaskResult, DeploymentStatus
from src.database import DeploymentDatabase
from src.docker_handler import DockerComposeHandler, DockerResourceMonitor
from src.domain_manager import DomainManager
from src.git_cache import GitCacheManager
from src.utils import (
    validate_deployment_name, validate_email, sanitize_deployment_id,
    ensure_directory, read_yaml_file, write_yaml_file, get_port_mappings,
    generate_env_content, run_command, run_command_with_retry, cleanup_deployment_directory
)
from src.performance_tracker import performance_tracker

logger = logging.getLogger(__name__)


class DeploymentManager:
    """Main deployment manager orchestrating all operations"""
    
    def __init__(self, config: AppConfig):
        self.config = config
        self.db = DeploymentDatabase()
        self.domain_manager = DomainManager(config)
        self.resource_monitor = DockerResourceMonitor()
        
        # Initialize git cache if enabled
        self.git_cache = None
        if config.git_cache_enabled:
            self.git_cache = GitCacheManager(config.git_cache_path)
        
        # Ensure base deployment path exists
        ensure_directory(self.config.base_deployment_path)
        
        # Load available versions on init
        self._refresh_available_versions()
    
    def create_deployment(self, params: DeploymentParams, progress_callback=None) -> Tuple[bool, str, Optional[Deployment]]:
        """Create a new deployment"""
        # Validate parameters
        if progress_callback:
            progress_callback("Validating parameters...", "")
        validation_errors = params.validate()
        if validation_errors:
            return False, f"Validation failed: {', '.join(validation_errors)}", None
        
        # Check deployment limits
        if progress_callback:
            progress_callback("Checking deployment limits...", "")
        if not self._check_deployment_limits(params.tester_email):
            return False, f"Deployment limit reached for {params.tester_email}", None
        
        # Generate deployment ID
        deployment_id = sanitize_deployment_id(params.tester_email, params.name)
        
        # Allocate port range
        if progress_callback:
            progress_callback("Allocating resources...", "")
        port_base = self.db.allocate_port_range(deployment_id)
        if not port_base:
            return False, "No available port range", None
        
        # Get port mappings
        port_mappings = get_port_mappings(port_base)
        
        # Create deployment object
        deployment = Deployment(
            id=deployment_id,
            name=params.name,
            tester_email=params.tester_email,
            openspp_version=params.openspp_version,
            dependency_versions=params.dependency_versions,
            environment=params.environment,
            status=DeploymentStatus.CREATING,
            port_base=port_base,
            port_mappings=port_mappings,
            subdomain=self._generate_subdomain(deployment_id),
            notes=params.notes
        )
        
        # Save initial deployment record
        self.db.save_deployment(deployment)
        logger.info(f"Creating deployment {deployment_id}")
        
        try:
            # Create deployment directory
            deployment_path = self._get_deployment_path(deployment_id)
            ensure_directory(deployment_path)
            
            # Clone openspp-docker repository
            if progress_callback:
                progress_callback("Preparing OpenSPP Docker repository...", "")
            logger.info(f"Setting up openspp-docker for {deployment_id}")
            
            openspp_docker_path = deployment_path / "openspp-docker"
            
            with performance_tracker.track_operation("Setup OpenSPP Docker Repository", expected_duration=5.0):
                if self.git_cache:
                    # Use cached repository
                    if progress_callback:
                        progress_callback("Using cached repository...", "Much faster!")
                    
                    # Update cache first
                    self.git_cache.update_or_clone_repo(
                        self.config.openspp_docker_repo,
                        self.config.default_branch
                    )
                    
                    # Copy to deployment
                    self.git_cache.copy_to_destination(
                        self.config.openspp_docker_repo,
                        str(openspp_docker_path),
                        exclude_git=False
                    )
                    
                    # Checkout the correct branch in the copy
                    repo = git.Repo(openspp_docker_path)
                    repo.git.checkout(self.config.default_branch)
                else:
                    # Direct clone (fallback)
                    if progress_callback:
                        progress_callback("Cloning repository...", "This may take a minute...")
                    repo = git.Repo.clone_from(
                        self.config.openspp_docker_repo,
                        openspp_docker_path,
                        branch=self.config.default_branch
                    )
            
            if progress_callback:
                progress_callback("Repository ready", "OpenSPP Docker repository prepared")
            
            # Clean up openg2p_auth directory if it exists to avoid conflicts
            openg2p_auth_path = deployment_path / "openspp-docker" / "odoo" / "custom" / "src" / "openg2p_auth"
            if openg2p_auth_path.exists():
                logger.info("Removing existing openg2p_auth directory to avoid conflicts")
                import shutil
                shutil.rmtree(str(openg2p_auth_path), ignore_errors=True)
            
            # Note: Port fixing will happen after git-aggregate creates docker-compose.yml
            
            # Update repos.yaml with selected versions
            if progress_callback:
                progress_callback("Configuring deployment versions...", "")
            if not self._update_repos_yaml(deployment):
                raise Exception("Failed to update repos.yaml")
            if progress_callback:
                progress_callback("Configuration complete", f"Using OpenSPP {deployment.openspp_version}")
            
            # Generate .env file
            if progress_callback:
                progress_callback("Generating environment configuration...", "")
            if not self._generate_env_file(deployment):
                raise Exception("Failed to generate .env file")
            
            # Copy .env file to openspp-docker directory
            env_src = deployment_path / ".env"
            env_dst = deployment_path / "openspp-docker" / ".env"
            if env_src.exists():
                import shutil
                shutil.copy2(str(env_src), str(env_dst))
            
            # Generate docker-compose.override.yml for dynamic ports
            if not self._generate_docker_override(deployment):
                raise Exception("Failed to generate docker-compose override")
            
            if progress_callback:
                progress_callback("Environment configured", "")
            
            # Initialize docker handler with absolute path
            docker_handler = DockerComposeHandler(str(deployment_path / "openspp-docker"), deployment_id)
            
            # Run deployment sequence
            if progress_callback:
                progress_callback("Starting deployment sequence...", "")
            logger.info(f"Running deployment sequence for {deployment_id}")
            
            tasks = [
                ("develop", {}, "Setting up development environment"),
                ("img-pull", {}, "Pulling Docker images"),
                ("img-build", {}, "Building custom images"),
                ("git-aggregate", {}, "Aggregating dependencies"),
                ("resetdb", {}, "Initializing database"),
                ("start", {"detach": True}, "Starting services")
            ]
            
            for task_name, task_params, task_description in tasks:
                # Pre-populate repositories from cache before git-aggregate
                if task_name == "git-aggregate" and self.git_cache:
                    if progress_callback:
                        progress_callback("Pre-populating repositories from cache...", "")
                    self._prepopulate_repos_from_cache(deployment)
                    if progress_callback:
                        progress_callback("Cache pre-population complete", "Repositories copied from cache")
                
                # Get expected duration for this task
                expected_durations = {
                    "develop": 5.0,
                    "img-pull": 30.0,
                    "img-build": 120.0,
                    "git-aggregate": 45.0,
                    "resetdb": 60.0,
                    "start": 15.0
                }
                expected_duration = expected_durations.get(task_name, 10.0)
                
                with performance_tracker.track_operation(f"Task: {task_description}", expected_duration=expected_duration):
                    if progress_callback:
                        progress_callback(f"Executing: {task_description}", "")
                    logger.info(f"Executing task: {task_name}")
                    
                    result = self._run_invoke_task(deployment, task_name, task_params)
                    
                    if not result.success:
                        raise Exception(f"Task {task_name} failed: {result.error}")
                    
                    if progress_callback:
                        progress_callback(f"Completed: {task_description}", f"{task_name} completed successfully")
                
                # Fix hardcoded ports after git-aggregate creates docker-compose.yml
                if task_name == "git-aggregate":
                    if progress_callback:
                        progress_callback("Fixing port configuration...", "Updating docker-compose.yml with environment variables")
                    logger.info("Fixing hardcoded ports in docker-compose.yml after git-aggregate")
                    if not self._fix_docker_compose_ports(deployment):
                        logger.warning("Failed to fix docker-compose.yml ports after git-aggregate")
                    else:
                        logger.info("Successfully fixed hardcoded ports in docker-compose.yml")
                
                deployment.last_action = f"Executed {task_name}"
                self.db.save_deployment(deployment)
            
            # Wait for services to be ready
            if not self.config.docker_skip_health_check:
                if progress_callback:
                    progress_callback("Waiting for services to start...", "This may take a few minutes...")
                logger.info("Waiting for services to be ready...")
                if docker_handler.wait_for_services(timeout=self.config.docker_health_check_timeout):
                    deployment.status = DeploymentStatus.RUNNING
                else:
                    deployment.status = DeploymentStatus.ERROR
                    deployment.last_action = "Services failed to start"
            else:
                logger.info("Skipping health check as configured")
                deployment.status = DeploymentStatus.RUNNING
            
            # Setup domain/nginx
            if self.config.nginx_enabled:
                if progress_callback:
                    progress_callback("Setting up domain configuration...", "")
                logger.info(f"Setting up domain for {deployment_id}")
                self.domain_manager.setup_deployment_domain(deployment)
                if progress_callback:
                    progress_callback("Domain configured", f"Accessible at {deployment.subdomain}")
            else:
                logger.info(f"Nginx disabled - deployment accessible at localhost:{deployment.port_base}")
            
            # Final save
            self.db.save_deployment(deployment)
            
            logger.info(f"Deployment {deployment_id} created successfully")
            if progress_callback:
                progress_callback("Deployment ready!", f"Access at {deployment.subdomain if self.config.nginx_enabled else f'localhost:{deployment.port_base}'}")
            return True, "Deployment created successfully", deployment
            
        except Exception as e:
            logger.error(f"Failed to create deployment {deployment_id}: {e}")
            deployment.status = DeploymentStatus.ERROR
            deployment.last_action = f"Creation failed: {str(e)}"
            self.db.save_deployment(deployment)
            
            # Cleanup on failure
            self._cleanup_failed_deployment(deployment)
            
            return False, f"Deployment failed: {str(e)}", deployment
    
    def update_deployment(self, deployment_id: str, new_version: str, 
                         reset_db: bool = False) -> Tuple[bool, str]:
        """Update deployment to new version"""
        deployment = self.db.get_deployment(deployment_id)
        if not deployment:
            return False, "Deployment not found"
        
        if deployment.status != DeploymentStatus.RUNNING:
            return False, f"Cannot update deployment in {deployment.status} state"
        
        logger.info(f"Updating deployment {deployment_id} to {new_version}")
        deployment.status = DeploymentStatus.UPDATING
        self.db.save_deployment(deployment)
        
        try:
            # Update version
            deployment.openspp_version = new_version
            
            # Get deployment path
            deployment_path = self._get_deployment_path(deployment_id)
            
            # Clean up openg2p_auth directory if it exists to avoid conflicts
            openg2p_auth_path = deployment_path / "openspp-docker" / "odoo" / "custom" / "src" / "openg2p_auth"
            if openg2p_auth_path.exists():
                logger.info("Removing existing openg2p_auth directory to avoid conflicts during upgrade")
                import shutil
                shutil.rmtree(str(openg2p_auth_path), ignore_errors=True)
            
            # Fix hardcoded ports in docker-compose.yml
            if not self._fix_docker_compose_ports(deployment):
                logger.warning("Failed to fix docker-compose.yml ports during upgrade")
            
            # Update repos.yaml
            if not self._update_repos_yaml(deployment):
                raise Exception("Failed to update repos.yaml")
            docker_handler = DockerComposeHandler(str(deployment_path / "openspp-docker"), deployment_id)
            
            # Stop services
            docker_handler.stop()
            
            # Run update sequence
            tasks = [("git-aggregate", {})]
            
            if reset_db:
                tasks.append(("resetdb", {}))
            else:
                tasks.append(("update", {}))
            
            tasks.append(("start", {"detach": True}))
            
            for task_name, task_params in tasks:
                # Pre-populate repositories from cache before git-aggregate
                if task_name == "git-aggregate" and self.git_cache:
                    logger.info("Pre-populating repositories from cache for update...")
                    self._prepopulate_repos_from_cache(deployment)
                
                result = self._run_invoke_task(deployment, task_name, task_params)
                if not result.success:
                    raise Exception(f"Task {task_name} failed")
            
            # Wait for services
            if docker_handler.wait_for_services():
                deployment.status = DeploymentStatus.RUNNING
                deployment.last_action = f"Updated to {new_version}"
            else:
                deployment.status = DeploymentStatus.ERROR
                deployment.last_action = "Update failed - services not healthy"
            
            self.db.save_deployment(deployment)
            return True, f"Updated to version {new_version}"
                
        except Exception as e:
            logger.error(f"Failed to update deployment: {e}")
            deployment.status = DeploymentStatus.ERROR
            deployment.last_action = f"Update failed: {str(e)}"
            self.db.save_deployment(deployment)
            return False, str(e)
    
    def stop_deployment(self, deployment_id: str) -> Tuple[bool, str]:
        """Stop a deployment"""
        deployment = self.db.get_deployment(deployment_id)
        if not deployment:
            return False, "Deployment not found"
        
        logger.info(f"Stopping deployment {deployment_id}")
        
        try:
            deployment_path = self._get_deployment_path(deployment_id)
            docker_handler = DockerComposeHandler(str(deployment_path / "openspp-docker"), deployment_id)
            
            result = docker_handler.stop()
            if result.success:
                deployment.status = DeploymentStatus.STOPPED
                deployment.last_action = "Stopped"
                self.db.save_deployment(deployment)
                return True, "Deployment stopped"
            else:
                return False, f"Failed to stop: {result.error}"
                
        except Exception as e:
            logger.error(f"Failed to stop deployment: {e}")
            return False, str(e)
    
    def start_deployment(self, deployment_id: str) -> Tuple[bool, str]:
        """Start a stopped deployment"""
        deployment = self.db.get_deployment(deployment_id)
        if not deployment:
            return False, "Deployment not found"
        
        if deployment.status != DeploymentStatus.STOPPED:
            return False, f"Cannot start deployment in {deployment.status} state"
        
        logger.info(f"Starting deployment {deployment_id}")
        
        try:
            deployment_path = self._get_deployment_path(deployment_id)
            docker_handler = DockerComposeHandler(str(deployment_path / "openspp-docker"), deployment_id)
            
            result = docker_handler.start()
            if result.success:
                if docker_handler.wait_for_services(timeout=300):
                    deployment.status = DeploymentStatus.RUNNING
                    deployment.last_action = "Started"
                else:
                    deployment.status = DeploymentStatus.ERROR
                    deployment.last_action = "Services failed to start"
                
                self.db.save_deployment(deployment)
                return True, "Deployment started"
            else:
                return False, f"Failed to start: {result.error}"
                
        except Exception as e:
            logger.error(f"Failed to start deployment: {e}")
            return False, str(e)
    
    def delete_deployment(self, deployment_id: str) -> Tuple[bool, str]:
        """Delete a deployment completely"""
        from .performance_tracker import PerformanceTracker
        performance_tracker = PerformanceTracker()
        
        with performance_tracker.track_operation(f"DB lookup for deletion {deployment_id}", show_progress=False):
            deployment = self.db.get_deployment(deployment_id)
            if not deployment:
                return False, "Deployment not found"
        
        logger.info(f"Deleting deployment {deployment_id}")
        
        try:
            deployment_path = self._get_deployment_path(deployment_id)
            
            # Remove containers and volumes
            if deployment_path.exists() and (deployment_path / "openspp-docker").exists():
                with performance_tracker.track_operation(f"Docker down with volumes {deployment_id}", show_progress=False):
                    docker_handler = DockerComposeHandler(str(deployment_path / "openspp-docker"), deployment_id)
                    docker_handler.down(volumes=True)
            
            # Remove nginx config
            if self.config.nginx_enabled:
                with performance_tracker.track_operation(f"Remove nginx config {deployment_id}", show_progress=False):
                    self.domain_manager.cleanup_deployment_domain(deployment.id)
            
            # Remove deployment directory
            with performance_tracker.track_operation(f"Remove deployment directory {deployment_id}", show_progress=False):
                cleanup_deployment_directory(str(deployment_path))
            
            # Remove from database
            with performance_tracker.track_operation(f"Remove from DB {deployment_id}", show_progress=False):
                self.db.delete_deployment(deployment_id)
            
            logger.info(f"Deployment {deployment_id} deleted successfully")
            return True, "Deployment deleted"
            
        except Exception as e:
            logger.error(f"Failed to delete deployment: {e}")
            return False, str(e)
    
    def restart_deployment(self, deployment_id: str, quick: bool = False) -> Tuple[bool, str]:
        """Restart a deployment"""
        deployment = self.db.get_deployment(deployment_id)
        if not deployment:
            return False, "Deployment not found"
        
        logger.info(f"Restarting deployment {deployment_id}")
        
        try:
            deployment_path = self._get_deployment_path(deployment_id)
            docker_handler = DockerComposeHandler(str(deployment_path / "openspp-docker"), deployment_id)
            
            if quick:
                # Just restart containers
                result = docker_handler.restart()
            else:
                # Full stop and start
                stop_result = docker_handler.stop()
                if not stop_result.success:
                    return False, f"Failed to stop: {stop_result.error}"
                
                result = docker_handler.start()
            
            if result.success:
                deployment.last_action = "Restarted"
                self.db.save_deployment(deployment)
                return True, "Deployment restarted"
            else:
                return False, f"Failed to restart: {result.error}"
                
        except Exception as e:
            logger.error(f"Failed to restart deployment: {e}")
            return False, str(e)
    
    def execute_task(self, deployment_id: str, task: str, params: Dict = None) -> TaskResult:
        """Execute an invoke task on deployment"""
        deployment = self.db.get_deployment(deployment_id)
        if not deployment:
            return TaskResult(success=False, output="", error="Deployment not found")
        
        logger.info(f"Executing task {task} on {deployment_id}")
        
        # Execute task
        result = self._run_invoke_task(deployment, task, params or {})
        
        # Update deployment
        deployment.last_action = f"Executed {task}"
        self.db.save_deployment(deployment)
        
        return result
    
    def get_deployment_status(self, deployment_id: str) -> Dict:
        """Get detailed deployment status"""
        from .performance_tracker import PerformanceTracker
        performance_tracker = PerformanceTracker()
        
        with performance_tracker.track_operation(f"DB lookup for {deployment_id}", show_progress=False):
            deployment = self.db.get_deployment(deployment_id)
            if not deployment:
                return {}
        
        with performance_tracker.track_operation(f"Create DockerHandler for {deployment_id}", show_progress=False):
            docker_handler = DockerComposeHandler(
                str(self._get_deployment_path(deployment_id) / "openspp-docker"), 
                deployment_id
            )
        
        with performance_tracker.track_operation(f"Get container status for {deployment_id}", show_progress=False):
            container_status = docker_handler.get_container_status()
            
        with performance_tracker.track_operation(f"Get container stats for {deployment_id}", show_progress=False):
            container_stats = docker_handler.get_container_stats()
        
        return {
            "deployment": deployment.to_dict(),
            "containers": container_status,
            "stats": container_stats,
            "logs": {}  # Could add recent logs here
        }
    
    def get_deployment_logs(self, deployment_id: str, service: str = None, 
                           tail: int = 100) -> str:
        """Get deployment logs"""
        deployment = self.db.get_deployment(deployment_id)
        if not deployment:
            return "Deployment not found"
        
        deployment_path = self._get_deployment_path(deployment_id)
        docker_handler = DockerComposeHandler(str(deployment_path / "openspp-docker"), deployment_id)
        
        result = docker_handler.logs(service=service, tail=tail)
        return result.output if result.success else result.error
    
    def get_all_deployments(self) -> List[Deployment]:
        """Get all deployments"""
        return self.db.get_all_deployments()
    
    def get_deployments_by_tester(self, tester_email: str) -> List[Deployment]:
        """Get deployments for a specific tester"""
        return self.db.get_deployments_by_tester(tester_email)
    
    def get_deployment_by_id(self, deployment_id: str) -> Optional[Deployment]:
        """Get deployment by ID"""
        return self.db.get_deployment(deployment_id)
    
    def get_deployment_metrics(self) -> Dict:
        """Get deployment metrics"""
        all_deployments = self.db.get_all_deployments()
        
        return {
            "total": len(all_deployments),
            "running": len([d for d in all_deployments if d.status == DeploymentStatus.RUNNING]),
            "stopped": len([d for d in all_deployments if d.status == DeploymentStatus.STOPPED]),
            "error": len([d for d in all_deployments if d.status == DeploymentStatus.ERROR]),
            "by_tester": {},
            "by_version": {},
            "port_usage": self.db.get_port_usage_stats()
        }
    
    def cleanup_orphaned_resources(self):
        """Clean up orphaned Docker resources"""
        logger.info("Cleaning up orphaned resources")
        
        # Get all deployment IDs from database
        db_deployments = {d.id for d in self.db.get_all_deployments()}
        
        # Check for orphaned containers
        try:
            result = run_command(["docker", "ps", "-a", "--format", "json"])
            if result.returncode == 0:
                # Parse and check containers
                pass
        except Exception as e:
            logger.error(f"Failed to cleanup resources: {e}")
    
    def _check_deployment_limits(self, tester_email: str) -> bool:
        """Check if tester can create more deployments"""
        current_count = self.db.count_tester_deployments(tester_email)
        return current_count < self.config.max_deployments_per_tester
    
    def _generate_subdomain(self, deployment_id: str) -> str:
        """Generate subdomain for deployment"""
        return f"{deployment_id}.{self.config.base_domain}"
    
    def _get_deployment_path(self, deployment_id: str) -> Path:
        """Get deployment directory path"""
        return Path(self.config.base_deployment_path).resolve() / deployment_id
    
    def _update_repos_yaml(self, deployment: Deployment) -> bool:
        """Update repos.yaml with deployment versions"""
        repos_yaml_path = (
            self._get_deployment_path(deployment.id) / 
            "openspp-docker" / "odoo" / "custom" / "src" / "repos.yaml"
        )
        
        try:
            repos = read_yaml_file(str(repos_yaml_path))
            
            # Remove openg2p-auth repository to avoid duplicate modules conflict
            # The modules in openg2p-auth are already present in openg2p-registry
            if 'openg2p_auth' in repos:
                logger.info("Removing openg2p_auth from repos.yaml to avoid duplicate modules")
                del repos['openg2p_auth']
            
            # Update openspp_modules version
            if 'openspp_modules' in repos and deployment.openspp_version:
                # Get the remote name from the current configuration
                remote_name = 'openspp'
                if 'remotes' in repos['openspp_modules']:
                    remote_name = list(repos['openspp_modules']['remotes'].keys())[0]
                
                repos['openspp_modules']['target'] = f"{remote_name} {deployment.openspp_version}"
                repos['openspp_modules']['merges'] = [f"{remote_name} {deployment.openspp_version}"]
            
            # Update dependency versions if specified
            for dep, version in deployment.dependency_versions.items():
                if dep in repos and version:
                    # Handle organization prefix for OpenG2P repos
                    if '/' in version and dep.startswith('openg2p_'):
                        # Parse organization and version
                        org_prefix, actual_version = version.split('/', 1)
                        
                        # Update remote URL based on organization
                        if 'remotes' in repos[dep]:
                            current_remote = list(repos[dep]['remotes'].keys())[0]
                            current_url = repos[dep]['remotes'][current_remote]
                            
                            if org_prefix == 'OpenG2P':
                                # Use original OpenG2P repo
                                new_url = current_url.replace('OpenSPP', 'openg2p')
                            else:
                                # Use OpenSPP fork
                                new_url = current_url.replace('openg2p', 'OpenSPP')
                            
                            repos[dep]['remotes'][current_remote] = new_url
                        
                        # Update target and merges with actual version (without prefix)
                        remote_name = list(repos[dep]['remotes'].keys())[0] if 'remotes' in repos[dep] else 'origin'
                        repos[dep]['target'] = f"{remote_name} {actual_version}"
                        repos[dep]['merges'] = [f"{remote_name} {actual_version}"]
                    else:
                        # Non-OpenG2P repos or no prefix - handle normally
                        remote_name = 'origin'
                        if 'remotes' in repos[dep]:
                            remote_name = list(repos[dep]['remotes'].keys())[0]
                        
                        # Update both target and merges
                        repos[dep]['target'] = f"{remote_name} {version}"
                        repos[dep]['merges'] = [f"{remote_name} {version}"]
            
            return write_yaml_file(str(repos_yaml_path), repos)
            
        except Exception as e:
            logger.error(f"Failed to update repos.yaml: {e}")
            return False
    
    def _generate_env_file(self, deployment: Deployment) -> bool:
        """Generate .env file for deployment"""
        env_path = self._get_deployment_path(deployment.id) / ".env"
        
        try:
            config_dict = {
                'docker_cpu_limit': self.config.docker_cpu_limit,
                'docker_memory_limit': self.config.docker_memory_limit
            }
            
            env_content = generate_env_content(
                deployment.id,
                deployment.port_base,
                config_dict
            )
            
            with open(env_path, 'w') as f:
                f.write(env_content)
            
            return True
            
        except Exception as e:
            logger.error(f"Failed to generate .env file: {e}")
            return False
    
    def _fix_docker_compose_ports(self, deployment: Deployment) -> bool:
        """Fix hardcoded ports in docker-compose.yml to use environment variables"""
        docker_compose_path = (
            self._get_deployment_path(deployment.id) / 
            "openspp-docker" / "docker-compose.yml"
        )
        
        if not docker_compose_path.exists():
            logger.error(f"docker-compose.yml not found at {docker_compose_path}")
            return False
        
        try:
            with open(docker_compose_path, 'r') as f:
                content = f.read()
            
            # Replace hardcoded ports with environment variables
            # Pattern: 127.0.0.1:XXXXX: where XXXXX is a port number
            import re
            
            # Common service port replacements - with or without quotes
            replacements = [
                # SMTP port 
                (r'(["\']*127\.0\.0\.1:)\d{5}(:8025["\']*)', r'\g<1>${SMTP_PORT}\g<2>'),
                # PGWeb port
                (r'(["\']*127\.0\.0\.1:)\d{5}(:8081["\']*)', r'\g<1>${PGWEB_PORT}\g<2>'),
                # Debugger port
                (r'(["\']*127\.0\.0\.1:)\d{5}(:1984["\']*)', r'\g<1>${DEBUGGER_PORT}\g<2>'),
                # Odoo main port
                (r'(["\']*127\.0\.0\.1:)\d{5}(:8069["\']*)', r'\g<1>${ODOO_PORT}\g<2>'),
                # Odoo longpolling port
                (r'(["\']*127\.0\.0\.1:)\d{5}(:8072["\']*)', r'\g<1>${ODOO_PORT_LONGPOLLING}\g<2>'),
                # Odoo proxy admin port
                (r'(["\']*127\.0\.0\.1:)\d{5}(:6899["\']*)', r'\g<1>${ODOO_PROXY_PORT}\g<2>'),
                # DB port
                (r'(["\']*127\.0\.0\.1:)\d{5}(:5432["\']*)', r'\g<1>${DB_PORT}\g<2>'),
            ]
            
            modified = False
            for pattern, replacement in replacements:
                if re.search(pattern, content):
                    content = re.sub(pattern, replacement, content)
                    modified = True
            
            if modified:
                with open(docker_compose_path, 'w') as f:
                    f.write(content)
                logger.info(f"Fixed hardcoded ports in docker-compose.yml for {deployment.id}")
                return True
            else:
                logger.info("No hardcoded ports found to fix in docker-compose.yml")
                return True
                
        except Exception as e:
            logger.error(f"Failed to fix docker-compose.yml ports: {e}")
            return False
    
    def _generate_docker_override(self, deployment: Deployment) -> bool:
        """Generate docker-compose.override.yml for any custom configuration"""
        override_path = (
            self._get_deployment_path(deployment.id) / 
            "openspp-docker" / "docker-compose.override.yml"
        )
        
        try:
            # Create minimal override configuration
            # Ports are now handled via environment variables in the main docker-compose.yml
            override_config = {
                'version': '3.4',
                'services': {
                    # Add any service-specific overrides here if needed
                    # For now, we don't need port overrides since they use env vars
                }
            }
            
            # Write override file
            return write_yaml_file(str(override_path), override_config)
            
        except Exception as e:
            logger.error(f"Failed to generate docker-compose override: {e}")
            return False
    
    def _run_invoke_task(self, deployment: Deployment, task: str, 
                        params: Dict[str, str]) -> TaskResult:
        """Run invoke task in deployment directory"""
        # Always use absolute paths
        deployment_path = self._get_deployment_path(deployment.id)
        working_dir = (deployment_path / "openspp-docker").resolve()
        
        # Ensure working directory exists
        if not working_dir.exists():
            logger.error(f"Working directory does not exist: {working_dir}")
            return TaskResult(
                success=False,
                output="",
                error=f"Directory not found: {working_dir}",
                execution_time=0.0
            )
        
        # Get log file for this deployment
        from .utils import get_deployment_log_file
        log_file = get_deployment_log_file(str(deployment_path), "deployment_commands")
        
        # Build command
        cmd = ["invoke", task]
        for key, value in params.items():
            if value is not None and value != "":
                # Handle boolean values - add flag without value if True
                if isinstance(value, bool):
                    if value:
                        cmd.append(f"--{key}")
                else:
                    cmd.extend([f"--{key}", str(value)])
        
        # Set environment
        env = os.environ.copy()
        env.update({
            "UID": str(os.getuid()),
            "GID": str(os.getgid())
        })
        
        # Load .env file
        env_file = deployment_path / ".env"
        if env_file.exists():
            with open(env_file, 'r') as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith('#') and '=' in line:
                        key, value = line.split('=', 1)
                        env[key.strip()] = value.strip()
        
        # Run command with retry for invoke tasks and log output
        start_time = time.time()
        result = run_command_with_retry(cmd, cwd=str(working_dir), env=env, log_file=str(log_file))
        execution_time = time.time() - start_time
        
        # If command failed, include more details in the error message
        error_msg = result.stderr
        if result.returncode != 0 and not error_msg:
            error_msg = f"Command failed with exit code {result.returncode}. Check {log_file} for details."
        
        return TaskResult(
            success=result.returncode == 0,
            output=result.stdout,
            error=error_msg,
            execution_time=execution_time
        )
    
    def _cleanup_failed_deployment(self, deployment: Deployment):
        """Clean up resources for failed deployment"""
        if self.config.dev_mode:
            logger.info(f"Dev mode enabled: preserving failed deployment {deployment.id} for debugging")
            logger.info(f"Logs available in: {self._get_deployment_path(deployment.id) / 'logs'}")
            # Still stop containers to free resources, but preserve files
            try:
                docker_handler = DockerComposeHandler(
                    str(self._get_deployment_path(deployment.id) / "openspp-docker"), 
                    deployment.id
                )
                docker_handler.down(volumes=True)
                logger.info(f"Stopped containers for failed deployment {deployment.id}")
            except Exception as e:
                logger.warning(f"Failed to stop containers for {deployment.id}: {e}")
            return
        
        # Normal cleanup for production
        logger.info(f"Cleaning up failed deployment {deployment.id}")
        try:
            # Try to stop any running containers
            docker_handler = DockerComposeHandler(
                str(self._get_deployment_path(deployment.id) / "openspp-docker"), 
                deployment.id
            )
            docker_handler.down(volumes=True)
        except:
            pass
        
        # Remove deployment directory
        deployment_path = self._get_deployment_path(deployment.id)
        if deployment_path.exists():
            cleanup_deployment_directory(str(deployment_path))
        
        # Remove nginx config
        if self.config.nginx_enabled:
            self.domain_manager.cleanup_deployment_domain(deployment.id)
        
        # Free port allocation
        self.db.delete_deployment(deployment.id)
    
    def _refresh_available_versions(self):
        """Refresh list of available OpenSPP versions (branches and tags)"""
        try:
            versions = []
            
            if self.git_cache:
                # Use git cache for faster access
                repo_url = "https://github.com/openspp/openspp-modules.git"
                
                # Get ALL branches
                branches = self.git_cache.get_available_branches(repo_url)
                versions.extend(branches)  # Add all branches
                
                # Get ALL tags
                tags = self.git_cache.get_available_tags(repo_url)
                versions.extend(tags)  # Add all tags
            else:
                # Fallback to direct git commands
                # Get branches
                result = run_command_with_retry([
                    "git", "ls-remote", "--heads", 
                    "https://github.com/openspp/openspp-modules.git"
                ])
                
                if result.returncode == 0:
                    for line in result.stdout.strip().split('\n'):
                        if 'refs/heads/' in line:
                            branch = line.split('refs/heads/')[-1]
                            # Include all branches, not just specific ones
                            versions.append(branch)
                
                # Get tags
                result = run_command_with_retry([
                    "git", "ls-remote", "--tags", 
                    "https://github.com/openspp/openspp-modules.git"
                ])
                
                if result.returncode == 0:
                    for line in result.stdout.strip().split('\n'):
                        if 'refs/tags/' in line and '^{}' not in line:
                            tag = line.split('refs/tags/')[-1]
                            # Include ALL tags
                            versions.append(tag)
            
            # Remove duplicates
            unique_versions = list(set(versions))
            
            # Separate into categories
            branch_17 = ["17.0"] if "17.0" in unique_versions else []
            
            # Identify tags vs branches - tags typically have version numbers or specific prefixes
            def is_likely_tag(version):
                # Tags often start with v followed by version numbers
                import re
                return (
                    version.startswith("v") or  # Most tags start with v
                    version.startswith("openspp-") or  # In case there are any openspp- tags
                    (re.search(r'\d+\.\d+\.\d+', version) and not version in ["15.0", "17.0"])  # Has semantic version but not branch names
                )
            
            tags = sorted([v for v in unique_versions if is_likely_tag(v) and v != "17.0"], reverse=True)
            other_branches = sorted([v for v in unique_versions 
                                   if v not in branch_17 + tags])
            
            # Combine in priority order: 17.0 first, then tags (newest first), then other branches
            self.config.available_openspp_versions = branch_17 + tags + other_branches
            logger.info(f"Found {len(self.config.available_openspp_versions)} OpenSPP versions")
            logger.debug(f"Branches: {other_branches[:10]}")  # Log first 10 branches
            logger.debug(f"Tags: {tags[:10]}")  # Log first 10 tags
            
        except Exception as e:
            logger.error(f"Failed to fetch OpenSPP versions: {e}")
            # Leave empty if fetch fails - UI will handle this
            self.config.available_openspp_versions = []
    
    def get_available_dependency_branches(self, repo_name: str) -> List[str]:
        """Get available branches for a dependency from both OpenSPP and OpenG2P repos"""
        branches = []
        
        # Define both OpenSPP fork and original OpenG2P URLs
        if repo_name.startswith('openg2p_'):
            repo_urls = {
                "OpenSPP": f"https://github.com/OpenSPP/{repo_name.replace('_', '-')}.git",
                "OpenG2P": f"https://github.com/openg2p/{repo_name.replace('_', '-')}.git"
            }
        else:
            # Non-OpenG2P repo
            return []
        
        for org, repo_url in repo_urls.items():
            try:
                result = run_command_with_retry([
                    "git", "ls-remote", "--heads", repo_url
                ])
                
                if result.returncode == 0:
                    for line in result.stdout.strip().split('\n'):
                        if 'refs/heads/' in line:
                            branch = line.split('refs/heads/')[-1]
                            # Add with organization prefix
                            branches.append(f"{org}/{branch}")
                
                # Also get tags
                result = run_command_with_retry([
                    "git", "ls-remote", "--tags", repo_url
                ])
                
                if result.returncode == 0:
                    for line in result.stdout.strip().split('\n'):
                        if 'refs/tags/' in line and '^{}' not in line:
                            tag = line.split('refs/tags/')[-1]
                            branches.append(f"{org}/{tag}")
                            
            except Exception as e:
                logger.debug(f"Failed to fetch branches for {repo_name} from {org}: {e}")
        
        return sorted(branches)
    
    def _get_single_repo_versions(self, repo_info: Tuple[str, str]) -> Tuple[str, List[str]]:
        """Get versions for a single repository - helper for parallel processing"""
        repo_name, remote_url = repo_info
        
        try:
            versions = []
            
            if self.git_cache:
                # Get branches and tags from cache
                branches = self.git_cache.get_available_branches(remote_url)
                tags = self.git_cache.get_available_tags(remote_url)
                
                # For OpenG2P repos, also fetch from the original OpenG2P organization
                if repo_name.startswith('openg2p_') and 'OpenSPP' in remote_url:
                    # Sort to put more recent versions first (reverse alphabetical often correlates with recency)
                    sorted_branches = sorted(branches, reverse=True)
                    sorted_tags = sorted(tags, reverse=True)
                    
                    # Add OpenSPP versions with prefix
                    for v in sorted_branches + sorted_tags:
                        versions.append(f"OpenSPP/{v}")
                    
                    # Also fetch from original OpenG2P repo
                    original_url = remote_url.replace('OpenSPP', 'openg2p')
                    try:
                        g2p_branches = self.git_cache.get_available_branches(original_url)
                        g2p_tags = self.git_cache.get_available_tags(original_url)
                        
                        # Sort OpenG2P versions too
                        sorted_g2p_branches = sorted(g2p_branches, reverse=True)
                        sorted_g2p_tags = sorted(g2p_tags, reverse=True)
                        
                        for v in sorted_g2p_branches + sorted_g2p_tags:
                            versions.append(f"OpenG2P/{v}")
                    except Exception as e:
                        logger.debug(f"Could not fetch from OpenG2P repo for {repo_name}: {e}")
                else:
                    # Non-OpenG2P repos - no prefix needed
                    versions = sorted(branches, reverse=True) + sorted(tags, reverse=True)
                
                return repo_name, versions
            else:
                # No cache available
                return repo_name, []
        except Exception as e:
            logger.debug(f"Failed to get versions for {repo_name}: {e}")
            return repo_name, []
    
    def get_available_dependencies(self) -> Dict[str, List[str]]:
        """Get all available dependencies from repos.yaml template"""
        from src.performance_tracker import performance_tracker
        
        try:
            # Use a cached openspp-docker repo or clone a temporary one
            if self.git_cache:
                with performance_tracker.track_operation("Update openspp-docker Git Cache", show_progress=False):
                    self.git_cache.update_or_clone_repo(
                        self.config.openspp_docker_repo,
                        self.config.default_branch
                    )
                    repo_path = self.git_cache.get_cached_repo_path(self.config.openspp_docker_repo)
            else:
                # Create temp clone
                import tempfile
                temp_dir = tempfile.mkdtemp()
                repo = git.Repo.clone_from(
                    self.config.openspp_docker_repo,
                    temp_dir,
                    branch=self.config.default_branch,
                    depth=1
                )
                repo_path = Path(temp_dir)
            
            # Read repos.yaml
            repos_yaml_path = repo_path / "odoo" / "custom" / "src" / "repos.yaml"
            if repos_yaml_path.exists():
                with performance_tracker.track_operation("Read repos.yaml file", show_progress=False):
                    repos = read_yaml_file(str(repos_yaml_path))
                
                dependencies = {}
                
                # Prepare repository info for parallel processing
                repo_infos = []
                for repo_name, repo_config in repos.items():
                    if repo_name == './odoo':
                        continue  # Skip odoo itself
                    
                    if 'remotes' in repo_config:
                        # Get repository URL
                        for remote_name, remote_url in repo_config['remotes'].items():
                            repo_infos.append((repo_name, remote_url))
                            break
                
                repo_count = len(repo_infos)
                if repo_count > 0 and self.git_cache:
                    # Use ThreadPoolExecutor to fetch versions for all repos in parallel
                    with performance_tracker.track_operation(f"Fetch versions for {repo_count} dependency repos (parallel)", show_progress=True, expected_duration=2.0):
                        # Limit max workers to avoid overwhelming git operations
                        max_workers = min(repo_count, 6)  # Max 6 concurrent git operations
                        
                        with ThreadPoolExecutor(max_workers=max_workers) as executor:
                            # Submit all repo version requests
                            future_to_repo = {
                                executor.submit(self._get_single_repo_versions, repo_info): repo_info 
                                for repo_info in repo_infos
                            }
                            
                            # Collect results as they complete
                            for future in as_completed(future_to_repo):
                                try:
                                    repo_name, versions = future.result()
                                    dependencies[repo_name] = versions
                                except Exception as e:
                                    repo_info = future_to_repo[future]
                                    repo_name = repo_info[0]
                                    logger.debug(f"Failed to get versions for {repo_name}: {e}")
                                    dependencies[repo_name] = []
                else:
                    # No cache - use fallback method for OpenG2P repos
                    for repo_name, repo_config in repos.items():
                        if repo_name != './odoo' and 'remotes' in repo_config:
                            if repo_name.startswith('openg2p_'):
                                # Use the fallback method that fetches from both orgs
                                dependencies[repo_name] = self.get_available_dependency_branches(repo_name)
                            else:
                                dependencies[repo_name] = []
                
                # Clean up temp dir if created
                if not self.git_cache and 'temp_dir' in locals():
                    shutil.rmtree(temp_dir)
                
                return dependencies
                
        except Exception as e:
            logger.error(f"Failed to get available dependencies: {e}")
            
        return {}
    
    def _prepopulate_repos_from_cache(self, deployment: Deployment):
        """Pre-populate repositories from git cache before running git-aggregate"""
        if not self.git_cache:
            return
        
        # Always use absolute paths
        deployment_path = self._get_deployment_path(deployment.id)
        repos_yaml_path = (
            deployment_path / "openspp-docker" / "odoo" / "custom" / "src" / "repos.yaml"
        )
        src_path = deployment_path / "openspp-docker" / "odoo" / "custom" / "src"
        
        try:
            # Read repos.yaml
            repos = read_yaml_file(str(repos_yaml_path))
            
            # Pre-populate each repository from cache
            for repo_name, repo_config in repos.items():
                # Note: ./odoo is the main Odoo repository (~2GB) - we should cache it!
                # Removed skip to enable caching of the large Odoo repo
                
                # Skip openg2p_auth to avoid duplicate modules conflict
                if repo_name == 'openg2p_auth':
                    logger.info("Skipping openg2p_auth to avoid duplicate modules")
                    continue
                
                if 'remotes' in repo_config:
                    # Get the first remote URL
                    for remote_name, remote_url in repo_config['remotes'].items():
                        logger.info(f"Pre-populating {repo_name} from cache...")
                        
                        # Update cache first
                        self.git_cache.update_or_clone_repo(remote_url)
                        
                        # Copy to destination
                        dest_path = src_path / repo_name
                        if not dest_path.exists():
                            self.git_cache.copy_to_destination(
                                remote_url, 
                                str(dest_path),
                                exclude_git=False  # Keep .git for git-aggregate
                            )
                            logger.info(f"Copied {repo_name} from cache")
                        break  # Only process first remote
            
            logger.info("Repository pre-population completed")
            
        except Exception as e:
            logger.warning(f"Failed to pre-populate repos from cache: {e}")
            # Not critical - git-aggregate will clone normally
    
    def fix_deployment_ports(self, deployment_id: str) -> Tuple[bool, str]:
        """Fix port configuration for existing deployment"""
        deployment = self.db.get_deployment(deployment_id)
        if not deployment:
            return False, "Deployment not found"
        
        logger.info(f"Fixing port configuration for {deployment_id}")
        
        try:
            # Fix hardcoded ports in docker-compose.yml
            if not self._fix_docker_compose_ports(deployment):
                return False, "Failed to fix docker-compose.yml ports"
            
            # Regenerate .env file with correct ports
            if not self._generate_env_file(deployment):
                return False, "Failed to regenerate .env file"
            
            # Copy .env file to openspp-docker directory
            deployment_path = self._get_deployment_path(deployment_id)
            env_src = deployment_path / ".env"
            env_dst = deployment_path / "openspp-docker" / ".env"
            if env_src.exists():
                import shutil
                shutil.copy2(str(env_src), str(env_dst))
            
            # Generate docker-compose.override.yml (minimal, ports via env vars)
            if self._generate_docker_override(deployment):
                return True, f"Port configuration fixed. Restart deployment to apply changes."
            else:
                return False, "Failed to generate port override"
        except Exception as e:
            logger.error(f"Failed to fix ports: {e}")
            return False, str(e)
    
    def get_deployment_command_logs(self, deployment_id: str, date: str = None) -> str:
        """Get command logs for a deployment"""
        deployment_path = self._get_deployment_path(deployment_id)
        logs_dir = deployment_path / "logs"
        
        if not logs_dir.exists():
            return "No logs directory found for this deployment."
        
        # Use today's date if not specified
        if not date:
            date = time.strftime('%Y%m%d')
        
        log_file = logs_dir / f"deployment_commands_{date}.log"
        
        if not log_file.exists():
            # List available log files
            available_logs = sorted(logs_dir.glob("deployment_commands_*.log"))
            if available_logs:
                files_list = "\n".join([f.name for f in available_logs])
                return f"No logs found for {date}. Available log files:\n{files_list}"
            else:
                return "No command logs found for this deployment."
        
        try:
            with open(log_file, 'r') as f:
                return f.read()
        except Exception as e:
            logger.error(f"Failed to read log file {log_file}: {e}")
            return f"Error reading log file: {e}"
    
    def get_deployment_debug_logs(self, deployment_id: str, date: str = None) -> str:
        """Get debug command logs for a deployment (shows command timing and results)"""
        deployment_path = self._get_deployment_path(deployment_id)
        logs_dir = deployment_path / "logs"
        
        if not logs_dir.exists():
            return "No logs directory found for this deployment."
        
        # Use today's date if not specified
        if not date:
            date = time.strftime('%Y%m%d')
        
        log_file = logs_dir / f"debug_commands_{date}.log"
        
        if not log_file.exists():
            # List available debug log files
            available_logs = sorted(logs_dir.glob("debug_commands_*.log"))
            if available_logs:
                files_list = "\n".join([f.name for f in available_logs])
                return f"No debug logs found for {date}. Available debug log files:\n{files_list}"
            else:
                return "No debug command logs found for this deployment."
        
        try:
            with open(log_file, 'r') as f:
                content = f.read()
                if not content.strip():
                    return "Debug log file is empty (no commands executed yet)."
                return content
        except Exception as e:
            logger.error(f"Failed to read debug log file {log_file}: {e}")
            return f"Error reading debug log file: {e}"
    
    def get_app_command_logs(self, date: str = None) -> str:
        """Get main application command logs (non-deployment specific commands)"""
        logs_dir = Path(__file__).parent.parent / "logs"
        
        if not logs_dir.exists():
            return "No main app logs directory found. App commands will create it automatically."
        
        # Use today's date if not specified
        if not date:
            date = time.strftime('%Y%m%d')
        
        log_file = logs_dir / f"app_commands_{date}.log"
        
        if not log_file.exists():
            # List available app log files
            available_logs = sorted(logs_dir.glob("app_commands_*.log"))
            if available_logs:
                files_list = "\n".join([f.name for f in available_logs])
                return f"No app logs found for {date}. Available app log files:\n{files_list}"
            else:
                return "No app command logs found yet. These are created when general app commands are executed."
        
        try:
            with open(log_file, 'r') as f:
                content = f.read()
                if not content.strip():
                    return "App log file is empty (no general app commands executed yet)."
                return content
        except Exception as e:
            logger.error(f"Failed to read app log file {log_file}: {e}")
            return f"Error reading app log file: {e}"
    
    def sync_deployment_states(self):
        """Sync deployment states with actual Docker container states"""
        logger.info("=== Starting deployment state sync ===")
        
        # Test command logging with a simple git command
        from src.utils import run_command
        test_result = run_command(["git", "--version"])
        logger.info(f"Test command executed - git version: {test_result.returncode}")
        
        deployments = self.db.get_all_deployments()
        logger.info(f"Found {len(deployments)} deployments to sync")
        
        for deployment in deployments:
            try:
                logger.info(f"--- Processing deployment: {deployment.id} (Current DB status: {deployment.status}) ---")
                
                docker_handler = DockerComposeHandler(
                    str(self._get_deployment_path(deployment.id) / "openspp-docker"),
                    deployment.id
                )
                
                # Get container states
                container_status = docker_handler.get_container_status()
                logger.info(f"Container status for {deployment.id}: {container_status}")
                
                # Update deployment status based on container states
                if not container_status:
                    # No containers found
                    logger.warning(f"No containers found for {deployment.id}")
                    if deployment.status == DeploymentStatus.RUNNING:
                        logger.info(f"Marking {deployment.id} as STOPPED (no containers)")
                        deployment.status = DeploymentStatus.STOPPED
                        deployment.last_action = "Containers not found"
                else:
                    # Check if main services are running
                    logger.info(f"Checking services in {deployment.id}:")
                    for name, status in container_status.items():
                        logger.info(f"  - Service '{name}': state='{status.get('state')}', status='{status.get('status')}'")
                    
                    odoo_running = any(
                        'odoo' in name and status.get('state') == 'running'
                        for name, status in container_status.items()
                    )
                    logger.info(f"Odoo running check for {deployment.id}: {odoo_running}")
                    
                    if odoo_running and deployment.status != DeploymentStatus.RUNNING:
                        logger.info(f"Updating {deployment.id} to RUNNING (odoo is running)")
                        deployment.status = DeploymentStatus.RUNNING
                        deployment.last_action = "State synced - running"
                    elif not odoo_running and deployment.status == DeploymentStatus.RUNNING:
                        logger.info(f"Updating {deployment.id} to STOPPED (odoo not running)")
                        deployment.status = DeploymentStatus.STOPPED
                        deployment.last_action = "State synced - stopped"
                    else:
                        logger.info(f"No status change needed for {deployment.id}")
                
                logger.info(f"Saving {deployment.id} with status: {deployment.status}")
                self.db.save_deployment(deployment)
                
            except Exception as e:
                logger.error(f"Failed to sync state for {deployment.id}: {e}", exc_info=True)