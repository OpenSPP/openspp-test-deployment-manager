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
    
    def __init__(self, cache_path: str, shallow_depth: int = 1):
        self.cache_path = Path(cache_path)
        ensure_directory(str(self.cache_path))
        # Add caching for branches/tags to avoid repeated fetches
        self._branch_cache = {}  # {repo_url: {'branches': [...], 'tags': [...], 'timestamp': ...}}
        self._cache_ttl = timedelta(minutes=5)  # Cache for 5 minutes
        self._last_fetch = {}  # Track last fetch time per repo
        self.shallow_depth = shallow_depth  # Depth for shallow clones
        self.large_repo_patterns = ['odoo/odoo', 'OCA/OCB']  # Repos to always shallow clone
        
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
    
    def _is_large_repo(self, repo_url: str) -> bool:
        """Check if this is a known large repository that should be shallow cloned"""
        return any(pattern in repo_url for pattern in self.large_repo_patterns)
    
    def update_or_clone_repo(self, repo_url: str, branch: Optional[str] = None, force_update: bool = False, 
                           force_shallow: bool = None) -> Path:
        """Update existing repo or clone new one with optimized shallow cloning"""
        repo_path = self.get_cached_repo_path(repo_url)
        
        # Determine if we should use shallow clone
        use_shallow = force_shallow if force_shallow is not None else self._is_large_repo(repo_url)
        
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
                
                # For shallow repos, only fetch what we need
                if use_shallow:
                    if branch:
                        # Only fetch the specific branch with limited depth
                        repo.git.fetch('origin', branch, '--depth', str(self.shallow_depth))
                    else:
                        # Fetch with limited depth but ensure we get all tags
                        repo.git.fetch('--depth', str(self.shallow_depth))
                        # Separately fetch all tags (lightweight, just refs)
                        repo.git.fetch('--tags', '--force')
                else:
                    # Full fetch for non-shallow repos
                    repo.git.fetch('--all', '--tags')
                
                self._last_fetch[repo_url] = datetime.now()
                
                # If specific branch requested, checkout
                if branch:
                    try:
                        repo.git.checkout(branch)
                        if use_shallow:
                            # For shallow repos, use fetch instead of pull to maintain shallow depth
                            repo.git.reset('--hard', f'origin/{branch}')
                        else:
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
        clone_type = "shallow" if use_shallow else "full"
        logger.info(f"Cloning repository to cache ({clone_type}): {repo_url}")
        try:
            clone_args = {
                'url': repo_url,
                'to_path': repo_path,
                'branch': branch
            }
            
            if use_shallow:
                # Shallow clone with minimal history
                clone_args['depth'] = self.shallow_depth
                if branch:
                    clone_args['single_branch'] = True  # Only clone specified branch if requested
                logger.info(f"Using shallow clone with depth {self.shallow_depth} for {repo_url}")
            else:
                # Full clone for smaller repos
                clone_args['no_single_branch'] = True  # Clone all branches
            
            repo = git.Repo.clone_from(**clone_args)
            
            # After cloning, ensure we have all tags
            try:
                repo.git.fetch('--tags', '--force')
                logger.info(f"Fetched all tags for {repo_url}")
            except Exception as e:
                logger.warning(f"Failed to fetch tags after clone: {e}")
            
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
                # Fetch all tags, not just shallow
                repo.git.fetch('--tags', '--force')
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
    
    def optimize_repo(self, repo_url: str) -> int:
        """Optimize a cached repository using git gc and prune"""
        repo_path = self.get_cached_repo_path(repo_url)
        
        if not repo_path.exists():
            logger.warning(f"Repository not in cache: {repo_url}")
            return 0
        
        try:
            repo = git.Repo(repo_path)
            size_before = self._get_repo_size(repo_path)
            
            # Run git garbage collection
            logger.info(f"Running git gc on {repo_url}")
            repo.git.gc('--aggressive', '--prune=now')
            
            # Prune unreachable objects
            repo.git.prune()
            
            # Remove reflogs older than 1 day
            repo.git.reflog('expire', '--expire=1.day.ago', '--all')
            
            size_after = self._get_repo_size(repo_path)
            saved = size_before - size_after
            
            logger.info(f"Optimized {repo_url}: saved {saved / (1024*1024):.2f} MB")
            return saved
            
        except Exception as e:
            logger.error(f"Failed to optimize {repo_url}: {e}")
            return 0
    
    def _get_repo_size(self, repo_path: Path) -> int:
        """Get size of a repository in bytes"""
        total_size = 0
        for dirpath, _, filenames in os.walk(repo_path):
            for filename in filenames:
                filepath = os.path.join(dirpath, filename)
                total_size += os.path.getsize(filepath)
        return total_size
    
    def cleanup_old_repos(self, max_age_days: int = 30) -> int:
        """Remove cached repositories not accessed in max_age_days"""
        if not self.cache_path.exists():
            return 0
        
        current_time = time.time()
        max_age_seconds = max_age_days * 24 * 60 * 60
        total_removed = 0
        
        for repo_dir in self.cache_path.iterdir():
            if not repo_dir.is_dir():
                continue
                
            # Check last access time
            last_access = os.path.getatime(repo_dir)
            age_seconds = current_time - last_access
            
            if age_seconds > max_age_seconds:
                try:
                    size = self._get_repo_size(repo_dir)
                    shutil.rmtree(repo_dir)
                    total_removed += size
                    logger.info(f"Removed old cached repo: {repo_dir.name} (freed {size/(1024*1024):.2f} MB)")
                except Exception as e:
                    logger.error(f"Failed to remove {repo_dir}: {e}")
        
        if total_removed > 0:
            logger.info(f"Total space freed: {total_removed/(1024*1024):.2f} MB")
        
        return total_removed
    
    def convert_to_shallow(self, repo_url: str, depth: int = 1) -> bool:
        """Convert an existing full clone to shallow clone"""
        repo_path = self.get_cached_repo_path(repo_url)
        
        if not repo_path.exists():
            logger.warning(f"Repository not in cache: {repo_url}")
            return False
        
        try:
            repo = git.Repo(repo_path)
            current_branch = repo.active_branch.name
            
            size_before = self._get_repo_size(repo_path)
            
            # Re-clone as shallow
            logger.info(f"Converting {repo_url} to shallow clone with depth {depth}")
            
            # Save the remote URL
            remote_url = repo.remotes.origin.url
            
            # Remove the old repo
            shutil.rmtree(repo_path)
            
            # Clone as shallow
            git.Repo.clone_from(
                remote_url,
                repo_path,
                branch=current_branch,
                depth=depth,
                single_branch=True
            )
            
            size_after = self._get_repo_size(repo_path)
            saved = size_before - size_after
            
            logger.info(f"Converted to shallow clone: saved {saved/(1024*1024):.2f} MB")
            return True
            
        except Exception as e:
            logger.error(f"Failed to convert to shallow: {e}")
            return False
    
    def get_repository_stats(self) -> Dict:
        """Get detailed statistics about cached repositories"""
        stats = {
            'total_size': 0,
            'repo_count': 0,
            'repos': [],
            'largest_repos': [],
            'optimization_potential': 0
        }
        
        if not self.cache_path.exists():
            return stats
        
        repo_sizes = []
        
        for repo_dir in self.cache_path.iterdir():
            if not repo_dir.is_dir() or not (repo_dir / '.git').exists():
                continue
                
            try:
                repo = git.Repo(repo_dir)
                origin_url = repo.remotes.origin.url if repo.remotes else 'Unknown'
                repo_size = self._get_repo_size(repo_dir)
                
                # Check if it's a shallow clone
                is_shallow = repo.git.rev_parse('--is-shallow-repository') == 'true'
                
                repo_info = {
                    'name': repo_dir.name,
                    'url': origin_url,
                    'size': repo_size,
                    'size_mb': repo_size / (1024 * 1024),
                    'is_shallow': is_shallow,
                    'last_accessed': datetime.fromtimestamp(os.path.getatime(repo_dir))
                }
                
                stats['repos'].append(repo_info)
                repo_sizes.append((repo_info['size_mb'], repo_info))
                stats['total_size'] += repo_size
                
                # Estimate optimization potential for non-shallow large repos
                if not is_shallow and repo_size > 100 * 1024 * 1024:  # > 100MB
                    # Shallow clones can save 80-90% of space for large repos
                    stats['optimization_potential'] += int(repo_size * 0.85)
                    
            except Exception as e:
                logger.error(f"Failed to get stats for {repo_dir}: {e}")
        
        stats['repo_count'] = len(stats['repos'])
        stats['total_size_mb'] = stats['total_size'] / (1024 * 1024)
        stats['optimization_potential_mb'] = stats['optimization_potential'] / (1024 * 1024)
        
        # Get top 5 largest repos
        repo_sizes.sort(reverse=True)
        stats['largest_repos'] = [info for _, info in repo_sizes[:5]]
        
        return stats