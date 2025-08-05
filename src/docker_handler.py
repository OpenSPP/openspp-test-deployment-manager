# ABOUTME: Docker and Docker Compose operations handler
# ABOUTME: Manages container lifecycle, monitoring, and resource management

import os
import subprocess
import logging
import json
from typing import Dict, List, Optional, Tuple
from pathlib import Path
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import docker
from docker.errors import NotFound, APIError

from src.utils import run_command, run_command_with_retry, format_docker_project_name, get_deployment_log_file
from src.models import TaskResult

logger = logging.getLogger(__name__)


class DockerComposeHandler:
    """Handle Docker Compose operations for deployments"""
    
    def __init__(self, deployment_path: str, deployment_id: str):
        self.deployment_path = str(Path(deployment_path).resolve())
        self.deployment_id = deployment_id
        self.compose_path = str(Path(deployment_path).resolve())  # Path already includes openspp-docker
        self.project_name = format_docker_project_name(deployment_id)
        
        # Setup deployment path for logging
        self.deployment_base_path = Path(deployment_path).parent
        
        # Initialize Docker client
        try:
            self.docker_client = docker.from_env()
        except Exception as e:
            logger.error(f"Failed to initialize Docker client: {e}")
            self.docker_client = None
    
    def _get_compose_command(self) -> List[str]:
        """Get the appropriate docker compose command"""
        # Try docker compose v2 first
        result = run_command(["docker", "compose", "version"], capture_output=True)
        if result.returncode == 0:
            return ["docker", "compose"]
        
        # Fall back to docker-compose v1
        return ["docker-compose"]
    
    def _get_compose_env(self) -> Dict[str, str]:
        """Get environment variables for compose commands"""
        env = os.environ.copy()
        env.update({
            "UID": str(os.getuid()),
            "GID": str(os.getgid()),
            "COMPOSE_PROJECT_NAME": self.project_name
        })
        
        # Load .env file if exists
        env_file = f"{self.deployment_path}/.env"
        if os.path.exists(env_file):
            with open(env_file, 'r') as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith('#') and '=' in line:
                        key, value = line.split('=', 1)
                        env[key.strip()] = value.strip()
        
        return env
    
    def _get_log_file_path(self) -> str:
        """Get log file path for docker commands"""
        return get_deployment_log_file(str(self.deployment_base_path), "docker_commands")
    
    def run_compose_command(self, args: List[str], capture_output: bool = True) -> TaskResult:
        """Run a docker-compose command"""
        compose_cmd = self._get_compose_command()
        cmd = compose_cmd + args
        
        start_time = time.time()
        # Use retry for docker-compose commands with full logging
        result = run_command_with_retry(
            cmd,
            cwd=self.compose_path,
            env=self._get_compose_env(),
            capture_output=capture_output,
            log_file=self._get_log_file_path()
        )
        execution_time = time.time() - start_time
        
        return TaskResult(
            success=result.returncode == 0,
            output=result.stdout,
            error=result.stderr,
            execution_time=execution_time
        )
    
    def start(self, detach: bool = True) -> TaskResult:
        """Start all services"""
        args = ["up"]
        if detach:
            args.append("-d")
        
        logger.info(f"Starting deployment {self.deployment_id}")
        return self.run_compose_command(args)
    
    def stop(self) -> TaskResult:
        """Stop all services"""
        logger.info(f"Stopping deployment {self.deployment_id}")
        return self.run_compose_command(["stop"])
    
    def down(self, volumes: bool = False) -> TaskResult:
        """Stop and remove containers"""
        args = ["down"]
        if volumes:
            args.append("-v")
        
        logger.info(f"Removing deployment {self.deployment_id}")
        return self.run_compose_command(args)
    
    def restart(self, service: str = None) -> TaskResult:
        """Restart services"""
        args = ["restart"]
        if service:
            args.append(service)
        
        logger.info(f"Restarting {'service ' + service if service else 'all services'} for {self.deployment_id}")
        return self.run_compose_command(args)
    
    def logs(self, service: str = None, tail: int = 100, follow: bool = False) -> TaskResult:
        """Get logs from services"""
        args = ["logs"]
        
        if tail:
            args.extend(["--tail", str(tail)])
        
        if follow:
            args.append("-f")
        
        if service:
            args.append(service)
        
        return self.run_compose_command(args)
    
    def ps(self) -> TaskResult:
        """List containers"""
        return self.run_compose_command(["ps", "--format", "json"])
    
    def exec_command(self, service: str, command: List[str]) -> TaskResult:
        """Execute command in a service container"""
        args = ["exec", "-T", service] + command
        return self.run_compose_command(args)
    
    def get_container_status(self) -> Dict[str, Dict]:
        """Get status of all containers in deployment"""
        from .performance_tracker import PerformanceTracker
        performance_tracker = PerformanceTracker()
        
        status = {}
        
        if not self.docker_client:
            return status
        
        try:
            # Get containers for this project
            with performance_tracker.track_operation(f"List containers for {self.project_name}", show_progress=False):
                containers = self.docker_client.containers.list(
                    all=True,
                    filters={"label": f"com.docker.compose.project={self.project_name}"}
                )
            
            with performance_tracker.track_operation(f"Inspect {len(containers)} containers for {self.project_name}", show_progress=False):
                for container in containers:
                    service = container.labels.get("com.docker.compose.service", "unknown")
                    
                    status[service] = {
                        "id": container.short_id,
                        "name": container.name,
                        "status": container.status,
                        "state": container.attrs['State']['Status'],
                        "health": self._get_container_health(container),
                        "created": container.attrs['Created'],
                        "started": container.attrs['State'].get('StartedAt'),
                        "ports": container.attrs['NetworkSettings']['Ports']
                    }
                
        except Exception as e:
            logger.error(f"Failed to get container status: {e}")
        
        return status
    
    def _get_single_container_stats(self, container) -> Tuple[str, Dict]:
        """Get stats for a single container - helper for parallel processing"""
        service = container.labels.get("com.docker.compose.service", "unknown")
        
        try:
            # Skip unhealthy containers to avoid API hangs
            health = self._get_container_health(container)
            if health == "unhealthy":
                logger.debug(f"Skipping stats for unhealthy container: {service}")
                return service, {
                    "cpu_percent": 0,
                    "memory_usage": 0,
                    "memory_limit": 0,
                    "memory_percent": 0,
                    "status": "unhealthy"
                }
            
            # Get stats (non-streaming) - this is the slow part we're parallelizing
            container_stats = container.stats(stream=False)
            
            # Calculate CPU percentage
            cpu_delta = container_stats['cpu_stats']['cpu_usage']['total_usage'] - \
                       container_stats['precpu_stats']['cpu_usage']['total_usage']
            system_delta = container_stats['cpu_stats']['system_cpu_usage'] - \
                          container_stats['precpu_stats']['system_cpu_usage']
            cpu_percent = 0.0
            if system_delta > 0:
                cpu_percent = (cpu_delta / system_delta) * 100.0
            
            # Memory usage
            memory_usage = container_stats['memory_stats'].get('usage', 0)
            memory_limit = container_stats['memory_stats'].get('limit', 0)
            memory_percent = 0.0
            if memory_limit > 0:
                memory_percent = (memory_usage / memory_limit) * 100.0
            
            # Network stats (handle missing eth0 interface gracefully)
            network_rx = 0
            network_tx = 0
            if 'networks' in container_stats and container_stats['networks']:
                # Get first network interface stats
                first_network = list(container_stats['networks'].values())[0]
                network_rx = first_network.get('rx_bytes', 0)
                network_tx = first_network.get('tx_bytes', 0)
            
            return service, {
                "cpu_percent": round(cpu_percent, 2),
                "memory_usage": memory_usage,
                "memory_limit": memory_limit,
                "memory_percent": round(memory_percent, 2),
                "network_rx": network_rx,
                "network_tx": network_tx,
                "status": "healthy"
            }
            
        except Exception as e:
            logger.debug(f"Failed to get stats for {service}: {e}")
            return service, {
                "cpu_percent": 0,
                "memory_usage": 0,
                "memory_limit": 0,
                "memory_percent": 0,
                "network_rx": 0,
                "network_tx": 0,
                "status": "error"
            }
    
    def get_container_stats(self) -> Dict[str, Dict]:
        """Get resource usage stats for containers - parallelized for performance"""
        from .performance_tracker import PerformanceTracker
        performance_tracker = PerformanceTracker()
        
        stats = {}
        
        if not self.docker_client:
            return stats
        
        try:
            with performance_tracker.track_operation(f"List containers for stats {self.project_name}", show_progress=False):
                containers = self.docker_client.containers.list(
                    filters={"label": f"com.docker.compose.project={self.project_name}"}
                )
            
            if not containers:
                return stats
            
            # Use ThreadPoolExecutor to get stats for all containers in parallel
            with performance_tracker.track_operation(f"Get stats for {len(containers)} containers (parallel) {self.project_name}", show_progress=False):
                # Limit max workers to avoid overwhelming the Docker daemon
                max_workers = min(len(containers), 8)  # Max 8 concurrent requests
                
                with ThreadPoolExecutor(max_workers=max_workers) as executor:
                    # Submit all container stats requests
                    future_to_container = {
                        executor.submit(self._get_single_container_stats, container): container 
                        for container in containers
                    }
                    
                    # Collect results as they complete
                    for future in as_completed(future_to_container):
                        try:
                            service, container_stats = future.result()
                            stats[service] = container_stats
                        except Exception as e:
                            container = future_to_container[future]
                            service = container.labels.get("com.docker.compose.service", "unknown")
                            logger.debug(f"Failed to get stats for {service}: {e}")
                            stats[service] = {
                                "cpu_percent": 0,
                                "memory_usage": 0,
                                "memory_limit": 0,
                                "memory_percent": 0,
                                "network_rx": 0,
                                "network_tx": 0,
                                "status": "error"
                            }
                    
        except Exception as e:
            logger.error(f"Failed to get container stats: {e}")
        
        return stats
    
    def wait_for_services(self, timeout: int = 300) -> bool:
        """Wait for all services to be healthy"""
        start_time = time.time()
        
        # Critical services that must be healthy
        # Note: We'll determine which are actually present in the deployment
        critical_services = {'odoo', 'db'}
        
        logged_services = False
        
        while time.time() - start_time < timeout:
            status = self.get_container_status()
            
            # Log services once
            if not logged_services and status:
                logger.info(f"Found services: {list(status.keys())}")
                logged_services = True
            
            # Check if critical services are ready
            critical_ready = True
            critical_found = set()
            
            for service, info in status.items():
                # All containers should at least be running
                if info['status'] != 'running':
                    critical_ready = False
                    break
                
                # For critical services, check health if available
                if service in critical_services:
                    critical_found.add(service)
                    
                    # If health check exists and is not healthy/starting, it's not ready
                    # If no health check exists, consider it ready if running
                    if info['health'] and info['health'] not in ['healthy', 'starting', None]:
                        logger.debug(f"Service {service} health check failed: {info['health']}")
                        critical_ready = False
                        break
                
                # For proxy services, we don't care about health status
                # They might be unhealthy if external services are unreachable
                elif 'proxy' in service:
                    continue
            
            # Ensure all critical services are found and ready
            if critical_ready and critical_found == critical_services and len(status) > 0:
                logger.info(f"Critical services are ready for {self.deployment_id}")
                # Log any unhealthy proxy services for information
                unhealthy_proxies = [s for s, i in status.items() 
                                   if 'proxy' in s and i.get('health') == 'unhealthy']
                if unhealthy_proxies:
                    logger.warning(f"Proxy services are unhealthy (this is usually OK): {unhealthy_proxies}")
                return True
            
            # Log progress every 30 seconds
            elapsed = int(time.time() - start_time)
            if elapsed % 30 == 0:
                logger.debug(f"Waiting for services... ({elapsed}s elapsed)")
                logger.debug(f"Critical services found: {critical_found}")
                logger.debug(f"Missing critical services: {critical_services - critical_found}")
                for service, info in status.items():
                    if service in critical_services:
                        logger.debug(f"  {service}: status={info['status']}, health={info.get('health', 'N/A')}")
            
            time.sleep(5)
        
        logger.error(f"Timeout waiting for services to be ready for {self.deployment_id}")
        return False
    
    def _get_container_health(self, container) -> Optional[str]:
        """Get container health status"""
        try:
            health = container.attrs['State'].get('Health')
            if health:
                return health['Status']
        except:
            pass
        return None
    
    def cleanup_volumes(self) -> bool:
        """Clean up volumes for this deployment"""
        if not self.docker_client:
            return False
        
        try:
            # Get volumes for this project
            volumes = self.docker_client.volumes.list(
                filters={"label": f"com.docker.compose.project={self.project_name}"}
            )
            
            for volume in volumes:
                try:
                    volume.remove()
                    logger.info(f"Removed volume {volume.name}")
                except Exception as e:
                    logger.error(f"Failed to remove volume {volume.name}: {e}")
            
            return True
            
        except Exception as e:
            logger.error(f"Failed to cleanup volumes: {e}")
            return False
    
    def get_service_url(self, service: str, port_mappings: Dict[str, int], subdomain: str) -> str:
        """Get URL for accessing a service"""
        if service == "odoo":
            return f"http://{subdomain}"
        elif service == "mailhog":
            return f"http://localhost:{port_mappings.get('smtp', '')}"
        elif service == "pgweb":
            return f"http://localhost:{port_mappings.get('pgweb', '')}"
        else:
            return ""


class DockerResourceMonitor:
    """Monitor Docker resource usage across all deployments"""
    
    def __init__(self):
        try:
            self.docker_client = docker.from_env()
        except Exception as e:
            logger.error(f"Failed to initialize Docker client: {e}")
            self.docker_client = None
    
    def get_system_info(self) -> Dict:
        """Get Docker system information"""
        if not self.docker_client:
            return {}
        
        try:
            info = self.docker_client.info()
            return {
                "containers": info.get('Containers', 0),
                "containers_running": info.get('ContainersRunning', 0),
                "images": info.get('Images', 0),
                "driver": info.get('Driver', ''),
                "memory_limit": info.get('MemTotal', 0),
                "cpu_count": info.get('NCPU', 0),
                "docker_version": info.get('ServerVersion', '')
            }
        except Exception as e:
            logger.error(f"Failed to get system info: {e}")
            return {}
    
    def cleanup_dangling_resources(self) -> Dict[str, int]:
        """Clean up dangling images, volumes, and networks"""
        if not self.docker_client:
            return {}
        
        cleaned = {
            "images": 0,
            "volumes": 0,
            "networks": 0
        }
        
        try:
            # Clean dangling images
            images = self.docker_client.images.prune(filters={'dangling': True})
            cleaned['images'] = len(images.get('ImagesDeleted', []))
            
            # Clean unused volumes
            volumes = self.docker_client.volumes.prune()
            cleaned['volumes'] = len(volumes.get('VolumesDeleted', []))
            
            # Clean unused networks
            networks = self.docker_client.networks.prune()
            cleaned['networks'] = len(networks.get('NetworksDeleted', []))
            
        except Exception as e:
            logger.error(f"Failed to cleanup resources: {e}")
        
        return cleaned