# ABOUTME: Utility functions for validation, Git operations, and general helpers
# ABOUTME: Provides common functionality used across the deployment manager

import re
import os
import subprocess
import logging
import yaml
from pathlib import Path
from typing import List, Dict, Optional, Tuple
from contextlib import contextmanager
import shutil
import time
from functools import wraps
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)


def retry_on_failure(max_attempts: int = 3, delay: float = 2.0, backoff: float = 2.0):
    """Decorator to retry a function on failure with exponential backoff"""
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            attempt = 1
            current_delay = delay
            
            while attempt <= max_attempts:
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    if attempt == max_attempts:
                        logger.error(f"{func.__name__} failed after {max_attempts} attempts: {e}")
                        raise
                    
                    logger.warning(f"{func.__name__} attempt {attempt} failed: {e}. Retrying in {current_delay}s...")
                    time.sleep(current_delay)
                    current_delay *= backoff
                    attempt += 1
            
            return None
        return wrapper
    return decorator


def validate_deployment_name(name: str) -> bool:
    """Validate deployment name format"""
    # Only alphanumeric and hyphens, 3-20 chars
    pattern = r'^[a-z0-9][a-z0-9-]{1,18}[a-z0-9]$'
    return bool(re.match(pattern, name.lower()))


def validate_email(email: str) -> bool:
    """Validate email format"""
    pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    return bool(re.match(pattern, email))


def sanitize_deployment_id(tester_email: str, name: str) -> str:
    """Create safe deployment ID from tester email and name"""
    tester = tester_email.split('@')[0].replace('.', '-').lower()
    tester = re.sub(r'[^a-z0-9-]', '', tester)
    name = re.sub(r'[^a-z0-9-]', '', name.lower())
    return f"{tester}-{name}"


@contextmanager
def cd(path: str):
    """Context manager for changing working directory"""
    old_path = os.getcwd()
    try:
        os.chdir(path)
        yield
    finally:
        os.chdir(old_path)


def run_command(cmd: List[str], cwd: str = None, env: Dict[str, str] = None, 
                capture_output: bool = True, log_file: str = None) -> subprocess.CompletedProcess:
    """Run a command and return the result with comprehensive logging and timing
    
    Args:
        cmd: Command as list of strings
        cwd: Working directory for command
        env: Environment variables to add
        capture_output: Whether to capture stdout/stderr
        log_file: Optional file to write detailed logs to
        
    Returns:
        subprocess.CompletedProcess with timing information logged
        
    Logs timing information to:
        - Console (debug/info/error with duration)
        - Specified log_file (if provided) with full details
        - debug_commands_YYYYMMDD.log in deployment logs folder (if in deployment context)
    """
    full_env = os.environ.copy()
    if env:
        full_env.update(env)
    
    start_time = time.perf_counter()
    start_timestamp = time.strftime('%Y-%m-%d %H:%M:%S')
    
    logger.debug(f"🚀 Starting command: {' '.join(cmd)} in {cwd or 'current directory'}")
    
    result = subprocess.run(
        cmd,
        cwd=cwd,
        env=full_env,
        capture_output=capture_output,
        text=True
    )
    
    end_time = time.perf_counter()
    duration = end_time - start_time
    end_timestamp = time.strftime('%Y-%m-%d %H:%M:%S')
    
    # Enhanced logging with timing information
    if log_file and capture_output:
        try:
            with open(log_file, 'a') as f:
                f.write(f"\n{'='*80}\n")
                f.write(f"Command: {' '.join(cmd)}\n")
                f.write(f"Directory: {cwd or 'current'}\n")
                f.write(f"Started: {start_timestamp}\n")
                f.write(f"Ended: {end_timestamp}\n")
                f.write(f"Duration: {duration:.3f}s\n")
                f.write(f"Exit Code: {result.returncode}\n")
                if duration > 10.0:
                    f.write(f"⚠️  SLOW COMMAND: Took {duration:.1f} seconds\n")
                f.write(f"{'='*80}\n")
                if result.stdout:
                    f.write("STDOUT:\n")
                    f.write(result.stdout)
                    f.write("\n")
                if result.stderr:
                    f.write("STDERR:\n")
                    f.write(result.stderr)
                    f.write("\n")
                f.write(f"{'='*80}\n\n")
        except Exception as e:
            logger.warning(f"Failed to write to log file {log_file}: {e}")
    
    # Always write debug logs to appropriate log directories
    if not log_file:
        try:
            # Determine log directory based on context
            if cwd and "openspp-docker" in str(cwd):
                # Deployment-specific commands -> deployment logs folder
                logs_dir = Path(cwd).parent / "logs"
                log_context = "deployment"
            elif cwd and Path(cwd).name.startswith(("jeremi-", "test-")):
                # Deployment folder commands -> deployment logs folder  
                logs_dir = Path(cwd) / "logs"
                log_context = "deployment"
            else:
                # General app commands -> main project logs folder
                logs_dir = Path(__file__).parent.parent / "logs"
                log_context = "app"
            
            # Ensure logs directory exists
            logs_dir.mkdir(exist_ok=True)
            
            # Choose appropriate log file name
            if log_context == "deployment":
                debug_log_file = logs_dir / f"debug_commands_{time.strftime('%Y%m%d')}.log"
            else:
                debug_log_file = logs_dir / f"app_commands_{time.strftime('%Y%m%d')}.log"
            
            # Write the log entry
            with open(debug_log_file, 'a') as f:
                if log_context == "app":
                    f.write(f"[{end_timestamp}] APP: {' '.join(cmd)} -> exit {result.returncode} ({duration:.3f}s)")
                    if cwd:
                        f.write(f" (cwd: {Path(cwd).name})")
                    f.write("\n")
                else:
                    f.write(f"[{end_timestamp}] {' '.join(cmd)} -> exit {result.returncode} ({duration:.3f}s)\n")
                
                if result.returncode != 0 and result.stderr:
                    f.write(f"  ERROR: {result.stderr.strip()}\n")
                    
        except Exception:
            # Silently fail debug logging to avoid breaking commands
            pass
    
    # Enhanced console logging with timing
    if result.returncode == 0:
        if duration > 5.0:
            logger.info(f"✅ Command completed in {duration:.3f}s: {' '.join(cmd)}")
        else:
            logger.debug(f"✅ Command completed in {duration:.3f}s: {' '.join(cmd)}")
    else:
        # Log more details about the failure with timing
        logger.error(f"❌ Command failed after {duration:.3f}s with exit code {result.returncode}: {' '.join(cmd)}")
        if result.stderr:
            logger.error(f"STDERR output:\n{result.stderr}")
        if result.stdout:
            logger.error(f"STDOUT output (may contain useful info):\n{result.stdout}")
    
    return result


def run_command_with_retry(cmd: List[str], cwd: str = None, env: Dict[str, str] = None, 
                          capture_output: bool = True, max_attempts: int = 3, 
                          log_file: str = None) -> subprocess.CompletedProcess:
    """Run a command with retry logic for transient failures"""
    # Commands that should be retried on failure
    retriable_commands = ['git', 'docker', 'docker-compose', 'invoke']
    
    # Check if this is a retriable command
    if cmd and cmd[0] in retriable_commands:
        @retry_on_failure(max_attempts=max_attempts, delay=2.0)
        def _run_with_retry():
            result = run_command(cmd, cwd, env, capture_output, log_file)
            if result.returncode != 0:
                # Check for transient errors
                error_text = result.stderr.lower()
                if any(err in error_text for err in ['network', 'timeout', 'connection', 'temporary']):
                    raise Exception(f"Transient error: {result.stderr}")
            return result
        
        try:
            return _run_with_retry()
        except Exception:
            # Return the last failed result
            return run_command(cmd, cwd, env, capture_output, log_file)
    else:
        # Non-retriable command, run normally
        return run_command(cmd, cwd, env, capture_output, log_file)


def ensure_directory(path: str) -> Path:
    """Ensure directory exists and return Path object"""
    path_obj = Path(path)
    path_obj.mkdir(parents=True, exist_ok=True)
    return path_obj


def get_deployment_log_file(deployment_path: str, log_type: str = "commands") -> str:
    """Get standardized log file path for a deployment
    
    Args:
        deployment_path: Path to the deployment directory
        log_type: Type of log (commands, docker, etc.)
    
    Returns:
        Full path to the log file
    """
    logs_dir = Path(deployment_path) / "logs"
    logs_dir.mkdir(exist_ok=True)
    
    date_str = time.strftime('%Y%m%d')
    return str(logs_dir / f"{log_type}_{date_str}.log")


def read_yaml_file(file_path: str) -> Dict:
    """Read and parse YAML file"""
    try:
        with open(file_path, 'r') as f:
            return yaml.safe_load(f) or {}
    except Exception as e:
        logger.error(f"Failed to read YAML file {file_path}: {e}")
        return {}


def write_yaml_file(file_path: str, data: Dict) -> bool:
    """Write data to YAML file"""
    try:
        with open(file_path, 'w') as f:
            yaml.dump(data, f, default_flow_style=False, sort_keys=False)
        return True
    except Exception as e:
        logger.error(f"Failed to write YAML file {file_path}: {e}")
        return False


def get_port_mappings(port_base: int) -> Dict[str, int]:
    """Generate service port mappings from base port"""
    return {
        "odoo": port_base,
        "smtp": port_base + 25,
        "mailhog": port_base + 25,  # Same as smtp
        "pgweb": port_base + 81,
        "debugger": port_base + 84
    }


def format_docker_project_name(deployment_id: str) -> str:
    """Format deployment ID for Docker Compose project name"""
    # Docker Compose doesn't like hyphens in project names
    return f"openspp_{deployment_id.replace('-', '_')}"


def get_deployment_path(base_path: str, deployment_id: str) -> Path:
    """Get full path for a deployment"""
    return Path(base_path) / deployment_id


def cleanup_deployment_directory(deployment_path: str) -> bool:
    """Safely remove deployment directory"""
    try:
        if os.path.exists(deployment_path):
            shutil.rmtree(deployment_path)
            logger.info(f"Cleaned up deployment directory: {deployment_path}")
        return True
    except Exception as e:
        logger.error(f"Failed to cleanup deployment directory: {e}")
        return False


def parse_git_tags(output: str) -> List[str]:
    """Parse git tag output and return list of tags"""
    tags = []
    for line in output.strip().split('\n'):
        if line.strip():
            # Extract tag name from refs/tags/
            if 'refs/tags/' in line:
                tag = line.split('refs/tags/')[-1]
                tags.append(tag)
            else:
                tags.append(line.strip())
    return sorted(tags, reverse=True)


def parse_git_branches(output: str) -> List[str]:
    """Parse git branch output and return list of branches"""
    branches = []
    for line in output.strip().split('\n'):
        if line.strip():
            # Remove refs/heads/ prefix if present
            if 'refs/heads/' in line:
                branch = line.split('refs/heads/')[-1]
                branches.append(branch)
            else:
                # Handle simple branch names
                branch = line.strip().lstrip('* ')
                branches.append(branch)
    return sorted(set(branches))


def format_bytes(bytes_value: int) -> str:
    """Format bytes to human readable string"""
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if bytes_value < 1024.0:
            return f"{bytes_value:.1f}{unit}"
        bytes_value /= 1024.0
    return f"{bytes_value:.1f}PB"


def parse_docker_stats(stats_line: str) -> Dict[str, str]:
    """Parse docker stats output line"""
    parts = stats_line.split()
    if len(parts) >= 6:
        return {
            "container": parts[0],
            "cpu": parts[2],
            "memory": f"{parts[3]} / {parts[5]}",
            "memory_percent": parts[6]
        }
    return {}


def generate_env_content(deployment_id: str, port_base: int, config: Dict) -> str:
    """Generate .env file content for deployment"""
    project_name = format_docker_project_name(deployment_id)
    
    env_content = f"""# Auto-generated environment file for {deployment_id}
# Generated by OpenSPP Deployment Manager

# Project identification
COMPOSE_PROJECT_NAME={project_name}
DEPLOYMENT_ID={deployment_id}

# User/Group IDs
UID={os.getuid()}
GID={os.getgid()}

# Port configuration
ODOO_PORT={port_base}
ODOO_PORT_LONGPOLLING={port_base + 72}
ODOO_PROXY_PORT={port_base + 99}
SMTP_PORT={port_base + 25}
PGWEB_PORT={port_base + 81}
DEBUGGER_PORT={port_base + 84}
DB_PORT={port_base + 32}

# Default Odoo configuration
ODOO_DB={deployment_id.replace('-', '_')}
ODOO_ADMIN_PASSWORD=admin
ODOO_DEMO=true
ODOO_LOAD_LANGUAGE=en_US

# SMTP Configuration
SMTP_USER=odoo
SMTP_PASSWORD=odoo

# PGWeb Configuration
PGWEB_DATABASE_URL=postgres://odoo:odoo@db:5432/{deployment_id.replace('-', '_')}?sslmode=disable

# Development settings
DEBUGGER_ENABLED=true
LOG_LEVEL=info

# Resource limits
DOCKER_CPU_LIMIT={config.get('docker_cpu_limit', '2')}
DOCKER_MEMORY_LIMIT={config.get('docker_memory_limit', '4GB')}
"""
    
    return env_content


def check_docker_compose_installed() -> Tuple[bool, str]:
    """Check if docker compose is installed and return version"""
    try:
        # Try docker compose (v2)
        result = run_command(["docker", "compose", "version"])
        if result.returncode == 0:
            return True, result.stdout.strip()
        
        # Try docker-compose (v1)
        result = run_command(["docker-compose", "--version"])
        if result.returncode == 0:
            return True, result.stdout.strip()
            
    except FileNotFoundError:
        pass
    
    return False, ""


def check_git_installed() -> Tuple[bool, str]:
    """Check if git is installed and return version"""
    try:
        result = run_command(["git", "--version"])
        if result.returncode == 0:
            return True, result.stdout.strip()
    except FileNotFoundError:
        pass
    
    return False, ""


def check_invoke_installed() -> Tuple[bool, str]:
    """Check if invoke is installed and return version"""
    try:
        result = run_command(["invoke", "--version"])
        if result.returncode == 0:
            return True, result.stdout.strip()
    except FileNotFoundError:
        pass
    
    return False, ""


def format_relative_date(date: Optional[datetime]) -> str:
    """Format a date as relative time (e.g., '2 hours ago', '3 days ago')"""
    if not date:
        return ""
    
    now = datetime.now()
    # Ensure both dates are timezone-naive for comparison
    if date.tzinfo:
        date = date.replace(tzinfo=None)
    if now.tzinfo:
        now = now.replace(tzinfo=None)
    
    diff = now - date
    
    # Less than a minute
    if diff.total_seconds() < 60:
        return "just now"
    
    # Less than an hour
    if diff.total_seconds() < 3600:
        minutes = int(diff.total_seconds() / 60)
        return f"{minutes} minute{'s' if minutes != 1 else ''} ago"
    
    # Less than a day
    if diff.total_seconds() < 86400:
        hours = int(diff.total_seconds() / 3600)
        return f"{hours} hour{'s' if hours != 1 else ''} ago"
    
    # Less than a week
    if diff.days < 7:
        return f"{diff.days} day{'s' if diff.days != 1 else ''} ago"
    
    # Less than a month (approximate)
    if diff.days < 30:
        weeks = diff.days // 7
        return f"{weeks} week{'s' if weeks != 1 else ''} ago"
    
    # Less than a year
    if diff.days < 365:
        months = diff.days // 30
        return f"{months} month{'s' if months != 1 else ''} ago"
    
    # Years
    years = diff.days // 365
    return f"{years} year{'s' if years != 1 else ''} ago"