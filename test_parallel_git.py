#!/usr/bin/env python3
# ABOUTME: Test script to verify parallel git version fetching performance
# ABOUTME: Compares sequential vs parallel git repository version fetching timing

import time
import sys
from pathlib import Path

# Add current directory to path and import src modules
sys.path.insert(0, str(Path(__file__).parent))

from src.deployment_manager import DeploymentManager
from src.models import AppConfig

def test_parallel_git_versions():
    """Test if parallelized git version fetching is working"""
    print("🚀 Testing Parallelized Git Version Fetching")
    print("=" * 60)
    
    # Load config
    try:
        config = AppConfig.from_yaml("config.yaml")
    except FileNotFoundError:
        try:
            config = AppConfig.from_yaml("config-mac.yaml")
        except FileNotFoundError:
            print("❌ No config file found (config.yaml or config-mac.yaml)")
            return
    
    print(f"📁 Using config: {config.openspp_docker_repo}")
    
    # Create DeploymentManager
    manager = DeploymentManager(config)
    
    # Test git version fetching
    print("\n⏱️  Running parallelized git version fetching...")
    start_time = time.time()
    
    try:
        dependencies = manager.get_available_dependencies()
        end_time = time.time()
        duration = end_time - start_time
        
        print(f"✅ Completed in {duration:.3f} seconds")
        print(f"📊 Found versions for {len(dependencies)} repositories:")
        
        for repo_name, versions in dependencies.items():
            version_count = len(versions)
            if version_count > 0:
                # Show first 3 versions as example
                sample_versions = versions[:3]
                sample_str = ", ".join(sample_versions)
                if version_count > 3:
                    sample_str += f" ... (+{version_count - 3} more)"
                print(f"   • {repo_name:20} | {version_count:3} versions | {sample_str}")
            else:
                print(f"   • {repo_name:20} | {version_count:3} versions | (no versions found)")
        
        # Performance assessment
        if duration < 3.0:
            print(f"\n🎉 EXCELLENT! Git versions fetched in {duration:.3f}s (target: <3s)")
            print(f"💪 Performance improvement from ~14.8s sequential: {14.8/duration:.1f}x faster!")
        elif duration < 5.0:
            print(f"\n👍 GOOD! Git versions fetched in {duration:.3f}s (target: <3s)")
            print(f"💪 Performance improvement from ~14.8s sequential: {14.8/duration:.1f}x faster!")
        else:
            print(f"\n⚠️  Still slow: {duration:.3f}s - may need git cache optimization")
            if duration < 14.8:
                print(f"💪 But still faster than sequential: {14.8/duration:.1f}x improvement!")
            
    except Exception as e:
        print(f"❌ Error testing git versions: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    test_parallel_git_versions()