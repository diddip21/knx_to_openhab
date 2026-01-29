import os
import json
import io
import time
from typing import Optional


def load_config():
    base = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    cfg_file = os.path.join(base, "web_ui", "backend", "config.json")
    if not os.path.exists(cfg_file):
        # defaults
        return {
            "openhab_path": os.path.join(base, "openhab"),
            "jobs_dir": os.path.join(base, "var", "lib", "knx_to_openhab"),
            "backups_dir": os.path.join(base, "var", "backups", "knx_to_openhab"),
            "bind_host": "0.0.0.0",
            "port": 8085,
        }
    with open(cfg_file, "r") as f:
        return json.load(f)


def ensure_dirs(paths):
    for p in paths:
        os.makedirs(p, exist_ok=True)


def jobs_file(jobs_dir):
    os.makedirs(jobs_dir, exist_ok=True)
    return os.path.join(jobs_dir, "jobs.json")


def load_jobs(jobs_dir):
    jf = jobs_file(jobs_dir)
    if not os.path.exists(jf):
        return {}
    with open(jf, "r") as f:
        return json.load(f)


def save_jobs(jobs_dir, jobs):
    jf = jobs_file(jobs_dir)
    tmp_file = jf + ".tmp"

    # Write to temporary file
    with open(tmp_file, "w", encoding="utf-8") as f:
        json.dump(jobs, f, indent=2, ensure_ascii=False)

    # Windows-safe atomic replacement
    # On Windows, os.replace() can fail with PermissionError if the target file is in use
    # Try to replace, and if it fails on Windows, use a fallback strategy
    try:
        os.replace(tmp_file, jf)
    except (PermissionError, OSError) as e:
        import sys

        if sys.platform == "win32":
            # Windows fallback: try removing target first, then rename
            try:
                if os.path.exists(jf):
                    os.remove(jf)
                os.rename(tmp_file, jf)
            except (PermissionError, OSError):
                # Last resort: copy content and remove temp
                import shutil

                shutil.copy2(tmp_file, jf)
                try:
                    os.remove(tmp_file)
                except:
                    pass  # Ignore errors cleaning up temp file
        else:
            # Re-raise on non-Windows platforms
            raise


def save_job(jobs_dir, job):
    jobs = load_jobs(jobs_dir)
    jobs[job["id"]] = job
    save_jobs(jobs_dir, jobs)


# New helpers for per-job persistent logs and metadata


def job_dir(jobs_dir: str, job_id: str) -> str:
    d = os.path.join(jobs_dir, job_id)
    os.makedirs(d, exist_ok=True)
    return d


def job_log_path(jobs_dir: str, job_id: str) -> str:
    return os.path.join(job_dir(jobs_dir, job_id), "log.txt")


def job_meta_path(jobs_dir: str, job_id: str) -> str:
    return os.path.join(job_dir(jobs_dir, job_id), "metadata.json")


def open_job_log(jobs_dir: str, job_id: str, mode: str = "ab"):
    """Open the job log file. Default is append binary. Caller must close file."""
    path = job_log_path(jobs_dir, job_id)
    return open(path, mode)


def append_job_log(jobs_dir: str, job_id: str, data: bytes):
    path = job_log_path(jobs_dir, job_id)
    with open(path, "ab") as f:
        f.write(data)
        f.flush()
        os.fsync(f.fileno())


def read_job_log(jobs_dir: str, job_id: str, offset: Optional[int] = None) -> bytes:
    path = job_log_path(jobs_dir, job_id)
    if not os.path.exists(path):
        return b""
    with open(path, "rb") as f:
        if offset:
            f.seek(offset)
        return f.read()


def read_job_metadata(jobs_dir: str, job_id: str) -> Optional[dict]:
    path = job_meta_path(jobs_dir, job_id)
    if not os.path.exists(path):
        return None
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def write_job_metadata(jobs_dir: str, job_id: str, meta: dict):
    path = job_meta_path(jobs_dir, job_id)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2, ensure_ascii=False)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def update_job_metadata(jobs_dir: str, job_id: str, **kwargs):
    meta = read_job_metadata(jobs_dir, job_id) or {}
    meta.update(kwargs)
    meta["updated_at"] = int(time.time())
    write_job_metadata(jobs_dir, job_id, meta)
