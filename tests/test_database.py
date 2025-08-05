# ABOUTME: Tests for database operations
# ABOUTME: Validates CRUD operations, port allocation, and queries

import pytest
import tempfile
import os
from datetime import datetime
from src.database import DeploymentDatabase
from src.models import Deployment, DeploymentStatus


@pytest.fixture
def temp_db():
    """Create a temporary database for testing"""
    fd, path = tempfile.mkstemp(suffix='.db')
    os.close(fd)
    db = DeploymentDatabase(path)
    yield db
    os.unlink(path)


class TestDeploymentDatabase:
    """Test database operations"""
    
    def test_init_database(self, temp_db):
        """Test database initialization creates tables"""
        # Tables should be created automatically
        with temp_db.get_connection() as conn:
            cursor = conn.cursor()
            
            # Check deployments table exists
            cursor.execute("""
                SELECT name FROM sqlite_master 
                WHERE type='table' AND name='deployments'
            """)
            assert cursor.fetchone() is not None
            
            # Check port_allocations table exists
            cursor.execute("""
                SELECT name FROM sqlite_master 
                WHERE type='table' AND name='port_allocations'
            """)
            assert cursor.fetchone() is not None
    
    def test_save_and_get_deployment(self, temp_db):
        """Test saving and retrieving a deployment"""
        deployment = Deployment(
            id="test-deployment",
            name="test",
            tester_email="test@example.com",
            openspp_version="openspp-17.0.1.2.1",
            status=DeploymentStatus.RUNNING,
            port_base=18000,
            port_mappings={"odoo": 18000}
        )
        
        # Save deployment
        assert temp_db.save_deployment(deployment) == True
        
        # Retrieve deployment
        retrieved = temp_db.get_deployment("test-deployment")
        assert retrieved is not None
        assert retrieved.id == "test-deployment"
        assert retrieved.status == DeploymentStatus.RUNNING
        assert retrieved.port_mappings["odoo"] == 18000
    
    def test_update_deployment_status(self, temp_db):
        """Test updating deployment status"""
        deployment = Deployment(
            id="test-deployment",
            name="test",
            tester_email="test@example.com",
            openspp_version="openspp-17.0.1.2.1",
            status=DeploymentStatus.CREATING,
            port_base=18000
        )
        
        temp_db.save_deployment(deployment)
        
        # Update status
        success = temp_db.update_deployment_status(
            "test-deployment", 
            DeploymentStatus.RUNNING,
            "Started successfully"
        )
        assert success == True
        
        # Verify update
        updated = temp_db.get_deployment("test-deployment")
        assert updated.status == DeploymentStatus.RUNNING
        assert updated.last_action == "Started successfully"
    
    def test_get_deployments_by_tester(self, temp_db):
        """Test retrieving deployments by tester email"""
        # Create multiple deployments
        for i in range(3):
            deployment = Deployment(
                id=f"test-{i}",
                name=f"test{i}",
                tester_email="test@example.com",
                openspp_version="openspp-17.0.1.2.1",
                port_base=18000 + (i * 100)
            )
            temp_db.save_deployment(deployment)
        
        # Add deployment for different tester
        other = Deployment(
            id="other-deployment",
            name="other",
            tester_email="other@example.com",
            openspp_version="openspp-17.0.1.2.1",
            port_base=18300
        )
        temp_db.save_deployment(other)
        
        # Get deployments for test@example.com
        deployments = temp_db.get_deployments_by_tester("test@example.com")
        assert len(deployments) == 3
        assert all(d.tester_email == "test@example.com" for d in deployments)
    
    def test_get_deployments_by_status(self, temp_db):
        """Test retrieving deployments by status"""
        # Create deployments with different statuses
        statuses = [
            DeploymentStatus.RUNNING,
            DeploymentStatus.RUNNING,
            DeploymentStatus.STOPPED,
            DeploymentStatus.ERROR
        ]
        
        for i, status in enumerate(statuses):
            deployment = Deployment(
                id=f"test-{i}",
                name=f"test{i}",
                tester_email="test@example.com",
                openspp_version="openspp-17.0.1.2.1",
                status=status,
                port_base=18000 + (i * 100)
            )
            temp_db.save_deployment(deployment)
        
        # Get running deployments
        running = temp_db.get_deployments_by_status(DeploymentStatus.RUNNING)
        assert len(running) == 2
        
        # Get stopped deployments
        stopped = temp_db.get_deployments_by_status(DeploymentStatus.STOPPED)
        assert len(stopped) == 1
    
    def test_delete_deployment(self, temp_db):
        """Test deleting a deployment"""
        deployment = Deployment(
            id="test-deployment",
            name="test",
            tester_email="test@example.com",
            openspp_version="openspp-17.0.1.2.1",
            port_base=18000
        )
        
        temp_db.save_deployment(deployment)
        
        # Delete deployment
        assert temp_db.delete_deployment("test-deployment") == True
        
        # Verify deletion
        assert temp_db.get_deployment("test-deployment") is None
        
        # Port allocation should also be deleted
        with temp_db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT * FROM port_allocations WHERE deployment_id = ?",
                ("test-deployment",)
            )
            assert cursor.fetchone() is None
    
    def test_allocate_port_range(self, temp_db):
        """Test port allocation algorithm"""
        # First allocation should get 18000
        port1 = temp_db.allocate_port_range("deploy1")
        assert port1 == 18000
        
        # Second allocation should get 18100
        port2 = temp_db.allocate_port_range("deploy2")
        assert port2 == 18100
        
        # Third allocation should get 18200
        port3 = temp_db.allocate_port_range("deploy3")
        assert port3 == 18200
        
        # Delete middle deployment
        with temp_db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "DELETE FROM port_allocations WHERE deployment_id = ?",
                ("deploy2",)
            )
            conn.commit()
        
        # Next allocation should reuse the gap at 18100
        port4 = temp_db.allocate_port_range("deploy4")
        assert port4 == 18100
    
    def test_port_allocation_exhaustion(self, temp_db):
        """Test handling when all ports are exhausted"""
        # Allocate all possible ports (18000-19000 with increment 100 = 10 ports)
        for i in range(10):
            port = temp_db.allocate_port_range(f"deploy{i}")
            assert port is not None
        
        # Next allocation should fail
        port = temp_db.allocate_port_range("deploy_overflow")
        assert port is None
    
    def test_count_tester_deployments(self, temp_db):
        """Test counting deployments per tester"""
        # Create deployments for tester
        for i in range(3):
            deployment = Deployment(
                id=f"test-{i}",
                name=f"test{i}",
                tester_email="test@example.com",
                openspp_version="openspp-17.0.1.2.1",
                port_base=18000 + (i * 100)
            )
            temp_db.save_deployment(deployment)
        
        count = temp_db.count_tester_deployments("test@example.com")
        assert count == 3
        
        count = temp_db.count_tester_deployments("nonexistent@example.com")
        assert count == 0
    
    def test_deployment_exists(self, temp_db):
        """Test checking if deployment exists"""
        deployment = Deployment(
            id="test-deployment",
            name="test",
            tester_email="test@example.com",
            openspp_version="openspp-17.0.1.2.1",
            port_base=18000
        )
        
        temp_db.save_deployment(deployment)
        
        assert temp_db.deployment_exists("test-deployment") == True
        assert temp_db.deployment_exists("nonexistent") == False