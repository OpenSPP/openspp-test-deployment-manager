#!/usr/bin/env python3
# ABOUTME: Script to clear git cache and force refresh of tags/branches
# ABOUTME: Run this to fix missing tags in the deployment dropdown

import shutil
from pathlib import Path
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def clear_git_cache():
    """Clear the git cache to force fresh fetch of tags"""
    cache_path = Path(".git_cache")
    
    if cache_path.exists():
        logger.info(f"Clearing git cache at {cache_path}")
        shutil.rmtree(cache_path)
        logger.info("Git cache cleared successfully")
    else:
        logger.info("No git cache found")
    
    # Also clear any app session state cache if running
    logger.info("Please restart the deployment manager to fetch fresh tags")

if __name__ == "__main__":
    clear_git_cache()