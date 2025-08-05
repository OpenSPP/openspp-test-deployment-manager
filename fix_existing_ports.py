#!/usr/bin/env python3
"""Fix port configuration for existing deployments"""

import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

from src.models import AppConfig
from src.deployment_manager import DeploymentManager

def main():
    print("Fixing port configuration for existing deployments...")
    
    # Load config and create manager
    config = AppConfig()
    manager = DeploymentManager(config)
    
    # Get all deployments
    deployments = manager.get_all_deployments()
    
    if not deployments:
        print("No deployments found.")
        return
    
    # Fix each deployment
    for deployment in deployments:
        print(f"\nFixing {deployment.id}...")
        success, message = manager.fix_deployment_ports(deployment.id)
        if success:
            print(f"✓ {message}")
        else:
            print(f"✗ Failed: {message}")
    
    print("\nDone! Remember to restart running deployments for changes to take effect.")

if __name__ == "__main__":
    main()