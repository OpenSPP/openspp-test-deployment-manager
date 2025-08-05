# ABOUTME: Tests for deployment manager core functionality
# ABOUTME: Validates deployment lifecycle and management operations

import pytest
import tempfile
import os
from unittest.mock import patch, MagicMock, call
from src.deployment_manager import DeploymentManager
from src.models import AppConfig, DeploymentParams, DeploymentStatus
from src.database import DeploymentDatabase


@pytest.fixture
def temp_deployment_dir():
    """Create temporary deployment directory"""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield tmpdir


@pytest.fixture
def mock_config(temp_deployment_dir):
    """Create test configuration"""
    config = AppConfig()
    config.base_deployment_path = temp_deployment_dir
    config.nginx_enabled = False  # Disable nginx for tests
    config.available_openspp_versions = ["openspp-17.0.1.2.1", "openspp-17.0.1.2.0"]
    return config


@pytest.fixture
def temp_db():
    """Create temporary database"""
    fd, path = tempfile.mkstemp(suffix='.db')
    os.close(fd)
    yield path
    os.unlink(path)


class TestDeploymentManager:
    """Test deployment manager operations"""
    
    @patch('src.deployment_manager.DeploymentDatabase')
    def test_initialization(self, mock_db_class, mock_config):
        """Test deployment manager initialization"""
        manager = DeploymentManager(mock_config)
        
        assert manager.config == mock_config
        assert manager.db is not None
        assert os.path.exists(mock_config.base_deployment_path)
    
    def test_check_deployment_limits(self, mock_config):
        """Test deployment limit checking"""
        with patch('src.deployment_manager.DeploymentDatabase') as mock_db_class:
            mock_db = MagicMock()
            mock_db_class.return_value = mock_db
            
            manager = DeploymentManager(mock_config)
            
            # Under limit
            mock_db.count_tester_deployments.return_value = 2
            assert manager._check_deployment_limits("test@example.com") == True
            
            # At limit
            mock_db.count_tester_deployments.return_value = 3
            assert manager._check_deployment_limits("test@example.com") == False
    
    def test_deployment_params_validation(self):
        """Test deployment parameter validation"""
        # Valid params
        params = DeploymentParams(
            tester_email="test@example.com",
            name="valid-name",
            environment="devel"
        )
        errors = params.validate()
        assert len(errors) == 0
        
        # Invalid params
        params = DeploymentParams(
            tester_email="invalid",
            name="",
            environment="invalid"
        )
        errors = params.validate()
        assert len(errors) >= 3
    
    @patch('src.deployment_manager.git')
    @patch('src.deployment_manager.DockerComposeHandler')
    def test_create_deployment_validation_failure(self, mock_docker, mock_git, mock_config):
        """Test deployment creation with validation failure"""
        with patch('src.deployment_manager.DeploymentDatabase') as mock_db_class:
            manager = DeploymentManager(mock_config)
            
            # Invalid parameters
            params = DeploymentParams(
                tester_email="invalid-email",
                name="",
                environment="devel"
            )
            
            success, message, deployment = manager.create_deployment(params)
            
            assert success == False
            assert "Validation failed" in message
            assert deployment is None
    
    @patch('src.deployment_manager.git')
    @patch('src.deployment_manager.DockerComposeHandler')
    def test_create_deployment_limit_reached(self, mock_docker, mock_git, mock_config):
        """Test deployment creation when limit is reached"""
        with patch('src.deployment_manager.DeploymentDatabase') as mock_db_class:
            mock_db = MagicMock()
            mock_db_class.return_value = mock_db
            mock_db.count_tester_deployments.return_value = 3  # At limit
            
            manager = DeploymentManager(mock_config)
            
            params = DeploymentParams(
                tester_email="test@example.com",
                name="test-app",
                environment="devel"
            )
            
            success, message, deployment = manager.create_deployment(params)
            
            assert success == False
            assert "limit reached" in message
            assert deployment is None
    
    @patch('src.deployment_manager.DeploymentDatabase')
    def test_start_stop_deployment(self, mock_db_class, mock_config):
        """Test starting and stopping deployments"""
        mock_db = MagicMock()
        mock_db_class.return_value = mock_db
        
        # Create mock deployment
        mock_deployment = MagicMock()
        mock_deployment.id = "test-deployment"
        mock_deployment.status = DeploymentStatus.STOPPED
        mock_db.get_deployment.return_value = mock_deployment
        
        with patch('src.deployment_manager.DockerComposeHandler') as mock_docker_class:
            mock_docker = MagicMock()
            mock_docker_class.return_value = mock_docker
            
            # Mock successful start
            mock_result = MagicMock()
            mock_result.success = True
            mock_docker.start.return_value = mock_result
            
            manager = DeploymentManager(mock_config)
            
            # Test start
            success, message = manager.start_deployment("test-deployment")
            assert success == True
            assert "started" in message.lower()
            
            # Verify status was updated
            assert mock_deployment.status == DeploymentStatus.RUNNING
            mock_db.save_deployment.assert_called_with(mock_deployment)
            
            # Test stop
            mock_deployment.status = DeploymentStatus.RUNNING
            mock_docker.stop.return_value = mock_result
            
            success, message = manager.stop_deployment("test-deployment")
            assert success == True
            assert "stopped" in message.lower()
            assert mock_deployment.status == DeploymentStatus.STOPPED
    
    @patch('src.deployment_manager.DeploymentDatabase')
    def test_delete_deployment(self, mock_db_class, mock_config):
        """Test deleting a deployment"""
        mock_db = MagicMock()
        mock_db_class.return_value = mock_db
        
        # Create mock deployment
        mock_deployment = MagicMock()
        mock_deployment.id = "test-deployment"
        mock_db.get_deployment.return_value = mock_deployment
        
        with patch('src.deployment_manager.DockerComposeHandler') as mock_docker_class:
            mock_docker = MagicMock()
            mock_docker_class.return_value = mock_docker
            
            with patch('src.deployment_manager.cleanup_deployment_directory') as mock_cleanup:
                manager = DeploymentManager(mock_config)
                
                success, message = manager.delete_deployment("test-deployment")
                
                assert success == True
                assert "deleted successfully" in message.lower()
                
                # Verify cleanup was called
                mock_docker.down.assert_called_with(volumes=True)
                mock_docker.cleanup_volumes.assert_called_once()
                mock_cleanup.assert_called_once()
                mock_db.delete_deployment.assert_called_with("test-deployment")
    
    def test_get_available_dependency_branches(self, mock_config):
        """Test fetching available dependency branches"""
        with patch('src.deployment_manager.DeploymentDatabase'):
            with patch('src.deployment_manager.run_command_with_retry') as mock_run:
                # Mock successful git ls-remote
                mock_result = MagicMock()
                mock_result.returncode = 0
                mock_result.stdout = """
                a1b2c3d4 refs/heads/main
                e5f6g7h8 refs/heads/17.0-develop-openspp
                i9j0k1l2 refs/heads/17.0-develop
                """
                mock_run.return_value = mock_result
                
                manager = DeploymentManager(mock_config)
                branches = manager.get_available_dependency_branches("openg2p_registry")
                
                assert len(branches) == 2  # Only branches with 'openspp' or 'develop'
                assert "17.0-develop-openspp" in branches
                assert "17.0-develop" in branches
                assert "main" not in branches  # Filtered out