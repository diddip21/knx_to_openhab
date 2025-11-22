import os
import json


def load_config():
    base = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
    cfg_file = os.path.join(base, 'web_ui', 'backend', 'config.json')
    if not os.path.exists(cfg_file):
        # defaults
        return {
            'openhab_path': os.path.join(base, 'openhab'),
            'jobs_dir': os.path.join(base, 'var', 'lib', 'knx_to_openhab'),
            'backups_dir': os.path.join(base, 'var', 'backups', 'knx_to_openhab'),
            'bind_host': '0.0.0.0',
            'port': 8080
        }
    with open(cfg_file, 'r') as f:
        return json.load(f)


def ensure_dirs(paths):
    for p in paths:
        os.makedirs(p, exist_ok=True)


def jobs_file(jobs_dir):
    os.makedirs(jobs_dir, exist_ok=True)
    return os.path.join(jobs_dir, 'jobs.json')


def load_jobs(jobs_dir):
    jf = jobs_file(jobs_dir)
    if not os.path.exists(jf):
        return {}
    with open(jf, 'r') as f:
        return json.load(f)


def save_jobs(jobs_dir, jobs):
    jf = jobs_file(jobs_dir)
    with open(jf + '.tmp', 'w') as f:
        json.dump(jobs, f, indent=2)
    os.replace(jf + '.tmp', jf)


def save_job(jobs_dir, job):
    jobs = load_jobs(jobs_dir)
    jobs[job['id']] = job
    save_jobs(jobs_dir, jobs)
