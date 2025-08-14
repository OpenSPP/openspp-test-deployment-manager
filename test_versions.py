#!/usr/bin/env python3
# ABOUTME: Test script to debug why tags are not showing in the dropdown
# ABOUTME: Run this to see what versions are being detected

import sys
import logging
from pathlib import Path

# Add the src directory to the path
sys.path.insert(0, str(Path(__file__).parent))

from src.models import AppConfig
from src.deployment_manager import DeploymentManager

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

def test_version_fetching():
    """Test version fetching to see what's being detected"""
    # Load config
    config = AppConfig.from_file('config.yaml')
    
    print(f"Git cache enabled: {config.git_cache_enabled}")
    print(f"Git cache path: {config.git_cache_path}")
    
    # Create manager
    manager = DeploymentManager(config)
    
    # Force refresh
    print("\nRefreshing versions...")
    manager._refresh_available_versions()
    
    # Show results
    versions = manager.config.available_openspp_versions
    print(f"\nTotal versions found: {len(versions)}")
    
    # Categorize
    tags = [v for v in versions if v.startswith('v')]
    branches = [v for v in versions if not v.startswith('v')]
    
    print(f"\nTags found ({len(tags)}):")
    for tag in tags[:10]:  # Show first 10
        print(f"  - {tag}")
    if len(tags) > 10:
        print(f"  ... and {len(tags) - 10} more")
    
    print(f"\nBranches found ({len(branches)}):")
    for branch in branches[:10]:  # Show first 10
        print(f"  - {branch}")
    if len(branches) > 10:
        print(f"  ... and {len(branches) - 10} more")
    
    # Check specifically for v17.0.1.3
    if 'v17.0.1.3' in versions:
        print("\n✅ v17.0.1.3 IS in the list!")
    else:
        print("\n❌ v17.0.1.3 is NOT in the list")
        
        # Debug the is_likely_tag function
        print("\nTesting is_likely_tag function:")
        test_versions = ['v17.0.1.3', 'v17.0.1.2.1', '17.0', 'develop']
        import re
        for version in test_versions:
            is_tag = (
                version.startswith("v") or
                version.startswith("openspp-") or
                (re.search(r'\d+\.\d+\.\d+', version) and version not in ["15.0", "17.0"])
            )
            print(f"  {version}: {'TAG' if is_tag else 'BRANCH'}")

if __name__ == "__main__":
    test_version_fetching()