# ABOUTME: Tests for data models and enums
# ABOUTME: Validates DeploymentStatus enum and model serialization

import pytest
from datetime import datetime
from src.models import DeploymentStatus, Deployment, AppConfig, DeploymentParams


class TestDeploymentStatus:
    """Test the DeploymentStatus enum"""
    
    def test_status_values(self):
        """Test that all expected status values exist"""
        assert DeploymentStatus.CREATING.value == "creating"
        assert DeploymentStatus.RUNNING.value == "running"
        assert DeploymentStatus.STOPPED.value == "stopped"
        assert DeploymentStatus.ERROR.value == "error"
        assert DeploymentStatus.UPDATING.value == "updating"
    
    def test_status_from_string(self):
        """Test creating status from string value"""
        status = DeploymentStatus("running")
        assert status == DeploymentStatus.RUNNING
        
        with pytest.raises(ValueError):
            DeploymentStatus("invalid_status")


class TestDeployment:
    """Test the Deployment model"""
    
    def test_deployment_creation(self):
        """Test creating a deployment with all fields"""
        deployment = Deployment(
            id="test-deployment",
            name="test",
            tester_email="test@example.com",
            openspp_version="openspp-17.0.1.2.1",
            port_base=18000
        )
        
        assert deployment.id == "test-deployment"
        assert deployment.name == "test"
        assert deployment.status == DeploymentStatus.CREATING
        assert deployment.environment == "devel"
        assert deployment.port_base == 18000
    
    def test_deployment_to_dict(self):
        """Test serializing deployment to dictionary"""
        now = datetime.now()
        deployment = Deployment(
            id="test-deployment",
            name="test",
            tester_email="test@example.com",
            openspp_version="openspp-17.0.1.2.1",
            created_at=now,
            last_updated=now,
            status=DeploymentStatus.RUNNING,
            port_base=18000,
            port_mappings={"odoo": 18000, "smtp": 18025}
        )
        
        data = deployment.to_dict()
        
        assert data["id"] == "test-deployment"
        assert data["status"] == DeploymentStatus.RUNNING  # Should be enum, not string
        assert data["created_at"] == now.isoformat()
        assert data["port_mappings"]["odoo"] == 18000
    
    def test_deployment_from_dict(self):
        """Test creating deployment from dictionary"""
        now = datetime.now()
        data = {
            "id": "test-deployment",
            "name": "test",
            "tester_email": "test@example.com",
            "openspp_version": "openspp-17.0.1.2.1",
            "dependency_versions": {},
            "environment": "devel",
            "status": "running",
            "created_at": now.isoformat(),
            "last_updated": now.isoformat(),
            "port_base": 18000,
            "port_mappings": {},
            "subdomain": "test.local",
            "modules_installed": [],
            "last_action": "",
            "notes": ""
        }
        
        deployment = Deployment.from_dict(data)
        
        assert deployment.id == "test-deployment"
        assert deployment.status == "running"  # Will be converted to enum later
        assert isinstance(deployment.created_at, datetime)


class TestAppConfig:
    """Test the AppConfig model"""
    
    def test_default_config(self):
        """Test default configuration values"""
        config = AppConfig()
        
        assert config.base_deployment_path == "./deployments"
        assert config.port_range_start == 18000
        assert config.port_range_end == 19000
        assert config.port_increment == 100
        assert config.max_deployments_per_tester == 3
        assert config.nginx_enabled == True
    
    def test_config_from_yaml(self):
        """Test loading config from YAML data"""
        yaml_data = {
            "deployment": {
                "base_path": "/custom/path",
                "max_per_tester": 5
            },
            "ports": {
                "range_start": 20000,
                "range_end": 21000
            },
            "nginx": {
                "enabled": False
            }
        }
        
        config = AppConfig.from_yaml(yaml_data)
        
        assert config.base_deployment_path == "/custom/path"
        assert config.max_deployments_per_tester == 5
        assert config.port_range_start == 20000
        assert config.port_range_end == 21000
        assert config.nginx_enabled == False


class TestDeploymentParams:
    """Test the DeploymentParams model"""
    
    def test_params_validation(self):
        """Test parameter validation"""
        # Valid params
        params = DeploymentParams(
            tester_email="test@example.com",
            name="valid-name",
            environment="devel"
        )
        errors = params.validate()
        assert len(errors) == 0
        
        # Invalid email
        params = DeploymentParams(
            tester_email="invalid-email",
            name="valid-name"
        )
        errors = params.validate()
        assert "Invalid tester email" in errors
        
        # Invalid name
        params = DeploymentParams(
            tester_email="test@example.com",
            name="invalid name with spaces"
        )
        errors = params.validate()
        assert any("Name must be" in err for err in errors)
        
        # Invalid environment
        params = DeploymentParams(
            tester_email="test@example.com",
            name="valid-name",
            environment="production"  # Should be 'prod'
        )
        errors = params.validate()
        assert "Environment must be devel, test, or prod" in errors
    
    def test_tester_property(self):
        """Test extracting tester identifier from email"""
        params = DeploymentParams(
            tester_email="john.doe@example.com",
            name="test"
        )
        assert params.tester == "john-doe"
        
        params = DeploymentParams(
            tester_email="simple@test.com",
            name="test"
        )
        assert params.tester == "simple"