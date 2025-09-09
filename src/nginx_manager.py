# ABOUTME: Enhanced Nginx configuration manager with auto-recovery and drift healing
# ABOUTME: Handles nginx config generation, validation, error recovery, and reconciliation

import os
import re
import logging
import subprocess
import tempfile
import shutil
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from datetime import datetime

from src.models import Deployment, AppConfig
from src.utils import run_command

logger = logging.getLogger(__name__)


class NginxManager:
    """Enhanced Nginx configuration manager with error recovery and reconciliation"""
    
    def __init__(self, config: AppConfig):
        self.config = config
        self.nginx_sites_path = Path(config.nginx_config_path)
        self.nginx_enabled_path = self.nginx_sites_path.parent / "sites-enabled"
        self.nginx_conf_path = Path("/etc/nginx/nginx.conf")
        self.last_reload_status = None
        self.last_reload_error = None
        self.last_reload_time = None
        
    def ensure_nginx_base_config(self) -> Tuple[bool, str]:
        """Ensure nginx base configuration has proper settings"""
        try:
            # Check if we can read nginx.conf
            if not self.nginx_conf_path.exists():
                return False, f"Nginx config not found at {self.nginx_conf_path}"
            
            # Read current nginx.conf
            result = run_command(["sudo", "cat", str(self.nginx_conf_path)])
            if result.returncode != 0:
                return False, f"Cannot read nginx.conf: {result.stderr}"
            
            nginx_conf = result.stdout
            
            # Check for server_names_hash_bucket_size setting
            if "server_names_hash_bucket_size" not in nginx_conf or \
               re.search(r'^\s*#.*server_names_hash_bucket_size', nginx_conf, re.MULTILINE):
                # Need to add or uncomment server_names_hash_bucket_size
                logger.info("Updating nginx.conf to set server_names_hash_bucket_size to 128")
                
                # Create updated config
                if "server_names_hash_bucket_size" in nginx_conf:
                    # Uncomment and update existing line
                    updated_conf = re.sub(
                        r'^\s*#\s*server_names_hash_bucket_size\s+\d+;',
                        '    server_names_hash_bucket_size 128;',
                        nginx_conf,
                        flags=re.MULTILINE
                    )
                else:
                    # Add new line in http block
                    updated_conf = re.sub(
                        r'(http\s*{)',
                        r'\1\n    server_names_hash_bucket_size 128;',
                        nginx_conf
                    )
                
                # Write to temp file and move
                with tempfile.NamedTemporaryFile(mode='w', delete=False) as tmp:
                    tmp.write(updated_conf)
                    tmp_path = tmp.name
                
                # Backup original
                backup_path = f"/etc/nginx/nginx.conf.backup.{datetime.now().strftime('%Y%m%d_%H%M%S')}"
                run_command(["sudo", "cp", str(self.nginx_conf_path), backup_path])
                
                # Replace config
                result = run_command(["sudo", "mv", tmp_path, str(self.nginx_conf_path)])
                if result.returncode != 0:
                    os.unlink(tmp_path)
                    return False, f"Failed to update nginx.conf: {result.stderr}"
                
                logger.info("Successfully updated nginx.conf with server_names_hash_bucket_size 128")
            
            return True, "Nginx base configuration is properly set"
            
        except Exception as e:
            logger.error(f"Failed to ensure nginx base config: {e}")
            return False, str(e)
    
    def generate_nginx_config(self, deployment: Deployment) -> str:
        """Generate complete Nginx configuration with both internal and external domains"""
        # Domains
        external_domain = deployment.subdomain  # e.g., test1.test.openspp.org
        internal_domain = f"{deployment.id}.openspp-test.internal"
        
        # Ports
        odoo_port = deployment.port_mappings.get('odoo', deployment.port_base)
        smtp_port = deployment.port_mappings.get('smtp', deployment.port_base + 25)
        pgweb_port = deployment.port_mappings.get('pgweb', deployment.port_base + 81)
        
        # Common proxy configurations
        proxy_config = f"""
        proxy_pass http://localhost:{odoo_port};
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header X-Forwarded-Host $host;
        proxy_redirect off;
        client_max_body_size 100M;"""
        
        websocket_config = f"""
        proxy_pass http://localhost:{odoo_port}/websocket;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 86400s;
        proxy_send_timeout 86400s;"""
        
        config = f"""# Auto-generated Nginx configuration for {deployment.id}
# Generated by OpenSPP Deployment Manager
# Created: {datetime.now().isoformat()}
# Ports: Odoo={odoo_port}, SMTP={smtp_port}, PGWeb={pgweb_port}

# ===== INTERNAL DOMAIN (NO AUTH) =====
server {{
    listen 80;
    server_name {internal_domain};
    
    # No authentication for internal access
    
    # Security headers
    add_header X-Frame-Options "SAMEORIGIN" always;
    add_header X-Content-Type-Options "nosniff" always;
    add_header X-XSS-Protection "1; mode=block" always;
    
    # Proxy timeouts
    proxy_connect_timeout 600s;
    proxy_send_timeout 600s;
    proxy_read_timeout 600s;
    
    location / {{{proxy_config}
    }}
    
    location /websocket {{{websocket_config}
    }}
    
    location /longpolling {{
        proxy_pass http://localhost:{odoo_port}/longpolling;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }}
    
    access_log /var/log/nginx/{deployment.id}_int_access.log;
    error_log /var/log/nginx/{deployment.id}_int_error.log;
}}

# ===== EXTERNAL DOMAIN (WITH AUTH) =====
server {{
    listen 80;
    server_name {external_domain};
    
    # Basic authentication (username: {deployment.id})
    auth_basic "OpenSPP Deployment {deployment.id}";
    auth_basic_user_file /etc/nginx/htpasswd-{deployment.id};
    
    # Security headers
    add_header X-Frame-Options "SAMEORIGIN" always;
    add_header X-Content-Type-Options "nosniff" always;
    add_header X-XSS-Protection "1; mode=block" always;
    
    # Proxy timeouts  
    proxy_connect_timeout 600s;
    proxy_send_timeout 600s;
    proxy_read_timeout 600s;
    
    location / {{{proxy_config}
    }}
    
    location /websocket {{{websocket_config}
    }}
    
    location /longpolling {{
        proxy_pass http://localhost:{odoo_port}/longpolling;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }}
    
    access_log /var/log/nginx/{deployment.id}_ext_access.log;
    error_log /var/log/nginx/{deployment.id}_ext_error.log;
}}

# ===== MAILHOG INTERNAL =====
server {{
    listen 80;
    server_name mailhog-{deployment.id}.openspp-test.internal;
    
    location / {{
        proxy_pass http://localhost:{smtp_port};
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }}
}}

# ===== MAILHOG EXTERNAL =====
server {{
    listen 80;
    server_name mailhog-{external_domain};
    
    auth_basic "OpenSPP Mailhog {deployment.id}";
    auth_basic_user_file /etc/nginx/htpasswd-{deployment.id};
    
    location / {{
        proxy_pass http://localhost:{smtp_port};
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }}
}}

# ===== PGWEB INTERNAL =====
server {{
    listen 80;
    server_name pgweb-{deployment.id}.openspp-test.internal;
    
    location / {{
        proxy_pass http://localhost:{pgweb_port};
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }}
}}

# ===== PGWEB EXTERNAL =====
server {{
    listen 80;
    server_name pgweb-{external_domain};
    
    auth_basic "OpenSPP PGWeb {deployment.id}";
    auth_basic_user_file /etc/nginx/htpasswd-{deployment.id};
    
    location / {{
        proxy_pass http://localhost:{pgweb_port};
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }}
}}
"""
        return config
    
    def create_htpasswd_file(self, deployment: Deployment) -> Tuple[bool, str]:
        """Create htpasswd file for basic auth"""
        if not deployment.auth_password:
            logger.warning(f"No auth password for deployment {deployment.id}")
            return False, f"No auth password for deployment {deployment.id}"
            
        htpasswd_path = Path(f"/etc/nginx/htpasswd-{deployment.id}")
        
        try:
            # Generate APR1-MD5 hash (nginx compatible) - exactly as the old code did
            import crypt
            # Use deployment.id as username
            username = deployment.id
            # Create htpasswd entry
            htpasswd_entry = f"{username}:{crypt.crypt(deployment.auth_password, crypt.mksalt(crypt.METHOD_MD5))}\n"
            
            # Write to temporary file first
            with tempfile.NamedTemporaryFile(mode='w', delete=False) as tmp:
                tmp.write(htpasswd_entry)
                tmp_path = tmp.name
            
            # Move to nginx directory (requires sudo)
            result = run_command(
                ["sudo", "mv", tmp_path, str(htpasswd_path)]
            )
            
            if result.returncode != 0:
                logger.error(f"Failed to save htpasswd file: {result.stderr}")
                if os.path.exists(tmp_path):
                    os.unlink(tmp_path)
                return False, f"Failed to save htpasswd: {result.stderr}"
            
            # Set proper permissions
            run_command(["sudo", "chmod", "644", str(htpasswd_path)])
            
            logger.info(f"Created htpasswd file for {deployment.id}")
            return True, "htpasswd file created successfully"
            
        except Exception as e:
            logger.error(f"Failed to create htpasswd file: {e}")
            return False, str(e)
    
    def save_and_enable_nginx_config(self, deployment: Deployment) -> Tuple[bool, str]:
        """Save nginx config to sites-available and enable it"""
        config_content = self.generate_nginx_config(deployment)
        config_filename = f"openspp-{deployment.id}.conf"
        config_path = self.nginx_sites_path / config_filename
        enabled_path = self.nginx_enabled_path / config_filename
        
        try:
            # Write to temporary file
            with tempfile.NamedTemporaryFile(mode='w', delete=False) as tmp:
                tmp.write(config_content)
                tmp_path = tmp.name
            
            # Move to sites-available
            result = run_command(["sudo", "mv", tmp_path, str(config_path)])
            if result.returncode != 0:
                os.unlink(tmp_path)
                return False, f"Failed to save config: {result.stderr}"
            
            # Set permissions
            run_command(["sudo", "chmod", "644", str(config_path)])
            
            # Create symlink in sites-enabled
            result = run_command(["sudo", "ln", "-sf", str(config_path), str(enabled_path)])
            if result.returncode != 0:
                return False, f"Failed to enable site: {result.stderr}"
            
            logger.info(f"Saved and enabled nginx config for {deployment.id}")
            return True, "Nginx config saved and enabled"
            
        except Exception as e:
            logger.error(f"Failed to save nginx config: {e}")
            return False, str(e)
    
    def validate_and_reload_nginx(self) -> Tuple[bool, str]:
        """Validate nginx configuration and reload with auto-recovery"""
        try:
            # Test configuration
            test_result = run_command(["sudo", "nginx", "-t"])
            
            if test_result.returncode != 0:
                error_msg = test_result.stderr
                logger.error(f"Nginx config test failed: {error_msg}")
                
                # Check for common errors and attempt auto-fix
                if "server_names_hash_bucket_size" in error_msg:
                    logger.info("Detected hash bucket size error, attempting auto-fix...")
                    
                    # Update nginx.conf with larger bucket size
                    fix_success, fix_msg = self.fix_hash_bucket_size_error()
                    if fix_success:
                        # Retry test
                        test_result = run_command(["sudo", "nginx", "-t"])
                        if test_result.returncode == 0:
                            logger.info("Auto-fix successful, config now valid")
                        else:
                            return False, f"Auto-fix attempted but config still invalid: {test_result.stderr}"
                    else:
                        return False, f"Auto-fix failed: {fix_msg}"
                else:
                    # Return the actual error for other issues
                    return False, f"Config validation failed: {error_msg}"
            
            # If test passed, reload nginx
            reload_result = run_command(["sudo", "systemctl", "reload", "nginx"])
            
            if reload_result.returncode != 0:
                # Try alternative reload method
                reload_result = run_command(["sudo", "nginx", "-s", "reload"])
                if reload_result.returncode != 0:
                    error_msg = f"Failed to reload nginx: {reload_result.stderr}"
                    self.last_reload_status = False
                    self.last_reload_error = error_msg
                    self.last_reload_time = datetime.now()
                    return False, error_msg
            
            self.last_reload_status = True
            self.last_reload_error = None
            self.last_reload_time = datetime.now()
            logger.info("Nginx reloaded successfully")
            return True, "Nginx reloaded successfully"
            
        except Exception as e:
            error_msg = str(e)
            self.last_reload_status = False
            self.last_reload_error = error_msg
            self.last_reload_time = datetime.now()
            logger.error(f"Failed to reload nginx: {error_msg}")
            return False, error_msg
    
    def fix_hash_bucket_size_error(self) -> Tuple[bool, str]:
        """Auto-fix server_names_hash_bucket_size error"""
        try:
            # Read current nginx.conf
            result = run_command(["sudo", "cat", str(self.nginx_conf_path)])
            if result.returncode != 0:
                return False, f"Cannot read nginx.conf: {result.stderr}"
            
            nginx_conf = result.stdout
            
            # Check current setting
            current_size = 64
            match = re.search(r'server_names_hash_bucket_size\s+(\d+);', nginx_conf)
            if match:
                current_size = int(match.group(1))
            
            # Double the size
            new_size = max(128, current_size * 2)
            
            # Update or add the setting
            if "server_names_hash_bucket_size" in nginx_conf:
                updated_conf = re.sub(
                    r'server_names_hash_bucket_size\s+\d+;',
                    f'server_names_hash_bucket_size {new_size};',
                    nginx_conf
                )
            else:
                # Add after http {
                updated_conf = re.sub(
                    r'(http\s*{)',
                    f'\\1\n    server_names_hash_bucket_size {new_size};',
                    nginx_conf
                )
            
            # Write to temp file
            with tempfile.NamedTemporaryFile(mode='w', delete=False) as tmp:
                tmp.write(updated_conf)
                tmp_path = tmp.name
            
            # Backup and replace
            backup_path = f"/etc/nginx/nginx.conf.backup.{datetime.now().strftime('%Y%m%d_%H%M%S')}"
            run_command(["sudo", "cp", str(self.nginx_conf_path), backup_path])
            
            result = run_command(["sudo", "mv", tmp_path, str(self.nginx_conf_path)])
            if result.returncode != 0:
                os.unlink(tmp_path)
                return False, f"Failed to update nginx.conf: {result.stderr}"
            
            logger.info(f"Updated server_names_hash_bucket_size to {new_size}")
            return True, f"Updated hash bucket size to {new_size}"
            
        except Exception as e:
            return False, str(e)
    
    def reconcile_nginx_configs(self, deployments: List[Deployment]) -> Dict[str, any]:
        """Reconcile nginx configs with actual deployments"""
        results = {
            'checked': 0,
            'created': 0,
            'updated': 0,
            'removed': 0,
            'errors': []
        }
        
        try:
            # Get all existing nginx configs
            existing_configs = set()
            if self.nginx_sites_path.exists():
                for config_file in self.nginx_sites_path.glob("openspp-*.conf"):
                    # Extract deployment ID from filename
                    deployment_id = config_file.stem.replace("openspp-", "")
                    existing_configs.add(deployment_id)
            
            # Get all deployment IDs
            deployment_ids = {d.id for d in deployments}
            
            # Create/update configs for active deployments
            for deployment in deployments:
                results['checked'] += 1
                config_path = self.nginx_sites_path / f"openspp-{deployment.id}.conf"
                
                if not config_path.exists():
                    # Create missing config
                    logger.info(f"Creating missing nginx config for {deployment.id}")
                    success, msg = self.save_and_enable_nginx_config(deployment)
                    if success:
                        results['created'] += 1
                    else:
                        results['errors'].append(f"{deployment.id}: {msg}")
                else:
                    # Check if config needs updating
                    # (Could compare content here if needed)
                    logger.debug(f"Config exists for {deployment.id}")
            
            # Remove configs for non-existent deployments
            stale_configs = existing_configs - deployment_ids
            for deployment_id in stale_configs:
                logger.info(f"Removing stale nginx config for {deployment_id}")
                if self.remove_nginx_config(deployment_id):
                    results['removed'] += 1
                else:
                    results['errors'].append(f"Failed to remove config for {deployment_id}")
            
            # Ensure all htpasswd files exist
            for deployment in deployments:
                if deployment.auth_password:
                    htpasswd_path = Path(f"/etc/nginx/htpasswd-{deployment.id}")
                    if not htpasswd_path.exists():
                        logger.info(f"Creating missing htpasswd for {deployment.id}")
                        self.create_htpasswd_file(deployment)
            
        except Exception as e:
            results['errors'].append(f"Reconciliation error: {str(e)}")
        
        return results
    
    def remove_nginx_config(self, deployment_id: str) -> bool:
        """Remove nginx configuration and htpasswd file"""
        try:
            # Remove symlink from sites-enabled
            enabled_path = self.nginx_enabled_path / f"openspp-{deployment_id}.conf"
            if enabled_path.exists():
                run_command(["sudo", "rm", str(enabled_path)])
            
            # Remove config from sites-available
            config_path = self.nginx_sites_path / f"openspp-{deployment_id}.conf"
            if config_path.exists():
                run_command(["sudo", "rm", str(config_path)])
            
            # Remove htpasswd file
            htpasswd_path = Path(f"/etc/nginx/htpasswd-{deployment_id}")
            if htpasswd_path.exists():
                run_command(["sudo", "rm", str(htpasswd_path)])
            
            logger.info(f"Removed nginx config for {deployment_id}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to remove nginx config: {e}")
            return False
    
    def get_nginx_status(self) -> Dict[str, any]:
        """Get current nginx status and last reload info"""
        status = {
            'running': False,
            'config_valid': False,
            'last_reload_time': self.last_reload_time,
            'last_reload_status': self.last_reload_status,
            'last_reload_error': self.last_reload_error
        }
        
        try:
            # Check if nginx is running
            # Try systemctl first (Linux)
            result = run_command(["systemctl", "is-active", "nginx"])
            status['running'] = result.returncode == 0
        except (FileNotFoundError, OSError):
            # Fallback for systems without systemctl (e.g., macOS)
            try:
                result = run_command(["pgrep", "-x", "nginx"])
                status['running'] = result.returncode == 0
            except:
                status['running'] = False
        
        try:
            # Check if config is valid
            result = run_command(["sudo", "nginx", "-t"])
            status['config_valid'] = result.returncode == 0
        except Exception as e:
            logger.debug(f"Failed to check nginx config validity: {e}")
            status['config_valid'] = False
        
        return status
    
    def setup_deployment_domain(self, deployment: Deployment) -> Tuple[bool, str]:
        """Complete domain setup for a deployment with proper error handling"""
        errors = []
        warnings = []
        
        logger.info(f"Starting domain setup for deployment {deployment.id}")
        
        # Ensure base nginx config is proper
        success, msg = self.ensure_nginx_base_config()
        if not success:
            warnings.append(f"Base config: {msg}")
        
        # Create htpasswd file - this is critical for external access
        if deployment.auth_password:
            logger.info(f"Creating htpasswd file for {deployment.id} with password")
            success, msg = self.create_htpasswd_file(deployment)
            if not success:
                # This is a critical error - nginx will fail without htpasswd file
                logger.error(f"Failed to create htpasswd file for {deployment.id}: {msg}")
                errors.append(f"htpasswd creation failed: {msg}")
                # Still continue to set up the config, but warn about the issue
        else:
            logger.warning(f"No auth_password set for deployment {deployment.id} - htpasswd file will not be created")
            warnings.append("No authentication password set")
        
        # Save and enable nginx config
        success, msg = self.save_and_enable_nginx_config(deployment)
        if not success:
            return False, f"Failed to setup domain: {msg}"
        
        # Validate and reload
        success, msg = self.validate_and_reload_nginx()
        if not success:
            # Check if it's specifically the htpasswd file missing
            if "htpasswd" in msg.lower():
                logger.error(f"Nginx reload failed due to missing htpasswd file for {deployment.id}")
                errors.append(f"Nginx config references htpasswd file that doesn't exist")
            # Try to rollback
            self.remove_nginx_config(deployment.id)
            return False, f"Config invalid, rolled back: {msg}"
        
        # Compile status message
        if errors:
            return False, f"Setup failed with errors: {'; '.join(errors)}"
        elif warnings:
            return True, f"Setup completed with warnings: {'; '.join(warnings)}"
        
        return True, "Domain setup completed successfully"
    
    def cleanup_deployment_domain(self, deployment_id: str) -> Tuple[bool, str]:
        """Clean up domain configuration for a deployment"""
        if self.remove_nginx_config(deployment_id):
            # Reload nginx
            self.validate_and_reload_nginx()
            return True, "Domain cleanup completed"
        return False, "Failed to cleanup domain configuration"