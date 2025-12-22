import os
import sys
import json
import uuid
import tarfile
import shutil
import threading
import queue
import subprocess
import traceback
import io
from concurrent.futures import ThreadPoolExecutor
from .storage import save_job, load_jobs, save_jobs, ensure_dirs


class JobManager:
    def __init__(self, cfg):
        self.cfg = cfg
        # Use the configured backup directory from config, with a sensible default
        jobs_dir_config = cfg.get('jobs_dir', 'var/lib/knx_to_openhab')
        backups_dir_config = cfg.get('backups_dir', 'var/backups/knx_to_openhab')
        
        # If paths are relative, make them relative to project root
        project_root = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
        if not os.path.isabs(jobs_dir_config):
            self.jobs_dir = os.path.join(project_root, jobs_dir_config)
        else:
            self.jobs_dir = jobs_dir_config
            
        if not os.path.isabs(backups_dir_config):
            self.backups_dir = os.path.join(project_root, backups_dir_config)
        else:
            self.backups_dir = backups_dir_config

        ensure_dirs([self.jobs_dir, self.backups_dir])
        self._jobs = load_jobs(self.jobs_dir)
        self.queues = {}
        self.executor = ThreadPoolExecutor(max_workers=2)
        self.lock = threading.Lock()

    def list_jobs(self):
        return list(self._jobs.values())

    def get_job(self, job_id):
        return self._jobs.get(job_id)

    def get_queue(self, job_id):
        # Ensure job exists before returning queue
        if job_id not in self._jobs:
            return None
        return self.queues.get(job_id)

    def create_job(self, input_path, original_name=None, password=None):
        job_id = uuid.uuid4().hex
        job = {
            'id': job_id,
            'input': input_path,
            'name': original_name or os.path.basename(input_path),
            'status': 'queued',
            'created': int(__import__('time').time()),
            'backups': [],
            'log': [],
            'stats': {},
            'password': password
        }
        q = queue.Queue()
        with self.lock:
            self._jobs[job_id] = job
            self.queues[job_id] = q  # Register queue before saving jobs
            save_jobs(self.jobs_dir, self._jobs)
        self.executor.submit(self._run_job, job_id)
        return job

    def _run_job(self, job_id):
        job = self._jobs[job_id]
        q = self.queues[job_id]
        job['status'] = 'running'
        save_jobs(self.jobs_dir, self._jobs)

        # create backup of current openhab folder
        openhab_path = self.cfg.get('openhab_path', 'openhab')
        ts = __import__('time').strftime('%Y%m%d-%H%M%S')
        backup_name = f"{job_id}-{ts}.tar.gz"
        backup_path = os.path.join(self.backups_dir, backup_name)
        try:
            if os.path.exists(openhab_path):
                with tarfile.open(backup_path, 'w:gz') as tar:
                    tar.add(openhab_path, arcname=os.path.basename(openhab_path))
                job['backups'].append({'name': backup_name, 'path': backup_path, 'ts': ts})
                save_jobs(self.jobs_dir, self._jobs)
                q.put({'type': 'backup', 'level': 'info', 'message': f'backup created: {backup_name}'})
                # enforce retention immediately after creating backup
                try:
                    self.enforce_retention()
                    q.put({'type': 'info', 'level': 'debug', 'message': 'retention enforced'})
                except Exception as re:
                    q.put({'type': 'error', 'level': 'warning', 'message': f'retention error: {re}'})
        except Exception as e:
            q.put({'type': 'error', 'level': 'error', 'message': f'backup failed: {e}'})

        # Process logic
        try:
            q.put({'type': 'info', 'level': 'info', 'message': 'start in-process generation'})
            import importlib
            import copy
            knxmod = importlib.import_module('knxproject_to_openhab')
            etsmod = importlib.import_module('ets_to_openhab')
            importlib.reload(etsmod) # Ensure we use the latest code
            
            # Setup Staging
            staging_dir = os.path.join(self.jobs_dir, job_id, 'staging')
            ensure_dirs([staging_dir])
            
            # Load main config to base our staged config on
            project_root = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
            if project_root not in sys.path:
                sys.path.insert(0, project_root)
            import config as global_config_module
            importlib.reload(global_config_module) # Reload to get fresh config
            
            # Create a copy of the config dict to modify
            staged_config = copy.copy(global_config_module.config)
            
            # Define output keys to override
            output_keys = ['items_path', 'things_path', 'sitemaps_path', 'influx_path', 'fenster_path']
            stage_mapping = {} # staged_path -> real_absolute_path
            
            q.put({'type': 'info', 'level': 'info', 'message': f'Staging directory: {staging_dir}'})

            for key in output_keys:
                real_path = staged_config.get(key)
                if real_path:
                    # Determine target subpath structure
                    if os.path.isabs(real_path):
                        # Try to find a common root with openhab_path if possible, or just use basename
                        # Heuristic: if path contains 'openhab', take suffix
                        norm_real = real_path.replace('\\', '/')
                        if 'openhab/' in norm_real:
                             subpath = norm_real.split('openhab/', 1)[1]
                             staged_path = os.path.join(staging_dir, 'openhab', subpath)
                        else:
                             # Just use basename inside key-named folder to avoid collisions
                             staged_path = os.path.join(staging_dir, key, os.path.basename(real_path))
                    else:
                        staged_path = os.path.join(staging_dir, real_path)
                    
                    # Ensure dir exists
                    os.makedirs(os.path.dirname(staged_path), exist_ok=True)
                    staged_config[key] = staged_path
                    stage_mapping[staged_path] = real_path

            # Capture stdout/stderr for ENTIRE generation process
            old_stdout = sys.stdout
            old_stderr = sys.stderr
            captured_output = io.StringIO()
            sys.stdout = captured_output
            sys.stderr = captured_output
            
            try:
                # load project (json dump or parse knxproj)
                if job['input'].lower().endswith('.json'):
                    with open(job['input'], 'r', encoding='utf8') as f:
                        project = json.load(f)
                    # Temporarily restore stdout to log message
                    sys.stdout = old_stdout
                    q.put({'type': 'info', 'level': 'info', 'message': 'read project JSON dump'})
                    sys.stdout = captured_output
                else:
                    # try to parse knxproj archive using XKNXProj
                    from xknxproject.xknxproj import XKNXProj
                    sys.stdout = old_stdout
                    q.put({'type': 'info', 'level': 'info', 'message': 'parsing knxproj archive (this may take a while)'})
                    sys.stdout = captured_output
                    pwd = job.get('password')
                    knxproj = XKNXProj(path=job['input'], password=pwd, language='de-DE')
                    project = knxproj.parse()
                    sys.stdout = old_stdout
                    q.put({'type': 'info', 'level': 'info', 'message': 'parsed knxproj'})
                    sys.stdout = captured_output

                # run the same sequence as the CLI main()
                building = knxmod.create_building(project)
                addresses = knxmod.get_addresses(project)
                sys.stdout = old_stdout
                q.put({'type': 'info', 'level': 'info', 'message': f'{len(addresses)} addresses extracted'})
                sys.stdout = captured_output
                
                house = knxmod.put_addresses_in_building(building, addresses, project)
                prj_name = house[0].get('name_long') if house else None
                ip = knxmod.get_gateway_ip(project)
                homekit_enabled = knxmod.is_homekit_enabled(project)
                alexa_enabled = knxmod.is_alexa_enabled(project)

                etsmod.floors = house[0]["floors"] if house else []
                etsmod.all_addresses = addresses
                etsmod.GWIP = ip
                etsmod.B_HOMEKIT = homekit_enabled
                etsmod.B_ALEXA = alexa_enabled
                if prj_name:
                    etsmod.PRJ_NAME = prj_name

                sys.stdout = old_stdout
                q.put({'type': 'info', 'level': 'info', 'message': 'generating files (staged)...'})
                sys.stdout = captured_output
                
                # ets_to_openhab.main() writes output files to STAGING via injected config
                etsmod.main(configuration=staged_config)
                
            finally:
                sys.stdout = old_stdout
                sys.stderr = old_stderr
                
                # Send captured output line by line to the queue
                captured = captured_output.getvalue()
                if captured:
                    for line in captured.strip().split('\n'):
                        if line.strip():
                            level = 'info'
                            message = line.strip()
                            if message.startswith('WARNING:'):
                                level = 'warning'
                                message = message[len('WARNING:'):].strip()
                            elif message.startswith('ERROR:'):
                                level = 'error'
                                message = message[len('ERROR:'):].strip()
                            elif 'WARNING:' in message and ':' in message:
                                level = 'warning'
                                parts = message.split(':')
                                if len(parts) > 2:
                                    message = ':'.join(parts[2:]).strip()
                            q.put({'type': 'info', 'level': level, 'message': message})

            # Save staging info to job
            job['staging_dir'] = staging_dir
            job['stage_mapping'] = stage_mapping
            job['staged'] = True
            
            # Compute statistics by comparing STAGED vs LIVE/BACKUP
            try:
                detailed_stats = self._compute_staged_stats(stage_mapping, openhab_path)
                job['stats'] = detailed_stats
                
                for fn, stat in sorted(job['stats'].items()):
                    before = int(stat.get('before', 0))
                    after = int(stat.get('after', 0))
                    delta = int(stat.get('delta', after - before))
                    added = int(stat.get('added', 0))
                    removed = int(stat.get('removed', 0))
                    msg = f"{fn}: {before} -> {after} lines ({delta:+d}) [+{added}/-{removed}]"
                    q.put({'type': 'stats', 'level': 'info', 'message': msg})

            except Exception as stats_error:
                q.put({'type': 'error', 'level': 'error', 'message': f'Stats error: {str(stats_error)}'})
                # fallback empty stats
                job['stats'] = {}

            job['status'] = 'completed'
            q.put({'type': 'status', 'level': 'info', 'message': 'completed (staged) - ready to deploy'})
        except Exception as e:
            job['status'] = 'failed'
            err_msg = str(e)
            tb = traceback.format_exc()
            q.put({'type': 'error', 'level': 'error', 'message': err_msg})
            q.put({'type': 'error', 'level': 'error', 'message': tb})
            job['log'].append(f"ERROR: {err_msg}")
            job['log'].append(tb)
        finally:
            save_jobs(self.jobs_dir, self._jobs)
            q.put(None)

    def _compute_detailed_stats(self, openhab_path, backup_path):
        """Compute detailed diff stats (added, removed) by comparing current files with backup."""
        import difflib
        import logging
        logger = logging.getLogger(__name__)
        stats = {}

        # Comprehensive file type detection for OpenHAB files
        supported_extensions = {
            '.items', '.things', '.sitemap', '.rules', '.persist',
            '.script', '.transform', '.db', '.cfg', '.properties'
        }

        # Get list of current files
        current_files = {}
        if os.path.exists(openhab_path):
            for root, dirs, files in os.walk(openhab_path):
                for fname in files:
                    # Check if file has supported extension or is in known OpenHAB directories
                    if (any(fname.endswith(ext) for ext in supported_extensions) or
                        any(root.endswith(dir_name) for dir_name in ['items', 'things', 'sitemaps', 'rules', 'persistence', 'scripts', 'transform'])):
                        fpath = os.path.join(root, fname)
                        try:
                            with open(fpath, 'r', encoding='utf8', errors='ignore') as f:
                                lines = f.readlines()
                                # Store with relative path for proper comparison
                                rel_path = os.path.relpath(fpath, openhab_path).replace('\\', '/')
                                current_files[rel_path] = lines
                        except Exception as e:
                            logger.warning(f"Could not read current file {fpath}: {e}")
                            continue

        # Get list of original files from backup
        original_files = {}
        if os.path.exists(backup_path):
            try:
                with tarfile.open(backup_path, 'r:gz') as tar:
                    for member in tar.getmembers():
                        if member.isfile():
                            member_name_normalized = member.name.replace('\\', '/')

                            # Extract relative path more robustly
                            relpath = self._extract_relative_path_from_backup(member_name_normalized)

                            if relpath and self._is_supported_openhab_file(relpath):
                                try:
                                    f = tar.extractfile(member)
                                    if f:
                                        wrapper = io.TextIOWrapper(f, encoding='utf-8', errors='ignore')
                                        lines = wrapper.readlines()
                                        original_files[relpath] = lines
                                except Exception as e:
                                    logger.warning(f"Could not extract file from backup {member.name}: {e}")
                                    continue
            except Exception as e:
                logger.error(f"Error reading backup for stats: {e}")
                # Even if backup reading fails, try to generate stats for current files
                # This handles the case where backup is corrupted or doesn't exist
                pass

        # No need to normalize current files since we already stored them with relative paths
        normalized_current_files = current_files

        # If no backup exists, stats will show all current files as "added"
        all_files = set(normalized_current_files.keys()) | set(original_files.keys())
        for fname in sorted(all_files):
            orig_lines = original_files.get(fname, [])
            curr_lines = normalized_current_files.get(fname, [])

            matcher = difflib.SequenceMatcher(None, orig_lines, curr_lines)
            added = 0
            removed = 0
            for tag, i1, i2, j1, j2 in matcher.get_opcodes():
                if tag == 'replace':
                    removed += i2 - i1
                    added += j2 - j1
                elif tag == 'delete':
                    removed += i2 - i1
                elif tag == 'insert':
                    added += j2 - j1

            stats[fname] = {
                'before': len(orig_lines),
                'after': len(curr_lines),
                'delta': len(curr_lines) - len(orig_lines),
                'added': added,
                'removed': removed
            }

        # If no files were found, make sure to generate stats for the main expected files
        if not stats:
            # Look for common OpenHAB files in the openhab directory
            expected_files = ['items/knx.items', 'things/knx.things', 'sitemaps/knx.sitemap',
                             'persistence/influxdb.persist', 'rules/fenster.rules']
            for expected_file in expected_files:
                full_path = os.path.join(openhab_path, expected_file)
                if os.path.exists(full_path):
                    try:
                        with open(full_path, 'r', encoding='utf-8', errors='ignore') as f:
                            lines = len(f.readlines())
                        stats[expected_file] = {
                            'before': 0,  # No backup existed before
                            'after': lines,
                            'delta': lines,
                            'added': lines,
                            'removed': 0
                        }
                    except Exception as e:
                        logger.warning(f"Could not read expected file {full_path}: {e}")

        return stats

    def _compute_staged_stats(self, stage_mapping, openhab_path):
        """Compute stats by comparing staged files with live files."""
        stats = {}
        import difflib

        for staged_path, real_path in stage_mapping.items():
            # Read staged content (New)
            curr_lines = []
            if os.path.exists(staged_path):
                try:
                    with open(staged_path, 'r', encoding='utf-8', errors='ignore') as f:
                        curr_lines = f.readlines()
                except Exception as e:
                    logger.warning(f"Could not read staged file {staged_path}: {e}")
                    continue

            # Read live content (Old)
            orig_lines = []
            # Calculate absolute real path
            # If real_path is relative, it is relative to project root or openhab_path?
            # In stage_mapping construction, we stored what was in config.
            # If config has "openhab/items/knx.items", that's relative to project root.
            # But earlier code used openhab_path from config.
            
            # We need to resolve real_path accurately.
            # In _run_job, we assumed:
            # if os.path.isabs(real_path): use it
            # else: os.path.join(staging_dir, real_path) (this was for Staged Path construction)
            
            # For reading the LIVE file:
            abs_real_path = real_path

            
            # If config says "openhab/items/knx.items", we should check if that exists relative to CWD?
            # jobs.py CWD is usually project root (or wherever app.py launched from).
            
            if not os.path.isabs(abs_real_path):
                 abs_real_path = os.path.abspath(abs_real_path)

            if os.path.exists(abs_real_path):
                try:
                    with open(abs_real_path, 'r', encoding='utf-8', errors='ignore') as f:
                        orig_lines = f.readlines()
                except Exception as e:
                    logger.warning(f"Could not read live file {abs_real_path}: {e}")
            
            # Compute Diff
            matcher = difflib.SequenceMatcher(None, orig_lines, curr_lines)
            added = 0
            removed = 0
            for tag, i1, i2, j1, j2 in matcher.get_opcodes():
                if tag == 'replace':
                    removed += i2 - i1
                    added += j2 - j1
                elif tag == 'delete':
                    removed += i2 - i1
                elif tag == 'insert':
                    added += j2 - j1

            # Relative path for display (key in stats dict)
            # Try to make it relative to openhab_path if possible, else basename
            if os.path.isabs(real_path):
                 # Try to make relative to openhab_path
                 if openhab_path and real_path.startswith(openhab_path):
                      rel_display = os.path.relpath(real_path, openhab_path).replace('\\', '/')
                 else:
                      rel_display = os.path.basename(real_path)
            else:
                 rel_display = real_path.replace('\\', '/')

            stats[rel_display] = {
                'before': len(orig_lines),
                'after': len(curr_lines),
                'delta': len(curr_lines) - len(orig_lines),
                'added': added,
                'removed': removed,
                'staged_path': staged_path, # Keep track for other uses
                'real_path': abs_real_path
            }
            
        return stats

    def _extract_relative_path_from_backup(self, member_name):
        """Extract relative path from backup member name, handling various archive structures."""
        # Handle different possible archive structures:
        # 1. "openhab/items/knx.items"
        # 2. "items/knx.items" 
        # 3. "knx.items"
        
        parts = member_name.split('/')
        
        # Find the index of 'openhab' if present
        openhab_idx = -1
        for i, part in enumerate(parts):
            if part == 'openhab':
                openhab_idx = i
                break
        
        if openhab_idx >= 0 and len(parts) > openhab_idx + 1:
            # Structure: path/to/openhab/relative/file
            relpath = '/'.join(parts[openhab_idx + 1:])
        elif len(parts) >= 2 and parts[0] in ['items', 'things', 'sitemaps', 'rules', 'persistence', 'scripts', 'transform']:
            # Structure: items/knx.items
            relpath = '/'.join(parts)
        else:
            # Structure: knx.items or unknown
            relpath = parts[-1] if parts else member_name
            
        return relpath

    def _is_supported_openhab_file(self, relpath):
        """Check if a file path represents a supported OpenHAB configuration file."""
        supported_extensions = {
            '.items', '.things', '.sitemap', '.rules', '.persist', 
            '.script', '.transform', '.db', '.cfg', '.properties'
        }
        
        # Check file extension
        if any(relpath.endswith(ext) for ext in supported_extensions):
            return True
            
        # Check if it's in a known OpenHAB directory
        path_parts = relpath.split('/')
        if len(path_parts) >= 2:
            dirname = path_parts[0]
            known_dirs = ['items', 'things', 'sitemaps', 'rules', 'persistence', 'scripts', 'transform']
            if dirname in known_dirs:
                return True
                
        return False

    def _normalize_current_files(self, current_files, openhab_path):
        """Normalize current file paths to match backup format."""
        normalized = {}
        
        for filename, lines in current_files.items():
            # Find the full path of this file
            for root, dirs, files in os.walk(openhab_path):
                if filename in files:
                    fpath = os.path.join(root, filename)
                    relpath = os.path.relpath(fpath, openhab_path).replace('\\', '/')
                    normalized[relpath] = lines
                    break
                    
        return normalized

    def _generate_basic_stats(self, openhab_path):
        """Generate basic statistics for generated files when detailed stats fail."""
        import importlib.util
        # Load the main config to get the actual paths
        main_config_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), 'config.json')
        if os.path.exists(main_config_path):
            with open(main_config_path, 'r', encoding='utf-8') as f:
                main_config = json.load(f)
        else:
            # Fallback to default paths if config can't be loaded
            main_config = {
                'items_path': 'openhab/items/knx.items',
                'things_path': 'openhab/things/knx.things',
                'sitemaps_path': 'openhab/sitemaps/knx.sitemap',
                'influx_path': 'openhab/persistence/influxdb.persist',
                'fenster_path': 'openhab/rules/fenster.rules'
            }

        basic_stats = {}

        # Check for expected generated files using actual configured paths
        expected_paths = [
            main_config.get('items_path', 'openhab/items/knx.items'),
            main_config.get('things_path', 'openhab/things/knx.things'),
            main_config.get('sitemaps_path', 'openhab/sitemaps/knx.sitemap'),
            main_config.get('influx_path', 'openhab/persistence/influxdb.persist'),
            main_config.get('fenster_path', 'openhab/rules/fenster.rules')
        ]

        for config_path in expected_paths:
            # Convert relative path to absolute path based on openhab_path
            if os.path.isabs(config_path):
                full_path = config_path
            else:
                full_path = os.path.join(self.cfg.get('openhab_path', 'openhab'), config_path)
                # If the config path already includes the openhab directory, use it as is
                if not os.path.exists(full_path):
                    full_path = config_path

            # If still doesn't exist, try with openhab_path as base
            if not os.path.exists(full_path):
                openhab_base = self.cfg.get('openhab_path', 'openhab')
                full_path = os.path.join(openhab_base, config_path)

            if os.path.exists(full_path):
                try:
                    with open(full_path, 'r', encoding='utf-8', errors='ignore') as f:
                        lines = len(f.readlines())
                    filename = os.path.basename(full_path)
                    basic_stats[filename] = {
                        'before': 0,  # No backup existed before
                        'after': lines,
                        'delta': lines,
                        'added': lines,
                        'removed': 0
                    }
                except Exception as e:
                    print(f'Could not read {full_path}: {str(e)}')  # Use print instead of q.put since this is outside job context

        # If still no files found, scan the entire openhab directory for any generated files
        if not basic_stats:
            openhab_path = self.cfg.get('openhab_path', 'openhab')
            if os.path.exists(openhab_path):
                for root, dirs, files in os.walk(openhab_path):
                    for file in files:
                        if file.endswith(('.items', '.things', '.sitemap', '.rules', '.persist', '.script', '.transform')):
                            full_path = os.path.join(root, file)
                            try:
                                with open(full_path, 'r', encoding='utf-8', errors='ignore') as f:
                                    lines = len(f.readlines())
                                # Create relative path for display
                                rel_path = os.path.relpath(full_path, openhab_path)
                                basic_stats[rel_path] = {
                                    'before': 0,  # No backup existed before
                                    'after': lines,
                                    'delta': lines,
                                    'added': lines,
                                    'removed': 0
                                }
                            except Exception as e:
                                print(f'Could not read generated file {full_path}: {str(e)}')  # Use print instead of q.put since this is outside job context

        return basic_stats

    def get_file_diff(self, job_id, rel_path):
        """Get diff for a specific file in a job."""
        job = self._jobs.get(job_id)
        if not job:
            return None
        
        openhab_path = self.cfg.get('openhab_path', 'openhab')
        # Use the latest backup for comparison
        if not job.get('backups'):
            return None
        backup_path = job['backups'][-1]['path']
        
        # Read current file
        curr_lines = []
        fpath = os.path.join(openhab_path, rel_path)
        if os.path.exists(fpath):
            try:
                with open(fpath, 'r', encoding='utf8', errors='ignore') as f:
                    curr_lines = f.readlines()
            except Exception:
                pass

        # Read original file from backup
        orig_lines = []
        if os.path.exists(backup_path):
            try:
                with tarfile.open(backup_path, 'r:gz') as tar:
                    # backup structure is openhab/...
                    # rel_path is like "items/knx.items"
                    # member name should be "openhab/items/knx.items"
                    member_path = f"openhab/{rel_path}".replace('\\', '/')
                    try:
                        member = tar.getmember(member_path)
                        f = tar.extractfile(member)
                        if f:
                            wrapper = io.TextIOWrapper(f, encoding='utf-8', errors='ignore')
                            orig_lines = wrapper.readlines()
                    except KeyError:
                        pass
            except Exception:
                pass

        import difflib
        diff_lines = []
        matcher = difflib.SequenceMatcher(None, orig_lines, curr_lines)
        for tag, i1, i2, j1, j2 in matcher.get_opcodes():
            if tag == 'equal':
                for i in range(i1, i2):
                    diff_lines.append({'type': 'unchanged', 'line': orig_lines[i].rstrip('\n'), 'orig_ln': i+1, 'curr_ln': j1 + (i-i1) + 1})
            elif tag == 'replace':
                for i in range(i1, i2):
                    diff_lines.append({'type': 'removed', 'line': orig_lines[i].rstrip('\n'), 'orig_ln': i+1})
                for j in range(j1, j2):
                    diff_lines.append({'type': 'added', 'line': curr_lines[j].rstrip('\n'), 'curr_ln': j+1})
            elif tag == 'delete':
                for i in range(i1, i2):
                    diff_lines.append({'type': 'removed', 'line': orig_lines[i].rstrip('\n'), 'orig_ln': i+1})
            elif tag == 'insert':
                for j in range(j1, j2):
                    diff_lines.append({'type': 'added', 'line': curr_lines[j].rstrip('\n'), 'curr_ln': j+1})
        
        return diff_lines

    def rollback(self, job_id, backup_name=None):
        job = self._jobs.get(job_id)
        if not job:
            raise ValueError('job not found')
        if not job.get('backups'):
            raise ValueError('no backups available')
        if backup_name is None:
            backup = job['backups'][-1]
        else:
            backup = next((b for b in job['backups'] if b['name'] == backup_name), None)
        if not backup:
            raise ValueError('backup not found')
        # extract backup into temp and move to openhab_path
        tmp = os.path.join(self.backups_dir, f"tmp-restore-{uuid.uuid4().hex}")
        os.makedirs(tmp, exist_ok=True)
        try:
            with tarfile.open(backup['path'], 'r:gz') as tar:
                tar.extractall(path=tmp)
            extracted = os.path.join(tmp, os.listdir(tmp)[0])
            dst = self.cfg.get('openhab_path', 'openhab')
            if os.path.exists(dst):
                shutil.rmtree(dst)
            shutil.move(extracted, dst)
            return True, f'restored {backup["name"]}'
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def deploy(self, job_id):
        """Deploy staged files to live environment."""
        job = self._jobs.get(job_id)
        if not job:
            raise ValueError('Job not found')
        
        if not job.get('staged'):
            raise ValueError('Job is not staged or already deployed')

        mapping = job.get('stage_mapping', {})
        if not mapping:
             raise ValueError('No staged files found')
             
        # Create a safety backup before deploying?
        # Ideally yes, but maybe user wants quick deploy. 
        # Making a backup is safer.
        openhab_path = self.cfg.get('openhab_path', 'openhab')
        ts = __import__('time').strftime('%Y%m%d-%H%M%S')
        backup_name = f"pre-deploy-{job_id}-{ts}.tar.gz"
        backup_path = os.path.join(self.backups_dir, backup_name)
        try:
             # Basic backup of openhab dir
             if os.path.exists(openhab_path):
                with tarfile.open(backup_path, 'w:gz') as tar:
                    tar.add(openhab_path, arcname=os.path.basename(openhab_path))
                job['backups'].append({'name': backup_name, 'path': backup_path, 'ts': ts})
                save_jobs(self.jobs_dir, self._jobs)
        except Exception as e:
             logger.error(f"Failed to create pre-deploy backup: {e}")
             # Proceed? Or abort? Abort is safer.
             raise Exception(f"Backup failed, aborting deploy: {e}")

        deployed_count = 0
        try:
            for staged_path, real_path in mapping.items():
                if os.path.exists(staged_path):
                    # Ensure target dir exists
                    # resolve real_path absolute
                    target = real_path
                    if not os.path.isabs(target):
                        target = os.path.abspath(target)
                    
                    os.makedirs(os.path.dirname(target), exist_ok=True)
                    shutil.copy2(staged_path, target)
                    deployed_count += 1
                else:
                    logger.warning(f"Staged file missing: {staged_path}")
            
            job['deployed'] = True
            save_jobs(self.jobs_dir, self._jobs)
            return True, f"Deployed {deployed_count} files."
            
        except Exception as e:
            logger.error(f"Deploy failed: {e}")
            raise

    def enforce_retention(self):
        """Enforce retention policy: delete backups older than days or trim by count/size."""
        r = self.cfg.get('retention', {})
        days = int(r.get('days', 14))
        max_backups = int(r.get('max_backups', 50))
        max_size_mb = int(r.get('max_backups_size_mb', 500))
        # delete by age
        import time
        now = time.time()
        backups = []
        for fn in os.listdir(self.backups_dir):
            if not fn.endswith('.tar.gz'):
                continue
            fp = os.path.join(self.backups_dir, fn)
            st = os.stat(fp)
            backups.append({'name': fn, 'path': fp, 'mtime': st.st_mtime, 'size': st.st_size})
        # by age
        cutoff = now - days * 86400
        for b in backups:
            if b['mtime'] < cutoff:
                try:
                    os.remove(b['path'])
                except Exception:
                    pass
        # refresh list
        backups = sorted([b for b in backups if os.path.exists(b['path'])], key=lambda x: x['mtime'])
        # trim by count
        while len(backups) > max_backups:
            b = backups.pop(0)
            try:
                os.remove(b['path'])
            except Exception:
                pass
        # trim by size
        total = sum(b['size'] for b in backups)
        max_bytes = max_size_mb * 1024 * 1024
        while total > max_bytes and backups:
            b = backups.pop(0)
            try:
                os.remove(b['path'])
                total -= b['size']
            except Exception:
                pass

    def status(self):
        running = [j for j in self._jobs.values() if j['status'] == 'running']
        return {'jobs_total': len(self._jobs), 'jobs_running': len(running)}

    def update_job(self, job_id, updates):
        """Update job fields (used for persisting logs from frontend)."""
        if job_id not in self._jobs:
            return False
        job = self._jobs[job_id]
        if 'log' in updates:
            job['log'] = updates['log']
        with self.lock:
            save_jobs(self.jobs_dir, self._jobs)
        return True

    def delete_job(self, job_id):
        """Delete a job from history."""
        if job_id not in self._jobs:
            return False
        with self.lock:
            del self._jobs[job_id]
            if job_id in self.queues:
                del self.queues[job_id]
            save_jobs(self.jobs_dir, self._jobs)
        return True
