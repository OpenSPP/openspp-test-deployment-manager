# ABOUTME: SQLite database operations for deployment persistence
# ABOUTME: Handles CRUD operations and port allocation tracking

import os
import sqlite3
import json
import logging
from datetime import datetime
from typing import List, Optional, Dict
from pathlib import Path
from contextlib import contextmanager

from src.models import Deployment, DeploymentStatus

logger = logging.getLogger(__name__)


class DeploymentDatabase:
    """Handle all database operations for deployments"""
    
    def __init__(self, db_path: str = "deployments.db"):
        # Make sure db_path is absolute to avoid issues when changing directories
        if not os.path.isabs(db_path):
            # Get the directory where this file is located
            base_dir = Path(__file__).parent.parent
            self.db_path = str(base_dir / db_path)
        else:
            self.db_path = db_path
        self.init_database()
    
    @contextmanager
    def get_connection(self):
        """Context manager for database connections"""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()
    
    def init_database(self):
        """Initialize database schema"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            # Create deployments table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS deployments (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    tester_email TEXT NOT NULL,
                    openspp_version TEXT NOT NULL,
                    dependency_versions TEXT,
                    environment TEXT DEFAULT 'devel',
                    status TEXT DEFAULT 'creating',
                    created_at TEXT NOT NULL,
                    last_updated TEXT NOT NULL,
                    port_base INTEGER,
                    port_mappings TEXT,
                    subdomain TEXT,
                    modules_installed TEXT,
                    last_action TEXT,
                    notes TEXT,
                    auth_password TEXT DEFAULT ''
                )
            ''')
            
            # Create port allocations table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS port_allocations (
                    port_base INTEGER PRIMARY KEY,
                    deployment_id TEXT NOT NULL,
                    allocated_at TEXT NOT NULL,
                    FOREIGN KEY (deployment_id) REFERENCES deployments (id)
                )
            ''')
            
            # Create indexes
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_tester_email ON deployments (tester_email)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_status ON deployments (status)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_created_at ON deployments (created_at)')
            
            conn.commit()
            logger.info(f"Database initialized at {self.db_path}")
    
    def save_deployment(self, deployment: Deployment) -> bool:
        """Save or update a deployment"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            # Convert complex fields to JSON
            dep_versions = json.dumps(deployment.dependency_versions)
            port_mappings = json.dumps(deployment.port_mappings)
            modules = json.dumps(deployment.modules_installed)
            
            # Update last_updated timestamp
            deployment.last_updated = datetime.now()
            
            try:
                cursor.execute('''
                    INSERT OR REPLACE INTO deployments (
                        id, name, tester_email, openspp_version, dependency_versions,
                        environment, status, created_at, last_updated, port_base,
                        port_mappings, subdomain, modules_installed, last_action, notes,
                        auth_password
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    deployment.id, deployment.name, deployment.tester_email,
                    deployment.openspp_version, dep_versions, deployment.environment,
                    deployment.status.value, deployment.created_at.isoformat(),
                    deployment.last_updated.isoformat(), deployment.port_base,
                    port_mappings, deployment.subdomain, modules,
                    deployment.last_action, deployment.notes, deployment.auth_password
                ))
                
                # Handle port allocation
                if deployment.port_base > 0:
                    cursor.execute('''
                        INSERT OR REPLACE INTO port_allocations (port_base, deployment_id, allocated_at)
                        VALUES (?, ?, ?)
                    ''', (deployment.port_base, deployment.id, datetime.now().isoformat()))
                
                conn.commit()
                logger.info(f"Saved deployment {deployment.id}")
                return True
                
            except Exception as e:
                logger.error(f"Failed to save deployment {deployment.id}: {e}")
                conn.rollback()
                return False
    
    def get_deployment(self, deployment_id: str) -> Optional[Deployment]:
        """Get a deployment by ID"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            cursor.execute('SELECT * FROM deployments WHERE id = ?', (deployment_id,))
            row = cursor.fetchone()
            
            if row:
                return self._row_to_deployment(row)
            return None
    
    def get_all_deployments(self) -> List[Deployment]:
        """Get all deployments"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            cursor.execute('SELECT * FROM deployments ORDER BY created_at DESC')
            rows = cursor.fetchall()
            
            return [self._row_to_deployment(row) for row in rows]
    
    def get_deployments_by_tester(self, tester_email: str) -> List[Deployment]:
        """Get all deployments for a specific tester"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            cursor.execute(
                'SELECT * FROM deployments WHERE tester_email = ? ORDER BY created_at DESC',
                (tester_email,)
            )
            rows = cursor.fetchall()
            
            return [self._row_to_deployment(row) for row in rows]
    
    def get_deployments_by_status(self, status: DeploymentStatus) -> List[Deployment]:
        """Get deployments by status"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            cursor.execute(
                'SELECT * FROM deployments WHERE status = ? ORDER BY created_at DESC',
                (status.value,)
            )
            rows = cursor.fetchall()
            
            return [self._row_to_deployment(row) for row in rows]
    
    def update_deployment_status(self, deployment_id: str, status: DeploymentStatus, last_action: str = None) -> bool:
        """Update deployment status"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            try:
                if last_action:
                    cursor.execute('''
                        UPDATE deployments 
                        SET status = ?, last_action = ?, last_updated = ?
                        WHERE id = ?
                    ''', (status.value, last_action, datetime.now().isoformat(), deployment_id))
                else:
                    cursor.execute('''
                        UPDATE deployments 
                        SET status = ?, last_updated = ?
                        WHERE id = ?
                    ''', (status.value, datetime.now().isoformat(), deployment_id))
                
                conn.commit()
                return cursor.rowcount > 0
                
            except Exception as e:
                logger.error(f"Failed to update deployment status: {e}")
                conn.rollback()
                return False
    
    def delete_deployment(self, deployment_id: str) -> bool:
        """Delete a deployment and free its ports"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            try:
                # Get port allocation first
                cursor.execute('SELECT port_base FROM deployments WHERE id = ?', (deployment_id,))
                row = cursor.fetchone()
                
                if row:
                    # Delete port allocation
                    cursor.execute('DELETE FROM port_allocations WHERE deployment_id = ?', (deployment_id,))
                    
                    # Delete deployment
                    cursor.execute('DELETE FROM deployments WHERE id = ?', (deployment_id,))
                    
                    conn.commit()
                    logger.info(f"Deleted deployment {deployment_id}")
                    return True
                    
                return False
                
            except Exception as e:
                logger.error(f"Failed to delete deployment: {e}")
                conn.rollback()
                return False
    
    def allocate_port_range(self, deployment_id: str, increment: int = 100) -> Optional[int]:
        """Allocate a port range for a deployment"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            # Get all allocated ports sorted
            cursor.execute('SELECT port_base FROM port_allocations ORDER BY port_base')
            allocated_ports = [row[0] for row in cursor.fetchall()]
            
            port_start = 18000  # Starting port
            port_end = 19000    # Maximum port
            
            # If no ports allocated yet, use the first available
            if not allocated_ports:
                port_base = port_start
            else:
                # Look for gaps in the allocated ports
                port_base = None
                
                # Check if we can use a port before the first allocation
                if allocated_ports[0] - port_start >= increment:
                    port_base = port_start
                else:
                    # Look for gaps between consecutive allocations
                    for i in range(len(allocated_ports) - 1):
                        gap_start = allocated_ports[i] + increment
                        gap_end = allocated_ports[i + 1]
                        
                        if gap_end - gap_start >= increment:
                            port_base = gap_start
                            break
                    
                    # If no gap found, try after the last allocation
                    if port_base is None:
                        next_port = allocated_ports[-1] + increment
                        if next_port + increment <= port_end:
                            port_base = next_port
            
            # Allocate the port if we found one
            if port_base is not None and port_base + increment <= port_end:
                cursor.execute('''
                    INSERT INTO port_allocations (port_base, deployment_id, allocated_at)
                    VALUES (?, ?, ?)
                ''', (port_base, deployment_id, datetime.now().isoformat()))
                
                conn.commit()
                logger.info(f"Allocated port range {port_base} for {deployment_id}")
                return port_base
            
            logger.error("No available port ranges")
            return None
    
    def count_tester_deployments(self, tester_email: str) -> int:
        """Count deployments for a tester"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            cursor.execute(
                'SELECT COUNT(*) FROM deployments WHERE tester_email = ?',
                (tester_email,)
            )
            return cursor.fetchone()[0]
    
    def deployment_exists(self, deployment_id: str) -> bool:
        """Check if deployment exists"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            cursor.execute('SELECT 1 FROM deployments WHERE id = ? LIMIT 1', (deployment_id,))
            return cursor.fetchone() is not None
    
    def _row_to_deployment(self, row: sqlite3.Row) -> Deployment:
        """Convert database row to Deployment object"""
        data = dict(row)
        
        # Parse JSON fields
        data['dependency_versions'] = json.loads(data.get('dependency_versions', '{}'))
        data['port_mappings'] = json.loads(data.get('port_mappings', '{}'))
        data['modules_installed'] = json.loads(data.get('modules_installed', '[]'))
        
        # Parse datetime fields
        data['created_at'] = datetime.fromisoformat(data['created_at'])
        data['last_updated'] = datetime.fromisoformat(data['last_updated'])
        
        # Convert status string to enum
        if 'status' in data and isinstance(data['status'], str):
            data['status'] = DeploymentStatus(data['status'])
        
        # Handle missing auth_password for backward compatibility
        if 'auth_password' not in data:
            data['auth_password'] = ''
        
        return Deployment(**data)


# CLI interface for database management
if __name__ == "__main__":
    import sys
    
    if len(sys.argv) > 1 and sys.argv[1] == "init":
        db = DeploymentDatabase()
        print(f"Database initialized at {db.db_path}")