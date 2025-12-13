"""
Version management and update functionality for KNX to OpenHAB Generator.
Uses Git commits for versioning instead of version.json.
"""
import os
import subprocess
import requests
from typing import Dict, Optional, Tuple
from datetime import datetime


class Updater:
    """Handles version checking and updates from GitHub using Git commits."""
    
    def __init__(self, base_path: str = None):
        """
        Initialize the updater.
        
        Args:
            base_path: Base directory of the installation (defaults to current working directory)
        """
        self.base_path = base_path or os.getcwd()
        self.repo_url = 'https://github.com/diddip21/knx_to_openhab'
        self.branch = 'main'
        
    def _run_git_command(self, args: list) -> Tuple[bool, str]:
        """
        Run a git command and return the result.
        
        Args:
            args: List of git command arguments
            
        Returns:
            Tuple of (success, output)
        """
        try:
            result = subprocess.run(
                ['git'] + args,
                cwd=self.base_path,
                capture_output=True,
                text=True,
                timeout=10
            )
            return result.returncode == 0, result.stdout.strip()
        except Exception as e:
            return False, str(e)
    
    def get_current_version(self) -> Dict:
        """
        Get the current version information from local git repository.
        
        Returns:
            Dictionary with version info (commit_hash, commit_date, branch, repository)
        """
        try:
            # Get current commit hash
            success, commit_hash = self._run_git_command(['rev-parse', 'HEAD'])
            if not success:
                return {
                    'commit_hash': 'unknown',
                    'commit_short': 'unknown',
                    'commit_date': 'unknown',
                    'commit_message': 'Git repository not found',
                    'branch': self.branch,
                    'repository': self.repo_url,
                    'error': 'Not a git repository or git not available'
                }
            
            # Get commit date
            success, commit_date = self._run_git_command([
                'show', '-s', '--format=%ci', 'HEAD'
            ])
            
            # Get commit message (first line)
            success, commit_message = self._run_git_command([
                'show', '-s', '--format=%s', 'HEAD'
            ])
            
            # Get current branch
            success, current_branch = self._run_git_command([
                'rev-parse', '--abbrev-ref', 'HEAD'
            ])
            
            return {
                'commit_hash': commit_hash,
                'commit_short': commit_hash[:7] if commit_hash != 'unknown' else 'unknown',
                'commit_date': commit_date if commit_date else 'unknown',
                'commit_message': commit_message if commit_message else 'No message',
                'branch': current_branch if current_branch else self.branch,
                'repository': self.repo_url
            }
        except Exception as e:
            return {
                'commit_hash': 'unknown',
                'commit_short': 'unknown',
                'commit_date': 'unknown',
                'commit_message': 'Error',
                'branch': self.branch,
                'repository': self.repo_url,
                'error': str(e)
            }
    
    def check_github_version(self) -> Tuple[bool, Optional[Dict]]:
        """
        Check GitHub for the latest commit on the main branch.
        
        Returns:
            Tuple of (success, commit_info_dict or None)
        """
        try:
            # Extract owner and repo from URL
            # e.g., https://github.com/diddip21/knx_to_openhab -> diddip21/knx_to_openhab
            parts = self.repo_url.rstrip('/').split('/')
            owner = parts[-2]
            repo = parts[-1].replace('.git', '')
            
            # Get latest commit from GitHub API
            api_url = f"https://api.github.com/repos/{owner}/{repo}/commits/{self.branch}"
            response = requests.get(api_url, timeout=10)
            
            if response.status_code != 200:
                return False, {'error': f'GitHub API returned status {response.status_code}'}
            
            commit_data = response.json()
            
            return True, {
                'commit_hash': commit_data['sha'],
                'commit_short': commit_data['sha'][:7],
                'commit_date': commit_data['commit']['committer']['date'],
                'commit_message': commit_data['commit']['message'].split('\n')[0],  # First line only
                'author': commit_data['commit']['author']['name'],
                'repository': self.repo_url,
                'branch': self.branch
            }
            
        except requests.RequestException as e:
            return False, {'error': f'Network error: {str(e)}'}
        except Exception as e:
            return False, {'error': f'Unexpected error: {str(e)}'}
    
    def check_for_updates(self) -> Dict:
        """
        Check if updates are available by comparing local and remote commits.
        
        Returns:
            Dictionary with update status and information
        """
        current = self.get_current_version()
        success, remote = self.check_github_version()
        
        if not success:
            return {
                'update_available': False,
                'current_commit': current.get('commit_short', 'unknown'),
                'current_date': current.get('commit_date', 'unknown'),
                'error': remote.get('error', 'Failed to check for updates')
            }
        
        # Compare commit hashes
        current_commit = current.get('commit_hash', '')
        remote_commit = remote.get('commit_hash', '')
        
        update_available = current_commit != remote_commit and current_commit != 'unknown'
        
        return {
            'update_available': update_available,
            'current_commit': current.get('commit_short', 'unknown'),
            'current_commit_full': current_commit,
            'current_date': current.get('commit_date', 'unknown'),
            'current_message': current.get('commit_message', ''),
            'latest_commit': remote.get('commit_short', 'unknown'),
            'latest_commit_full': remote_commit,
            'latest_date': remote.get('commit_date', 'unknown'),
            'latest_message': remote.get('commit_message', ''),
            'latest_author': remote.get('author', 'unknown'),
            'repository': self.repo_url,
            'branch': self.branch
        }
    
    def trigger_update(self) -> Tuple[bool, str]:
        """
        Trigger the update process by executing update.sh script.
        
        Returns:
            Tuple of (success, message)
        """
        try:
            update_script = os.path.join(self.base_path, 'update.sh')
            
            if not os.path.exists(update_script):
                return False, f"Update script not found at {update_script}"
            
            # Make script executable (optional, since we run with bash explicitly)
            try:
                os.chmod(update_script, 0o755)
            except OSError:
                # Ignore permission errors (e.g. if file is owned by root but we are knxohui)
                # We can still execute it via bash if we have read permissions
                pass

            
            # Execute update script in background
            # The script will handle git pull, dependency updates, and service restart
            # Ensure we are using the correct user if possible, though the service should already be running as knxohui
            subprocess.Popen(
                ['/bin/bash', update_script],
                cwd=self.base_path,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                start_new_session=True
            )
            
            return True, "Update process started. The service will restart automatically."
            
        except Exception as e:
            return False, f"Failed to start update: {str(e)}"
