#!/usr/bin/env python3
# Quick test to verify all imports work correctly

import sys
sys.path.insert(0, 'src')

try:
    from models import AppConfig, Deployment, DeploymentParams
    print("✅ Models imported successfully")
    
    from database import DeploymentDatabase
    print("✅ Database imported successfully")
    
    from docker_handler import DockerComposeHandler
    print("✅ Docker handler imported successfully")
    
    from deployment_manager import DeploymentManager
    print("✅ Deployment manager imported successfully")
    
    from utils import validate_email, validate_deployment_name
    print("✅ Utils imported successfully")
    
    # Test config loading
    import yaml
    with open('config-mac.yaml', 'r') as f:
        config_data = yaml.safe_load(f)
    
    config = AppConfig.from_yaml(config_data)
    print(f"✅ Config loaded: nginx_enabled = {config.nginx_enabled}")
    
    print("\n🎉 All imports working correctly!")
    
except Exception as e:
    print(f"❌ Import error: {e}")
    import traceback
    traceback.print_exc()