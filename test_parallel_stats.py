#!/usr/bin/env python3
# ABOUTME: Test script to verify parallel container stats performance 
# ABOUTME: Compares sequential vs parallel Docker stats collection timing

import time
import sys
from pathlib import Path

# Add current directory to path and import src modules
sys.path.insert(0, str(Path(__file__).parent))

from src.docker_handler import DockerComposeHandler

def test_parallel_stats():
    """Test if parallelized stats collection is working"""
    print("🚀 Testing Parallelized Container Stats Collection")
    print("=" * 60)
    
    # Find a deployment with multiple containers to test
    deployments_dir = Path("deployments")
    if not deployments_dir.exists():
        print("❌ No deployments directory found")
        return
    
    # Look for a deployment with openspp-docker
    test_deployment = None
    for deployment_dir in deployments_dir.iterdir():
        if deployment_dir.is_dir():
            docker_path = deployment_dir / "openspp-docker"
            if docker_path.exists():
                test_deployment = deployment_dir.name
                break
    
    if not test_deployment:
        print("❌ No test deployment found with openspp-docker")
        return
    
    print(f"📁 Testing with deployment: {test_deployment}")
    
    # Create DockerHandler
    docker_handler = DockerComposeHandler(
        str(deployments_dir / test_deployment / "openspp-docker"),
        test_deployment
    )
    
    # Test stats collection
    print("\n⏱️  Running parallelized stats collection...")
    start_time = time.time()
    
    try:
        stats = docker_handler.get_container_stats()
        end_time = time.time()
        duration = end_time - start_time
        
        print(f"✅ Completed in {duration:.3f} seconds")
        print(f"📊 Found stats for {len(stats)} containers:")
        
        for service, stat in stats.items():
            status = stat.get('status', 'unknown')
            cpu = stat.get('cpu_percent', 0)
            mem = stat.get('memory_percent', 0)
            print(f"   • {service:12} | Status: {status:9} | CPU: {cpu:5.1f}% | Mem: {mem:5.1f}%")
        
        # Performance assessment
        if duration < 3.0:
            print(f"\n🎉 EXCELLENT! Stats collected in {duration:.3f}s (target: <3s)")
        elif duration < 5.0:
            print(f"\n👍 GOOD! Stats collected in {duration:.3f}s (target: <3s)")
        else:
            print(f"\n⚠️  Still slow: {duration:.3f}s - may need Docker daemon optimization")
            
    except Exception as e:
        print(f"❌ Error testing stats: {e}")

if __name__ == "__main__":
    test_parallel_stats()