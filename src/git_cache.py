# ABOUTME: Git repository cache manager for faster deployments
# ABOUTME: Caches git repositories to avoid repeated clones

import os
import shutil
import logging
import time
from pathlib import Path
from typing import Dict, Optional, List
from datetime import datetime, timedelta
import git
from .utils import run_command_with_retry, ensure_directory

logger = logging.getLogger(__name__)


class GitCacheManager:
    """Manages cached git repositories for faster deployment"""
    
    def __init__(self, cache_path: str):
        self.cache_path = Path(cache_path)
        ensure_directory(str(self.cache_path))
        # Add caching for branches/tags to avoid repeated fetches
        self._branch_cache = {}  # {repo_url: {'branches': [...], 'tags': [...], 'timestamp': ...}}
        self._cache_ttl = timedelta(minutes=5)  # Cache for 5 minutes
        self._last_fetch = {}  # Track last fetch time per repo
        
    def get_cache_key(self, repo_url: str) -> str:
        """Generate cache key from repository URL"""
        # Extract repo name from URL
        # https://github.com/openspp/openspp-modules.git -> openspp_openspp-modules
        parts = repo_url.rstrip('.git').split('/')
        if len(parts) >= 2:
            org = parts[-2]
            repo = parts[-1]
            return f"{org}_{repo}"
        return repo_url.replace('/', '_').replace(':', '_')
    
    def get_cached_repo_path(self, repo_url: str) -> Path:
        """Get path to cached repository"""
        cache_key = self.get_cache_key(repo_url)
        return self.cache_path / cache_key
    
    def update_or_clone_repo(self, repo_url: str, branch: Optional[str] = None, force_update: bool = False) -> Path:
        """Update existing repo or clone new one"""
        repo_path = self.get_cached_repo_path(repo_url)
        
        if repo_path.exists():
            # Check if update is needed based on cache TTL
            if not force_update and not self._should_fetch(repo_url):
                logger.info(f"Using cached repository (still fresh): {repo_url}")
                
                # If specific branch requested, just checkout without pulling
                if branch:
                    try:
                        repo = git.Repo(repo_path)
                        repo.git.checkout(branch)
                    except git.GitCommandError:
                        # Might be a tag, try checking it out
                        repo.git.checkout(branch)
                
                return repo_path
            
            logger.info(f"Updating cached repository: {repo_url}")
            try:
                repo = git.Repo(repo_path)
                
                # Fetch all branches and tags
                repo.git.fetch('--all', '--tags')
                self._last_fetch[repo_url] = datetime.now()
                
                # If specific branch requested, checkout
                if branch:
                    try:
                        repo.git.checkout(branch)
                        repo.git.pull('origin', branch)
                    except git.GitCommandError:
                        # Might be a tag, try checking it out
                        repo.git.checkout(branch)
                
                logger.info(f"Updated cached repository: {repo_url}")
                return repo_path
                
            except Exception as e:
                logger.error(f"Failed to update cached repo {repo_url}: {e}")
                logger.info("Will remove and re-clone")
                shutil.rmtree(repo_path)
        
        # Clone new repository
        logger.info(f"Cloning repository to cache: {repo_url}")
        try:
            # Clone with all branches
            git.Repo.clone_from(
                repo_url,
                repo_path,
                branch=branch,
                no_single_branch=True  # Clone all branches
            )
            # Record fetch time for new clone
            self._last_fetch[repo_url] = datetime.now()
            logger.info(f"Cloned repository to cache: {repo_path}")
            return repo_path
            
        except Exception as e:
            logger.error(f"Failed to clone repository {repo_url}: {e}")
            raise
    
    def copy_to_destination(self, repo_url: str, dest_path: str, 
                          exclude_git: bool = False) -> bool:
        """Copy cached repository to destination"""
        cached_path = self.get_cached_repo_path(repo_url)
        
        if not cached_path.exists():
            logger.error(f"No cached repository found for {repo_url}")
            return False
        
        try:
            # Ensure destination parent exists
            dest = Path(dest_path)
            dest.parent.mkdir(parents=True, exist_ok=True)
            
            if exclude_git:
                # Copy without .git directory
                shutil.copytree(
                    cached_path,
                    dest,
                    ignore=shutil.ignore_patterns('.git')
                )
            else:
                # Copy entire repository including .git
                shutil.copytree(cached_path, dest)
            
            logger.info(f"Copied cached repository to {dest_path}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to copy repository: {e}")
            return False
    
    def _is_cache_valid(self, repo_url: str) -> bool:
        """Check if cached branch/tag data is still valid"""
        if repo_url not in self._branch_cache:
            return False
        timestamp = self._branch_cache[repo_url].get('timestamp')
        if not timestamp:
            return False
        return datetime.now() - timestamp < self._cache_ttl
    
    def _should_fetch(self, repo_url: str) -> bool:
        """Check if we should fetch from remote"""
        if repo_url not in self._last_fetch:
            return True
        return datetime.now() - self._last_fetch[repo_url] > self._cache_ttl
    
    def get_available_branches(self, repo_url: str) -> List[str]:
        """Get list of available branches from cached repo"""
        # Check in-memory cache first
        if self._is_cache_valid(repo_url):
            return self._branch_cache[repo_url].get('branches', [])
        
        repo_path = self.get_cached_repo_path(repo_url)
        
        if not repo_path.exists():
            # Update cache first
            self.update_or_clone_repo(repo_url)
        
        try:
            repo = git.Repo(repo_path)
            
            # Only fetch if needed
            if self._should_fetch(repo_url):
                repo.git.fetch('--all')
                self._last_fetch[repo_url] = datetime.now()
            
            branches = []
            for ref in repo.references:
                if ref.name.startswith('origin/') and not ref.name.endswith('/HEAD'):
                    branch_name = ref.name.replace('origin/', '')
                    branches.append(branch_name)
            
            branches = sorted(branches)
            
            # Update cache
            if repo_url not in self._branch_cache:
                self._branch_cache[repo_url] = {}
            self._branch_cache[repo_url]['branches'] = branches
            self._branch_cache[repo_url]['timestamp'] = datetime.now()
            
            return branches
            
        except Exception as e:
            logger.error(f"Failed to get branches for {repo_url}: {e}")
            return []
    
    def get_available_tags(self, repo_url: str) -> List[str]:
        """Get list of available tags from cached repo"""
        # Check in-memory cache first
        if self._is_cache_valid(repo_url):
            return self._branch_cache[repo_url].get('tags', [])
        
        repo_path = self.get_cached_repo_path(repo_url)
        
        if not repo_path.exists():
            # Update cache first
            self.update_or_clone_repo(repo_url)
        
        try:
            repo = git.Repo(repo_path)
            
            # Only fetch if needed
            if self._should_fetch(repo_url):
                repo.git.fetch('--tags')
                self._last_fetch[repo_url] = datetime.now()
            
            tags = [tag.name for tag in repo.tags]
            tags = sorted(tags, reverse=True)
            
            # Update cache
            if repo_url not in self._branch_cache:
                self._branch_cache[repo_url] = {}
            self._branch_cache[repo_url]['tags'] = tags
            self._branch_cache[repo_url]['timestamp'] = datetime.now()
            
            return tags
            
        except Exception as e:
            logger.error(f"Failed to get tags for {repo_url}: {e}")
            return []
    
    def clear_cache(self):
        """Clear all cached repositories"""
        if self.cache_path.exists():
            shutil.rmtree(self.cache_path)
            self.cache_path.mkdir()
            logger.info("Cleared git cache")
        # Also clear in-memory cache
        self._branch_cache.clear()
        self._last_fetch.clear()
    
    def get_cache_size(self) -> int:
        """Get total size of cache in bytes"""
        total_size = 0
        for dirpath, dirnames, filenames in os.walk(self.cache_path):
            for filename in filenames:
                filepath = os.path.join(dirpath, filename)
                total_size += os.path.getsize(filepath)
        return total_size
    
    def get_cache_info(self) -> Dict:
        """Get information about cached repositories"""
        info = {
            'path': str(self.cache_path),
            'size': self.get_cache_size(),
            'repositories': []
        }
        
        for repo_dir in self.cache_path.iterdir():
            if repo_dir.is_dir() and (repo_dir / '.git').exists():
                try:
                    repo = git.Repo(repo_dir)
                    origin = repo.remotes.origin.url if repo.remotes else 'Unknown'
                    
                    info['repositories'].append({
                        'name': repo_dir.name,
                        'url': origin,
                        'last_updated': os.path.getmtime(repo_dir),
                        'size': sum(
                            os.path.getsize(os.path.join(dirpath, filename))
                            for dirpath, _, filenames in os.walk(repo_dir)
                            for filename in filenames
                        )
                    })
                except Exception as e:
                    logger.error(f"Failed to get info for {repo_dir}: {e}")
        
        return info
    
    def prewarm_cache(self, repo_urls: List[str]) -> None:
        """Pre-warm cache for multiple repositories"""
        logger.info(f"Pre-warming cache for {len(repo_urls)} repositories")
        for repo_url in repo_urls:
            try:
                # This will fetch branches and tags and cache them
                self.get_available_branches(repo_url)
                self.get_available_tags(repo_url)
            except Exception as e:
                logger.error(f"Failed to pre-warm cache for {repo_url}: {e}")