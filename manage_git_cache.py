#!/usr/bin/env python3
# ABOUTME: Utility script for managing and optimizing git cache
# ABOUTME: Provides commands to analyze, optimize, and clean up cached repositories

import argparse
import sys
import yaml
from pathlib import Path
from src.git_cache import GitCacheManager
from src.models import AppConfig
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


def analyze_cache(cache_manager: GitCacheManager):
    """Analyze current cache status and show statistics"""
    print("\n🔍 Analyzing Git Cache...\n")
    
    stats = cache_manager.get_repository_stats()
    
    print(f"📊 Cache Statistics:")
    print(f"  • Total repositories: {stats['repo_count']}")
    print(f"  • Total size: {stats['total_size_mb']:.2f} MB")
    print(f"  • Cache path: {cache_manager.cache_path}")
    
    if stats['optimization_potential_mb'] > 0:
        print(f"\n💡 Optimization Potential:")
        print(f"  • Could save ~{stats['optimization_potential_mb']:.2f} MB by converting to shallow clones")
    
    if stats['largest_repos']:
        print(f"\n📦 Largest Repositories:")
        for repo in stats['largest_repos']:
            shallow_indicator = " (shallow)" if repo['is_shallow'] else " (full)"
            print(f"  • {repo['name']}: {repo['size_mb']:.2f} MB{shallow_indicator}")
            print(f"    URL: {repo['url']}")
            print(f"    Last accessed: {repo['last_accessed']}")
    
    return stats


def optimize_cache(cache_manager: GitCacheManager, aggressive: bool = False):
    """Optimize cached repositories"""
    print("\n🔧 Optimizing Git Cache...\n")
    
    stats = cache_manager.get_repository_stats()
    
    total_saved = 0
    
    # Run git gc on all repos
    print("Running garbage collection on all repositories...")
    for repo in stats['repos']:
        saved = cache_manager.optimize_repo(repo['url'])
        total_saved += saved
    
    # Convert large non-shallow repos to shallow if aggressive mode
    if aggressive:
        print("\n🚀 Converting large repositories to shallow clones...")
        for repo in stats['repos']:
            if not repo['is_shallow'] and repo['size_mb'] > 100:
                print(f"  Converting {repo['name']} to shallow clone...")
                if cache_manager.convert_to_shallow(repo['url']):
                    # Re-calculate saved space
                    new_size = cache_manager._get_repo_size(
                        cache_manager.get_cached_repo_path(repo['url'])
                    )
                    saved = repo['size'] - new_size
                    total_saved += saved
    
    print(f"\n✅ Optimization complete! Saved {total_saved/(1024*1024):.2f} MB")


def cleanup_cache(cache_manager: GitCacheManager, max_age_days: int):
    """Clean up old cached repositories"""
    print(f"\n🧹 Cleaning up repositories older than {max_age_days} days...\n")
    
    freed = cache_manager.cleanup_old_repos(max_age_days)
    
    if freed > 0:
        print(f"✅ Cleanup complete! Freed {freed/(1024*1024):.2f} MB")
    else:
        print("ℹ️  No old repositories to remove")


def convert_odoo_to_shallow(cache_manager: GitCacheManager):
    """Specifically optimize the Odoo repository"""
    print("\n🎯 Optimizing Odoo repository...\n")
    
    odoo_url = "https://github.com/odoo/odoo.git"
    repo_path = cache_manager.get_cached_repo_path(odoo_url)
    
    if not repo_path.exists():
        print("⚠️  Odoo repository not found in cache")
        print("   It will be shallow cloned on next use")
        return
    
    # Get current size
    size_before = cache_manager._get_repo_size(repo_path)
    print(f"Current Odoo repository size: {size_before/(1024*1024):.2f} MB")
    
    # Convert to shallow
    if cache_manager.convert_to_shallow(odoo_url, depth=1):
        size_after = cache_manager._get_repo_size(repo_path)
        saved = size_before - size_after
        print(f"✅ Successfully converted to shallow clone!")
        print(f"   New size: {size_after/(1024*1024):.2f} MB")
        print(f"   Saved: {saved/(1024*1024):.2f} MB ({(saved/size_before)*100:.1f}%)")
    else:
        print("❌ Failed to convert Odoo repository")


def clear_cache(cache_manager: GitCacheManager):
    """Clear all cached repositories"""
    response = input("\n⚠️  This will delete ALL cached repositories. Are you sure? (yes/no): ")
    if response.lower() == 'yes':
        cache_manager.clear_cache()
        print("✅ Cache cleared successfully!")
    else:
        print("❌ Operation cancelled")


def main():
    parser = argparse.ArgumentParser(description='Manage Git repository cache')
    parser.add_argument('command', choices=['analyze', 'optimize', 'cleanup', 'odoo', 'clear'],
                        help='Command to execute')
    parser.add_argument('--aggressive', action='store_true',
                        help='Aggressive optimization (converts to shallow clones)')
    parser.add_argument('--max-age', type=int, default=30,
                        help='Maximum age in days for cleanup (default: 30)')
    parser.add_argument('--config', type=str, default='config.yaml',
                        help='Path to config file (default: config.yaml)')
    
    args = parser.parse_args()
    
    # Load config and create cache manager
    try:
        with open(args.config, 'r') as f:
            config_data = yaml.safe_load(f)
        # Get git_cache_path from config or use default
        cache_path = config_data.get('git_cache_path', '.git_cache')
        cache_manager = GitCacheManager(cache_path)
    except Exception as e:
        logger.error(f"Failed to initialize: {e}")
        sys.exit(1)
    
    # Execute command
    if args.command == 'analyze':
        analyze_cache(cache_manager)
    elif args.command == 'optimize':
        optimize_cache(cache_manager, args.aggressive)
    elif args.command == 'cleanup':
        cleanup_cache(cache_manager, args.max_age)
    elif args.command == 'odoo':
        convert_odoo_to_shallow(cache_manager)
    elif args.command == 'clear':
        clear_cache(cache_manager)


if __name__ == '__main__':
    main()