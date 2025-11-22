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

    def create_job(self, input_path, original_name=None):
        job_id = uuid.uuid4().hex
        job = {
            'id': job_id,
            'input': input_path,
            'name': original_name or os.path.basename(input_path),
            'status': 'queued',
            'created': int(__import__('time').time()),
            'backups': [],
            'log': []
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
                q.put({'type': 'backup', 'message': f'backup created: {backup_name}'})
                # enforce retention immediately after creating backup
                try:
                    self.enforce_retention()
                    q.put({'type': 'info', 'message': 'retention enforced'})
                except Exception as re:
                    q.put({'type': 'error', 'message': f'retention error: {re}'})
        except Exception as e:
            q.put({'type': 'error', 'message': f'backup failed: {e}'})

        # Call knxproject_to_openhab functions directly (in-process)
        try:
            q.put({'type': 'info', 'message': 'start in-process generation'})
            import importlib
            knxmod = importlib.import_module('knxproject_to_openhab')
            etsmod = importlib.import_module('ets_to_openhab')
            # load project (json dump or parse knxproj)
            if job['input'].lower().endswith('.json'):
                with open(job['input'], 'r', encoding='utf8') as f:
                    project = json.load(f)
                q.put({'type': 'info', 'message': 'read project JSON dump'})
            else:
                # try to parse knxproj archive using XKNXProj
                from xknxproject.xknxproj import XKNXProj
                q.put({'type': 'info', 'message': 'parsing knxproj archive (this may take a while)'} )
                knxproj = XKNXProj(path=job['input'], password=None, language='de-DE')
                project = knxproj.parse()
                q.put({'type': 'info', 'message': 'parsed knxproj'})

            # run the same sequence as the CLI main()
            building = knxmod.create_building(project)
            q.put({'type': 'info', 'message': 'building created'})
            addresses = knxmod.get_addresses(project)
            q.put({'type': 'info', 'message': f'{len(addresses)} addresses extracted'})
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

            q.put({'type': 'info', 'message': 'calling ets_to_openhab.main()'})
            # ets_to_openhab.main() writes output files; capture logging via job['log'] where possible
            # etsmod may use print/logging; we can't intercept easily without patching, but we signal progress
            etsmod.main()
            job['status'] = 'completed'
            q.put({'type': 'status', 'message': 'completed'})
        except Exception as e:
            job['status'] = 'failed'
            err_msg = str(e)
            tb = traceback.format_exc()
            q.put({'type': 'error', 'message': err_msg})
            q.put({'type': 'error', 'message': tb})
            job['log'].append(f"ERROR: {err_msg}")
            job['log'].append(tb)
        finally:
            save_jobs(self.jobs_dir, self._jobs)
            # signal end
            q.put(None)

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
