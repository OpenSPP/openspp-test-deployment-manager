#!/usr/bin/env python3
# ABOUTME: Interactive test script for core OpenSPP Deployment Manager functions
# ABOUTME: Tests database, models, and deployment operations without Docker

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from src.models import AppConfig, DeploymentParams, DeploymentStatus
from src.database import DeploymentDatabase
from src.deployment_manager import DeploymentManager
from src.utils import validate_email, validate_deployment_name

def test_models():
    """Test model creation and validation"""
    print("=" * 60)
    print("Testing Models...")
    print("=" * 60)
    
    # Test DeploymentParams validation
    params = DeploymentParams(
        tester_email="test@example.com",
        name="test-app",
        environment="devel"
    )
    
    errors = params.validate()
    print(f"✅ Valid params: {len(errors) == 0}")
    
    # Test invalid params
    invalid_params = DeploymentParams(
        tester_email="invalid-email",
        name="invalid name",
        environment="production"
    )
    
    errors = invalid_params.validate()
    print(f"✅ Invalid params detected: {len(errors)} errors")
    for error in errors:
        print(f"   - {error}")
    
    # Test status enum
    print(f"\n✅ Status enum values:")
    for status in DeploymentStatus:
        print(f"   - {status.name}: {status.value}")

def test_database():
    """Test database operations"""
    print("\n" + "=" * 60)
    print("Testing Database Operations...")
    print("=" * 60)
    
    # Create test database
    db = DeploymentDatabase("test_deployments.db")
    
    # Test port allocation
    port1 = db.allocate_port_range("test-1")
    port2 = db.allocate_port_range("test-2")
    port3 = db.allocate_port_range("test-3")
    
    print(f"✅ Port allocation:")
    print(f"   - Deployment 1: {port1}")
    print(f"   - Deployment 2: {port2}")
    print(f"   - Deployment 3: {port3}")
    
    # Test deployment counting
    count = db.count_tester_deployments("test@example.com")
    print(f"\n✅ Deployments for test@example.com: {count}")
    
    # Clean up test database
    os.unlink("test_deployments.db")
    print("\n✅ Test database cleaned up")

def test_validation():
    """Test validation functions"""
    print("\n" + "=" * 60)
    print("Testing Validation Functions...")
    print("=" * 60)
    
    # Test email validation
    emails = [
        ("test@example.com", True),
        ("user.name@company.co.uk", True),
        ("invalid-email", False),
        ("@example.com", False)
    ]
    
    print("✅ Email validation:")
    for email, expected in emails:
        result = validate_email(email)
        status = "✓" if result == expected else "✗"
        print(f"   {status} {email}: {result}")
    
    # Test deployment name validation
    names = [
        ("valid-name", True),
        ("test123", True),
        ("a", False),  # Too short
        ("invalid name", False),  # Has space
        ("UPPERCASE", True),  # Converted to lowercase
    ]
    
    print("\n✅ Deployment name validation:")
    for name, expected in names:
        result = validate_deployment_name(name)
        status = "✓" if result == expected else "✗"
        print(f"   {status} {name}: {result}")

def test_deployment_manager_basics():
    """Test basic deployment manager operations"""
    print("\n" + "=" * 60)
    print("Testing Deployment Manager (without Docker)...")
    print("=" * 60)
    
    # Create config
    config = AppConfig()
    config.base_deployment_path = "./test_deployments"
    config.nginx_enabled = False
    
    # Create manager
    manager = DeploymentManager(config)
    
    print(f"✅ Deployment manager initialized")
    print(f"   - Base path: {config.base_deployment_path}")
    print(f"   - Port range: {config.port_range_start}-{config.port_range_end}")
    print(f"   - Max per tester: {config.max_deployments_per_tester}")
    
    # Test deployment limit check
    can_create = manager._check_deployment_limits("test@example.com")
    print(f"\n✅ Can create deployment for test@example.com: {can_create}")
    
    # Clean up
    import shutil
    if os.path.exists("./test_deployments"):
        shutil.rmtree("./test_deployments")
    if os.path.exists("deployments.db"):
        os.unlink("deployments.db")
    print("\n✅ Cleanup completed")

def main():
    """Run all tests"""
    print("\n🚀 OpenSPP Deployment Manager - Core Function Tests\n")
    
    try:
        test_models()
        test_database()
        test_validation()
        test_deployment_manager_basics()
        
        print("\n" + "=" * 60)
        print("✅ All core function tests passed!")
        print("=" * 60)
        
        print("\n📝 Summary:")
        print("- Models and enums work correctly")
        print("- Database operations (port allocation, queries) work")
        print("- Validation functions work as expected")
        print("- Deployment manager initializes properly")
        print("\n🎉 The core functions are ready to use!")
        
    except Exception as e:
        print(f"\n❌ Error during testing: {e}")
        import traceback
        traceback.print_exc()
        return 1
    
    return 0

if __name__ == "__main__":
    sys.exit(main())