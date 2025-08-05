#!/usr/bin/env python3
# ABOUTME: Demo script showing how to use OpenSPP Deployment Manager
# ABOUTME: Demonstrates API usage without requiring Docker

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from src.models import AppConfig, DeploymentParams, Deployment, DeploymentStatus
from src.database import DeploymentDatabase
from src.deployment_manager import DeploymentManager

def main():
    print("\n🚀 OpenSPP Deployment Manager - Demo\n")
    print("This demo shows the API usage without creating actual Docker containers.\n")
    
    # 1. Create configuration
    print("1️⃣ Creating configuration...")
    config = AppConfig()
    config.base_deployment_path = "./demo_deployments"
    config.nginx_enabled = False  # Disable for demo
    print(f"   ✅ Base path: {config.base_deployment_path}")
    print(f"   ✅ Port range: {config.port_range_start}-{config.port_range_end}")
    
    # 2. Initialize deployment manager
    print("\n2️⃣ Initializing deployment manager...")
    manager = DeploymentManager(config)
    print("   ✅ Manager initialized")
    
    # 3. Create deployment parameters
    print("\n3️⃣ Creating deployment parameters...")
    params = DeploymentParams(
        tester_email="demo@example.com",
        name="demo-app",
        environment="devel",
        openspp_version="openspp-17.0.1.2.1",
        notes="Demo deployment for testing"
    )
    
    # Validate parameters
    errors = params.validate()
    if errors:
        print("   ❌ Validation errors:")
        for error in errors:
            print(f"      - {error}")
        return 1
    
    print("   ✅ Parameters validated")
    print(f"   - Tester: {params.tester_email}")
    print(f"   - Name: {params.name}")
    print(f"   - Version: {params.openspp_version}")
    
    # 4. Check deployment limits
    print("\n4️⃣ Checking deployment limits...")
    can_create = manager._check_deployment_limits(params.tester_email)
    current_count = manager.db.count_tester_deployments(params.tester_email)
    print(f"   ✅ Current deployments: {current_count}/{config.max_deployments_per_tester}")
    print(f"   ✅ Can create new deployment: {can_create}")
    
    # 5. Simulate deployment creation (without Docker)
    print("\n5️⃣ Simulating deployment creation...")
    
    # Allocate port
    deployment_id = f"{params.tester}-{params.name}"
    port_base = manager.db.allocate_port_range(deployment_id)
    print(f"   ✅ Allocated port range: {port_base}-{port_base + 99}")
    
    # Create deployment object
    deployment = Deployment(
        id=deployment_id,
        name=params.name,
        tester_email=params.tester_email,
        openspp_version=params.openspp_version,
        environment=params.environment,
        status=DeploymentStatus.CREATING,
        port_base=port_base,
        port_mappings={
            "odoo": port_base,
            "smtp": port_base + 25,
            "pgweb": port_base + 81
        },
        subdomain=f"{deployment_id}.test.local",
        notes=params.notes
    )
    
    # Save to database
    manager.db.save_deployment(deployment)
    print(f"   ✅ Deployment saved to database")
    
    # 6. Query deployments
    print("\n6️⃣ Querying deployments...")
    
    # Get all deployments
    all_deployments = manager.db.get_all_deployments()
    print(f"   ✅ Total deployments: {len(all_deployments)}")
    
    # Get deployments by tester
    tester_deployments = manager.db.get_deployments_by_tester(params.tester_email)
    print(f"   ✅ Deployments for {params.tester_email}: {len(tester_deployments)}")
    
    # Get deployment by ID
    retrieved = manager.db.get_deployment(deployment_id)
    if retrieved:
        print(f"   ✅ Retrieved deployment: {retrieved.id}")
        print(f"      - Status: {retrieved.status.value}")
        print(f"      - Port: {retrieved.port_base}")
        print(f"      - Created: {retrieved.created_at}")
    
    # 7. Update deployment status
    print("\n7️⃣ Updating deployment status...")
    manager.db.update_deployment_status(
        deployment_id, 
        DeploymentStatus.RUNNING,
        "Demo completed"
    )
    print("   ✅ Status updated to RUNNING")
    
    # 8. Cleanup
    print("\n8️⃣ Cleaning up...")
    
    # Delete deployment
    manager.db.delete_deployment(deployment_id)
    print("   ✅ Deployment deleted from database")
    
    # Clean up directories
    import shutil
    if os.path.exists(config.base_deployment_path):
        shutil.rmtree(config.base_deployment_path)
    if os.path.exists("deployments.db"):
        os.unlink("deployments.db")
    print("   ✅ Cleaned up files")
    
    print("\n" + "=" * 60)
    print("✅ Demo completed successfully!")
    print("=" * 60)
    print("\n📝 What you've seen:")
    print("- Configuration and initialization")
    print("- Parameter validation")
    print("- Port allocation")
    print("- Database operations (CRUD)")
    print("- Status management")
    print("\n🎉 The deployment manager is working correctly!")
    print("\n💡 To create actual deployments, ensure Docker is running")
    print("   and use the Streamlit UI: uv run streamlit run app.py")
    
    return 0

if __name__ == "__main__":
    sys.exit(main())