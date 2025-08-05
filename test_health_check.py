#!/usr/bin/env python3
# ABOUTME: Test script to verify improved health check logic
# ABOUTME: Checks Docker container health status for deployments

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from src.docker_handler import DockerComposeHandler
import logging

logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

def test_health_check(deployment_id: str):
    """Test health check for a deployment"""
    print(f"\n🔍 Testing health check for deployment: {deployment_id}\n")
    
    deployment_path = f"./deployments/{deployment_id}/openspp-docker"
    if not os.path.exists(deployment_path):
        print(f"❌ Deployment path not found: {deployment_path}")
        return
    
    handler = DockerComposeHandler(deployment_path, deployment_id)
    
    # Get container status
    print("📊 Container Status:")
    status = handler.get_container_status()
    
    for service, info in status.items():
        health = info.get('health', 'N/A')
        print(f"  {service}: status={info['status']}, health={health}")
    
    # Test wait_for_services
    print("\n⏳ Testing wait_for_services (with 30 second timeout)...")
    result = handler.wait_for_services(timeout=30)
    
    if result:
        print("✅ Services are ready!")
    else:
        print("❌ Services failed health check")
    
    return result

if __name__ == "__main__":
    if len(sys.argv) > 1:
        deployment_id = sys.argv[1]
    else:
        # Default to the most recent deployment
        deployment_id = "jeremi-test3"
    
    test_health_check(deployment_id)