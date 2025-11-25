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
        self.jobs_dir = cfg.get('jobs_dir', './var/lib/knx_to_openhab')
        self.backups_dir = cfg.get('backups_dir', './var/backups/knx_to_openhab')
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
        with self.lock:
            self._jobs[job_id] = job
            save_jobs(self.jobs_dir, self._jobs)
        q = queue.Queue()
        self.queues[job_id] = q
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

        # (Stats capture removed - using backup for comparison)

        # Call knxproject_to_openhab functions directly (in-process)
        try:
            q.put({'type': 'info', 'level': 'info', 'message': 'start in-process generation'})
            import importlib
            knxmod = importlib.import_module('knxproject_to_openhab')
            etsmod = importlib.import_module('ets_to_openhab')
            
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
                q.put({'type': 'info', 'level': 'info', 'message': 'calling ets_to_openhab.main()'})
                sys.stdout = captured_output
                
                # ets_to_openhab.main() writes output files
                etsmod.main()
                
            finally:
                sys.stdout = old_stdout
                sys.stderr = old_stderr
                
                # Send captured output line by line to the queue
                # Parse log level from message (WARNING:..., ERROR:..., etc.)
                captured = captured_output.getvalue()
                if captured:
                    for line in captured.strip().split('\n'):
                        if line.strip():
                            # Detect log level from message content
                            level = 'info'
                            message = line.strip()
                            
                            # Check for WARNING: prefix
                            if message.startswith('WARNING:'):
                                level = 'warning'
                                # Remove the "WARNING:" prefix
                                message = message[len('WARNING:'):].strip()
                            elif message.startswith('ERROR:'):
                                level = 'error'
                                # Remove the "ERROR:" prefix
                                message = message[len('ERROR:'):].strip()
                            elif 'WARNING:' in message and ':' in message:
                                # e.g., "WARNING:ets_to_openhab:incomplete dimmer: ..."
                                level = 'warning'
                                # Extract message after the last ':'
                                parts = message.split(':')
                                if len(parts) > 2:
                                    message = ':'.join(parts[2:]).strip()
                            
                            q.put({'type': 'info', 'level': level, 'message': message})

            
            
            
            # Compute detailed statistics by comparing with backup
            job['stats'] = self._compute_detailed_stats(openhab_path, backup_path)
            for fn, stat in sorted(job['stats'].items()):
                msg = f"{fn}: {stat['before']} → {stat['after']} lines ({stat['delta']:+d}) [+{stat['added']}/-{stat['removed']}]"
                q.put({'type': 'stats', 'level': 'info', 'message': msg})
            
            job['status'] = 'completed'
            q.put({'type': 'status', 'level': 'info', 'message': 'completed'})
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
            # signal end
            q.put(None)

    def _compute_detailed_stats(self, openhab_path, backup_path):
        """Compute detailed diff stats (added, removed) by comparing current files with backup."""
        import difflib
        stats = {}
        
        # Get list of current files
        current_files = {}
        if os.path.exists(openhab_path):
            for root, dirs, files in os.walk(openhab_path):
                for fname in files:
                    if any(fname.endswith(ext) for ext in ['.items', '.things', '.sitemap', '.rules', '.persist']):
                        fpath = os.path.join(root, fname)
                        relpath = os.path.relpath(fpath, openhab_path).replace('\\', '/')
                        try:
                            with open(fpath, 'r', encoding='utf8', errors='ignore') as f:
                                current_files[relpath] = f.readlines()
                        except Exception:
                            pass

        # Get list of original files from backup
        original_files = {}
        if os.path.exists(backup_path):
            try:
                with tarfile.open(backup_path, 'r:gz') as tar:
                    for member in tar.getmembers():
                        if member.isfile() and any(member.name.endswith(ext) for ext in ['.items', '.things', '.sitemap', '.rules', '.persist']):
                            # member.name is like "openhab/items/knx.items"
                            # we need relative path from openhab root
                            # assuming backup structure is openhab/...
                            parts = member.name.replace('\\', '/').split('/', 1)
                            if len(parts) > 1:
                                relpath = parts[1]
                                f = tar.extractfile(member)
                                if f:
                                    wrapper = io.TextIOWrapper(f, encoding='utf-8', errors='ignore')
                                    original_files[relpath] = wrapper.readlines()
            except Exception as e:
                # Log error but continue
                print(f"Error reading backup for stats: {e}")

        # Compute diffs
        all_files = set(current_files.keys()) | set(original_files.keys())
        for fname in sorted(all_files):
            orig_lines = original_files.get(fname, [])
            curr_lines = current_files.get(fname, [])
            
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
            
        return stats

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
