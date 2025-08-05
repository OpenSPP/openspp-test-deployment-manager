#!/usr/bin/env python3
"""Clean up all test deployments"""

import shutil
import os
from pathlib import Path

# Remove deployment directories
deployment_path = Path("/Users/jeremi/Projects/134-openspp/openspp-deployment-manager/deployments")
for dep in deployment_path.glob("jeremi-test*"):
    print(f"Removing {dep}...")
    try:
        shutil.rmtree(dep)
        print(f"  ✓ Removed {dep.name}")
    except Exception as e:
        print(f"  ✗ Failed: {e}")

# Remove database file
db_file = Path("/Users/jeremi/Projects/134-openspp/openspp-deployment-manager/deployments.db")
if db_file.exists():
    print(f"Removing database...")
    try:
        db_file.unlink()
        print("  ✓ Database removed")
    except Exception as e:
        print(f"  ✗ Failed: {e}")

print("\nCleanup complete!")