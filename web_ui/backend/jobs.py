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

        # Capture file statistics before generation
        file_stats_before = self._capture_file_stats(openhab_path)

        # Call knxproject_to_openhab functions directly (in-process)
        try:
            q.put({'type': 'info', 'level': 'info', 'message': 'start in-process generation'})
            import importlib
            knxmod = importlib.import_module('knxproject_to_openhab')
            etsmod = importlib.import_module('ets_to_openhab')
            # load project (json dump or parse knxproj)
            if job['input'].lower().endswith('.json'):
                with open(job['input'], 'r', encoding='utf8') as f:
                    project = json.load(f)
                q.put({'type': 'info', 'level': 'info', 'message': 'read project JSON dump'})
            else:
                # try to parse knxproj archive using XKNXProj
                from xknxproject.xknxproj import XKNXProj
                q.put({'type': 'info', 'level': 'info', 'message': 'parsing knxproj archive (this may take a while)'})
                pwd = job.get('password')
                knxproj = XKNXProj(path=job['input'], password=pwd, language='de-DE')
                project = knxproj.parse()
                q.put({'type': 'info', 'level': 'info', 'message': 'parsed knxproj'})

            # run the same sequence as the CLI main()
            building = knxmod.create_building(project)
            q.put({'type': 'info', 'level': 'debug', 'message': 'building created'})
            addresses = knxmod.get_addresses(project)
            q.put({'type': 'info', 'level': 'info', 'message': f'{len(addresses)} addresses extracted'})
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

            q.put({'type': 'info', 'level': 'info', 'message': 'calling ets_to_openhab.main()'})
            
            # Capture stdout/stderr to get "No Room found..." and other print outputs
            old_stdout = sys.stdout
            old_stderr = sys.stderr
            captured_output = io.StringIO()
            sys.stdout = captured_output
            sys.stderr = captured_output
            
            try:
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

            
            
            # Capture file statistics after generation and compute deltas
            file_stats_after = self._capture_file_stats(openhab_path)
            job['stats'] = self._compute_file_deltas(file_stats_before, file_stats_after)
            for fn, stat in sorted(job['stats'].items()):
                msg = f"{fn}: {stat['before']} → {stat['after']} lines ({stat['delta']:+d})"
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

    def _capture_file_stats(self, path):
        """Capture line counts for all .items, .things, .sitemap, .rules, .persist files."""
        stats = {}
        if not os.path.exists(path):
            return stats
        for root, dirs, files in os.walk(path):
            for fname in files:
                if any(fname.endswith(ext) for ext in ['.items', '.things', '.sitemap', '.rules', '.persist']):
                    fpath = os.path.join(root, fname)
                    try:
                        with open(fpath, 'r', encoding='utf8', errors='ignore') as f:
                            lines = len(f.readlines())
                        relpath = os.path.relpath(fpath, path)
                        stats[relpath] = lines
                    except Exception:
                        pass
        return stats

    def _compute_file_deltas(self, before, after):
        """Compute line count changes: {filename: {before, after, delta}}."""
        all_files = set(before.keys()) | set(after.keys())
        deltas = {}
        for fname in sorted(all_files):
            b = before.get(fname, 0)
            a = after.get(fname, 0)
            deltas[fname] = {'before': b, 'after': a, 'delta': a - b}
        return deltas

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
