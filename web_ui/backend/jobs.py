import io
import json
import logging
import os
import queue
import re
import subprocess
import sys
import tarfile
import threading
import traceback
import uuid
from concurrent.futures import ThreadPoolExecutor

from completeness import check_completeness, iter_thing_lines

from .deploy_policy import (
    configured_managed_paths,
    deploy_staged_files,
    retire_managed_files,
    restore_managed_files,
)
from .storage import ensure_dirs, load_jobs, save_jobs

logger = logging.getLogger(__name__)


def _reload_generator_modules(project_root):
    """Reload config before generator modules that bind its values at import time."""
    import importlib

    if project_root not in sys.path:
        sys.path.insert(0, project_root)

    import config as global_config_module

    importlib.reload(global_config_module)
    etsmod = importlib.reload(importlib.import_module("ets_to_openhab"))
    knxmod = importlib.reload(importlib.import_module("knxproject_to_openhab"))
    return global_config_module, etsmod, knxmod


def _password_error_message(error):
    msg = str(error).lower()
    password_markers = [
        "bad password",
        "wrong password",
        "password required",
        "password-protected",
        "password protected",
        "encrypted",
        "decrypt",
        "decryption",
    ]
    if any(marker in msg for marker in password_markers):
        return (
            "This KNX project appears to be password-protected or the password is incorrect. "
            "Please enter the correct password in the upload form and try again."
        )
    return None


class JobManager:
    def __init__(self, cfg):
        self.cfg = cfg
        # Use the configured backup directory from config, with a sensible default
        jobs_dir_config = cfg.get("jobs_dir", "var/lib/knx_to_openhab")
        staging_dir_config = cfg.get("staging_dir", jobs_dir_config)
        backups_dir_config = cfg.get("backups_dir", "var/backups/knx_to_openhab")

        # If paths are relative, make them relative to project root
        project_root = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
        if not os.path.isabs(jobs_dir_config):
            self.jobs_dir = os.path.join(project_root, jobs_dir_config)
        else:
            self.jobs_dir = jobs_dir_config

        if not os.path.isabs(staging_dir_config):
            self.staging_dir = os.path.join(project_root, staging_dir_config)
        else:
            self.staging_dir = staging_dir_config

        if not os.path.isabs(backups_dir_config):
            self.backups_dir = os.path.join(project_root, backups_dir_config)
        else:
            self.backups_dir = backups_dir_config

        ensure_dirs([self.jobs_dir, self.staging_dir, self.backups_dir])
        self._jobs = load_jobs(self.jobs_dir)
        self.queues = {}
        self._preview_cache = {}
        self.executor = ThreadPoolExecutor(max_workers=2)
        self.lock = threading.Lock()

    def _reload_jobs(self):
        """Reload jobs from disk with a merge strategy to avoid clobbering active state."""
        with self.lock:
            disk_jobs = load_jobs(self.jobs_dir)
            for jid, d_job in disk_jobs.items():
                if jid not in self._jobs:
                    # New job from another process/disk
                    self._jobs[jid] = d_job
                else:
                    # Job exists in both.
                    m_job = self._jobs[jid]
                    m_status = m_job.get("status")
                    d_status = d_job.get("status")

                    # Merge logic:
                    # 1. If memory job is 'running', don't overwrite (active worker owns it)
                    # 2. If memory job is 'completed'/'failed' but disk is still 'running',
                    #    don't overwrite (worker just finished, disk is stale)
                    if m_status == "running":
                        continue
                    if m_status in ["completed", "failed"] and d_status == "running":
                        continue

                    self._jobs[jid] = d_job

    def list_jobs(self):
        self._reload_jobs()
        jobs = list(self._jobs.values())
        for j in jobs:
            j["auto_place_unknown"] = self.cfg.get("general", {}).get("auto_place_unknown", False)
        return jobs

    def get_job(self, job_id):
        job = self._jobs.get(job_id)
        if not job:
            self._reload_jobs()
            job = self._jobs.get(job_id)
        if job is not None:
            job["auto_place_unknown"] = self.cfg.get("general", {}).get("auto_place_unknown", False)
        return job

    def get_queue(self, job_id):
        # Ensure job exists before returning queue
        if job_id not in self._jobs:
            return None
        return self.queues.get(job_id)

    def create_job(self, input_path, original_name=None, password=None):
        job_id = uuid.uuid4().hex
        job = {
            "id": job_id,
            "input": input_path,
            "name": original_name or os.path.basename(input_path),
            "status": "queued",
            "created": int(__import__("time").time()),
            "backups": [],
            "log": [],
            "stats": {},
            # SECURITY: Do NOT store password in job JSON - keep only in memory
        }
        # Store password in memory only (for job processing)
        self._passwords = getattr(self, "_passwords", {})
        self._passwords[job_id] = password

        q = queue.Queue()
        try:
            with self.lock:
                self._jobs[job_id] = job
                self.queues[job_id] = q  # Register queue before saving jobs
                save_jobs(self.jobs_dir, self._jobs)
            self.executor.submit(self._run_job, job_id)
        except Exception:
            # A worker is not guaranteed to run, so remove the in-memory
            # secret and roll back the partially created job immediately.
            with self.lock:
                self._passwords.pop(job_id, None)
                self._jobs.pop(job_id, None)
                self.queues.pop(job_id, None)
                try:
                    save_jobs(self.jobs_dir, self._jobs)
                except Exception:
                    logger.exception("Failed to persist job rollback for %s", job_id)
            raise
        return job

    def save_job_preview(self, job_id, preview):
        """Persist a passphrase-free project preview outside the public job data."""
        self._preview_cache[job_id] = preview
        job_dir = os.path.join(self.jobs_dir, job_id)
        os.makedirs(job_dir, exist_ok=True)
        preview_path = os.path.join(job_dir, "project-preview.json")
        temp_path = f"{preview_path}.{uuid.uuid4().hex}.tmp"
        try:
            with open(temp_path, "w", encoding="utf-8") as preview_file:
                json.dump(preview, preview_file, ensure_ascii=False)
            os.chmod(temp_path, 0o600)
            os.replace(temp_path, preview_path)
        finally:
            if os.path.exists(temp_path):
                os.remove(temp_path)

    def get_job_preview(self, job_id):
        """Load a cached project preview without reopening the source archive."""
        if job_id in self._preview_cache:
            return self._preview_cache[job_id]

        preview_path = os.path.join(self.jobs_dir, job_id, "project-preview.json")
        try:
            with open(preview_path, "r", encoding="utf-8") as preview_file:
                preview = json.load(preview_file)
        except FileNotFoundError:
            return None
        except (OSError, json.JSONDecodeError):
            logger.exception("Failed to read cached project preview for %s", job_id)
            return None

        self._preview_cache[job_id] = preview
        return preview

    def _log_to_queue(self, job_id, q, msg):
        """Helper to both send to queue and persist in job log."""
        job = self._jobs.get(job_id)
        if job:
            # Format msg for log storage consistent with frontend expectations
            log_entry = {
                "level": msg.get("level", "info"),
                "text": msg.get("message", ""),
            }
            # Also support legacy string format if needed, but dict is better
            if msg.get("type") == "stats":
                log_entry["text"] = f"[STATS] {msg.get('message')}"
            elif msg.get("type") == "backup":
                log_entry["text"] = f"[BACKUP] {msg.get('message')}"
            elif msg.get("type") == "status":
                log_entry["text"] = f"[STATUS] {msg.get('message')}"

            job["log"].append(log_entry)
            # Periodic save? For now save at the end or on certain events
        q.put(msg)

    def _run_job(self, job_id):
        job = self._jobs[job_id]
        q = self.queues[job_id]
        job["status"] = "running"
        save_jobs(self.jobs_dir, self._jobs)

        # Retrieve password from in-memory store (not from job JSON).
        passwords = getattr(self, "_passwords", {})
        pwd = passwords.get(job_id)
        # Process logic
        original_openhab_path = None
        try:
            self._log_to_queue(
                job_id,
                q,
                {
                    "type": "info",
                    "level": "info",
                    "message": "start in-process generation",
                },
            )
            import copy

            # Reload config before its consumers: both generator modules import the
            # config dict directly, and config.py replaces that dict on reload.
            project_root = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
            global_config_module, etsmod, knxmod = _reload_generator_modules(project_root)

            # Setup Staging
            if os.path.abspath(self.staging_dir) == os.path.abspath(self.jobs_dir):
                staging_dir = os.path.join(self.jobs_dir, job_id, "staging")
            else:
                staging_dir = os.path.join(self.staging_dir, job_id)
            ensure_dirs([staging_dir])

            # Use the same validated paths for generation, deployment and rollback.
            openhab_path, managed_paths = configured_managed_paths(
                global_config_module.config, project_root
            )
            job["openhab_root"] = openhab_path
            job["managed_targets"] = sorted(set(managed_paths.values()))

            # Back up the same effective OpenHAB root that generation and deploy use.
            ts = __import__("time").strftime("%Y%m%d-%H%M%S")
            backup_name = f"{job_id}-{ts}.tar.gz"
            backup_path = os.path.join(self.backups_dir, backup_name)
            try:
                if os.path.isdir(openhab_path):
                    with tarfile.open(backup_path, "w:gz") as tar:
                        tar.add(openhab_path, arcname=os.path.basename(openhab_path))
                    job["backups"].append({"name": backup_name, "path": backup_path, "ts": ts})
                    save_jobs(self.jobs_dir, self._jobs)
                    self._log_to_queue(
                        job_id,
                        q,
                        {
                            "type": "backup",
                            "level": "info",
                            "message": f"backup created: {backup_name}",
                        },
                    )
                    try:
                        self.enforce_retention()
                    except Exception as retention_error:
                        self._log_to_queue(
                            job_id,
                            q,
                            {
                                "type": "error",
                                "level": "warning",
                                "message": f"retention error: {retention_error}",
                            },
                        )
            except Exception as backup_error:
                self._log_to_queue(
                    job_id,
                    q,
                    {
                        "type": "error",
                        "level": "error",
                        "message": f"backup failed: {backup_error}",
                    },
            )

            # Create a copy of the config dict to modify
            staged_config = copy.copy(global_config_module.config)
            staged_config["openhab_path"] = os.path.join(staging_dir, "openhab")

            # Ensure knxproject_to_openhab uses staged openhab_path for reports
            original_openhab_path = global_config_module.config.get("openhab_path")
            global_config_module.config["openhab_path"] = staged_config["openhab_path"]
            knxmod.config["openhab_path"] = staged_config["openhab_path"]

            # Define output keys to override
            output_format = str(staged_config.get("output_format", "legacy")).casefold()
            model_output_keys = (
                ["yaml_path"]
                if output_format == "yaml"
                else ["items_path", "things_path", "sitemaps_path"]
            )
            retired_keys = (
                ["items_path", "things_path", "sitemaps_path"]
                if output_format == "yaml"
                else ["yaml_path"]
            )
            retired_paths = [managed_paths[key] for key in retired_keys if key in managed_paths]
            output_keys = [
                key
                for key in model_output_keys + ["influx_path", "fenster_path"]
                if key in managed_paths and key in global_config_module.config
            ]
            stage_mapping = {}  # staged_path -> real_absolute_path

            q.put(
                {
                    "type": "info",
                    "level": "info",
                    "message": f"Staging directory: {staging_dir}",
                }
            )

            for key in output_keys:
                relative = managed_paths[key]
                staged_path = os.path.join(staging_dir, "openhab", *relative.split("/"))
                os.makedirs(os.path.dirname(staged_path), exist_ok=True)
                staged_config[key] = staged_path
                stage_mapping[staged_path] = os.path.join(openhab_path, *relative.split("/"))

            # Capture stdout/stderr for ENTIRE generation process
            old_stdout = sys.stdout
            old_stderr = sys.stderr
            captured_output = io.StringIO()
            sys.stdout = captured_output
            sys.stderr = captured_output

            try:
                # load project (json dump or parse knxproj)
                if job["input"].lower().endswith(".json"):
                    with open(job["input"], "r", encoding="utf8") as f:
                        project = json.load(f)
                    # Temporarily restore stdout to log message
                    sys.stdout = old_stdout
                    self._log_to_queue(
                        job_id,
                        q,
                        {
                            "type": "info",
                            "level": "info",
                            "message": "read project JSON dump",
                        },
                    )
                    sys.stdout = captured_output
                else:
                    # try to parse knxproj archive using XKNXProj
                    from xknxproject.xknxproj import XKNXProj

                    sys.stdout = old_stdout
                    self._log_to_queue(
                        job_id,
                        q,
                        {
                            "type": "info",
                            "level": "info",
                            "message": "parsing knxproj archive (this may take a while)",
                        },
                    )
                    sys.stdout = captured_output
                    knxproj = XKNXProj(path=job["input"], password=pwd, language="de-DE")
                    project = knxproj.parse()
                    sys.stdout = old_stdout
                    self._log_to_queue(
                        job_id,
                        q,
                        {"type": "info", "level": "info", "message": "parsed knxproj"},
                    )
                    sys.stdout = captured_output

                # run the same sequence as the CLI main()
                building = knxmod.create_building(project)
                addresses = knxmod.get_addresses(project)
                sys.stdout = old_stdout
                self._log_to_queue(
                    job_id,
                    q,
                    {
                        "type": "info",
                        "level": "info",
                        "message": f"{len(addresses)} addresses extracted",
                    },
                )
                sys.stdout = captured_output

                house = knxmod.put_addresses_in_building(building, addresses, project)
                from .project_preview import build_project_preview

                try:
                    self.save_job_preview(
                        job_id,
                        build_project_preview(
                            project,
                            knxmod,
                            parsed=(building, addresses, house),
                        ),
                    )
                except Exception as preview_error:
                    self._log_to_queue(
                        job_id,
                        q,
                        {
                            "type": "info",
                            "level": "warning",
                            "message": f"project structure preview could not be saved: {preview_error}",
                        },
                    )
                prj_name = house[0].get("name_long") if house else None
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
                self._log_to_queue(
                    job_id,
                    q,
                    {
                        "type": "info",
                        "level": "info",
                        "message": "generating files (staged)...",
                    },
                )
                sys.stdout = captured_output

                # ets_to_openhab.main() writes output files to STAGING via injected config
                generation_result = etsmod.main(configuration=staged_config)

                # Generate completeness report from staged knx.things
                try:
                    report_path = self._write_completeness_report(
                        staged_config.get("things_path"),
                        staged_config.get("openhab_path", ""),
                        things_text=generation_result.get("things"),
                    )
                    if report_path:
                        self._log_to_queue(
                            job_id,
                            q,
                            {
                                "type": "info",
                                "level": "info",
                                "message": f"completeness report written: {report_path}",
                            },
                        )
                except Exception as report_err:
                    self._log_to_queue(
                        job_id,
                        q,
                        {
                            "type": "error",
                            "level": "warning",
                            "message": f"completeness report failed: {report_err}",
                        },
                    )

                # Add reports to stage mapping if present
                for report in (
                    "unknown_report.json",
                    "partial_report.json",
                    "completeness_report.json",
                ):
                    staged_report = os.path.join(staged_config.get("openhab_path", ""), report)
                    if staged_report and os.path.exists(staged_report):
                        real_report = os.path.join(openhab_path, *managed_paths[report].split("/"))
                        stage_mapping[staged_report] = real_report

            finally:
                sys.stdout = old_stdout
                sys.stderr = old_stderr

                # Send captured output line by line to the queue
                captured = captured_output.getvalue()
                if captured:
                    for line in captured.strip().split("\n"):
                        if line.strip():
                            level = "info"
                            message = line.strip()
                            if message.startswith("WARNING:"):
                                level = "warning"
                                message = message[len("WARNING:") :].strip()
                            elif message.startswith("ERROR:"):
                                level = "error"
                                message = message[len("ERROR:") :].strip()
                            elif "WARNING:" in message and ":" in message:
                                level = "warning"
                                parts = message.split(":")
                                if len(parts) > 2:
                                    message = ":".join(parts[2:]).strip()
                            self._log_to_queue(
                                job_id,
                                q,
                                {"type": "info", "level": level, "message": message},
                            )

            # Save staging info to job
            job["staging_dir"] = staging_dir
            job["stage_mapping"] = stage_mapping
            job["retired_paths"] = retired_paths
            job["output_format"] = output_format
            job["staged"] = True

            # Compute statistics by comparing STAGED vs LIVE/BACKUP
            try:
                detailed_stats = self._compute_staged_stats(stage_mapping, openhab_path)
                detailed_stats.update(self._compute_retired_stats(retired_paths, openhab_path))
                job["stats"] = detailed_stats

                for fn, stat in sorted(job["stats"].items()):
                    before = int(stat.get("before", 0))
                    after = int(stat.get("after", 0))
                    delta = int(stat.get("delta", after - before))
                    added = int(stat.get("added", 0))
                    removed = int(stat.get("removed", 0))
                    msg = f"{fn}: {before} -> {after} lines ({delta:+d}) [+{added}/-{removed}]"
                    self._log_to_queue(
                        job_id, q, {"type": "stats", "level": "info", "message": msg}
                    )

            except Exception as stats_error:
                self._log_to_queue(
                    job_id,
                    q,
                    {
                        "type": "error",
                        "level": "error",
                        "message": f"Stats error: {str(stats_error)}",
                    },
                )
                # fallback empty stats
                job["stats"] = {}

            job["status"] = "completed"
            self._log_to_queue(
                job_id,
                q,
                {
                    "type": "status",
                    "level": "info",
                    "message": "completed (staged) - ready to deploy",
                },
            )
        except Exception as e:
            job["status"] = "failed"
            err_msg = str(e)
            friendly_msg = _password_error_message(e)
            if friendly_msg:
                job["error"] = friendly_msg
                self._log_to_queue(
                    job_id,
                    q,
                    {"type": "error", "level": "error", "message": friendly_msg},
                )
            else:
                job["error"] = err_msg
            tb = traceback.format_exc()
            self._log_to_queue(job_id, q, {"type": "error", "level": "error", "message": err_msg})
            # TB might be long, but we need it for debugging
            self._log_to_queue(job_id, q, {"type": "error", "level": "error", "message": tb})
        finally:
            if original_openhab_path is not None:
                try:
                    import config as global_config_module
                    import knxproject_to_openhab as knxmod

                    global_config_module.config["openhab_path"] = original_openhab_path
                    knxmod.config["openhab_path"] = original_openhab_path
                except Exception:
                    pass
            # SECURITY: Clear password from memory after job completes
            passwords = getattr(self, "_passwords", {})
            passwords.pop(job_id, None)
            save_jobs(self.jobs_dir, self._jobs)
            q.put(None)

    def _extract_thing_info(self, line):
        match = re.search(
            r'^Type\s+(?P<kind>\w+)\s*:\s*(?P<id>\S+)\s+"(?P<label>[^"]*)"',
            line,
        )
        if not match:
            return None
        return {
            "kind": match.group("kind"),
            "id": match.group("id"),
            "label": match.group("label"),
        }

    def _write_completeness_report(self, things_path, openhab_path, things_text=None):
        if things_text is None:
            if not things_path or not os.path.exists(things_path):
                return None
            with open(things_path, "r", encoding="utf-8", errors="ignore") as f:
                things_text = f.read()

        missing_required_tuples, recommended_missing_tuples = check_completeness(things_text)

        def _map_entries(entries):
            mapped = []
            for kind, reason, line in entries:
                info = self._extract_thing_info(line)
                if not info:
                    continue
                mapped.append(
                    {
                        **info,
                        "reason": reason,
                        "line": line,
                    }
                )
            return mapped

        missing_required = _map_entries(missing_required_tuples)
        recommended_missing = _map_entries(recommended_missing_tuples)

        total_things_checked = sum(1 for _ in iter_thing_lines(things_text))

        report = {
            "summary": {
                "missing_required": len(missing_required),
                "recommended_missing": len(recommended_missing),
                "total_things_checked": total_things_checked,
            },
            "missing_required": missing_required,
            "recommended_missing": recommended_missing,
        }

        if not openhab_path:
            openhab_path = os.path.dirname(things_path)
        report_path = os.path.join(openhab_path, "completeness_report.json")
        with open(report_path, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2, ensure_ascii=False)

        return report_path

    def _compute_staged_stats(self, stage_mapping, openhab_path):
        """Compute line and diff statistics for staged files against their live targets."""
        import difflib

        stats = {}
        abs_openhab_path = os.path.normpath(os.path.abspath(openhab_path))

        for staged_path, real_path in stage_mapping.items():
            try:
                with open(staged_path, "r", encoding="utf-8", errors="ignore") as staged_file:
                    staged_lines = staged_file.readlines()
            except OSError as error:
                logger.warning("Could not read staged file %s: %s", staged_path, error)
                continue

            abs_real_path = os.path.normpath(os.path.abspath(real_path))
            live_lines = []
            if os.path.exists(abs_real_path):
                try:
                    with open(abs_real_path, "r", encoding="utf-8", errors="ignore") as live_file:
                        live_lines = live_file.readlines()
                except OSError as error:
                    logger.warning("Could not read live file %s: %s", abs_real_path, error)

            added = 0
            removed = 0
            matcher = difflib.SequenceMatcher(None, live_lines, staged_lines)
            for tag, old_start, old_end, new_start, new_end in matcher.get_opcodes():
                if tag in ("replace", "delete"):
                    removed += old_end - old_start
                if tag in ("replace", "insert"):
                    added += new_end - new_start

            try:
                is_openhab_file = (
                    os.path.commonpath([abs_real_path, abs_openhab_path]) == abs_openhab_path
                )
            except ValueError:
                is_openhab_file = False

            if is_openhab_file:
                relative_path = os.path.relpath(abs_real_path, abs_openhab_path)
            elif os.path.isabs(real_path):
                relative_path = os.path.basename(real_path)
            else:
                relative_path = os.path.relpath(abs_real_path, os.getcwd())

            stats[relative_path.replace("\\", "/")] = {
                "before": len(live_lines),
                "after": len(staged_lines),
                "delta": len(staged_lines) - len(live_lines),
                "added": added,
                "removed": removed,
                "staged_path": staged_path,
                "real_path": abs_real_path,
            }

        return stats

    def _compute_retired_stats(self, retired_paths, openhab_path):
        """Report generated files that will be removed during a format transition."""
        stats = {}
        abs_openhab_path = os.path.normpath(os.path.abspath(openhab_path))
        for path in retired_paths:
            relative_path = os.path.relpath(path, abs_openhab_path) if os.path.isabs(path) else path
            absolute_path = os.path.normpath(os.path.join(abs_openhab_path, relative_path))
            if not os.path.isfile(absolute_path):
                continue
            try:
                with open(absolute_path, "r", encoding="utf-8", errors="ignore") as file:
                    before = len(file.readlines())
            except OSError:
                continue
            try:
                in_openhab = (
                    os.path.commonpath([absolute_path, abs_openhab_path]) == abs_openhab_path
                )
            except ValueError:
                in_openhab = False
            if not in_openhab:
                relative_path = os.path.basename(absolute_path)
            stats[relative_path.replace("\\", "/")] = {
                "before": before,
                "after": 0,
                "delta": -before,
                "added": 0,
                "removed": before,
                "staged_path": "",
                "real_path": absolute_path,
                "retired": True,
            }
        return stats

    def get_file_diff(self, job_id, rel_path):
        """Get diff for a specific file in a job (comparing Staged vs Live)."""
        job = self._jobs.get(job_id)
        if not job:
            return None

        openhab_path = job.get("openhab_root", self.cfg.get("openhab_path", "openhab"))

        # 1. Original = Live Running Config
        orig_lines = []
        live_fpath = os.path.join(openhab_path, rel_path)
        if os.path.exists(live_fpath):
            try:
                with open(live_fpath, "r", encoding="utf8", errors="ignore") as f:
                    orig_lines = f.readlines()
            except Exception:
                pass

        # 2. Current = Staged file from Job
        curr_lines = []
        staged_path = None

        # Try to get from stats (new jobs)
        if "stats" in job and rel_path in job["stats"]:
            staged_path = job["stats"][rel_path].get("staged_path")

        # Fallback: construct from staging_dir
        if (not staged_path or not os.path.exists(staged_path)) and "staging_dir" in job:
            staged_path = os.path.join(job["staging_dir"], "openhab", rel_path)

        if staged_path and os.path.isfile(staged_path):
            try:
                with open(staged_path, "r", encoding="utf-8", errors="replace") as f:
                    curr_lines = f.readlines()
            except Exception:
                pass

        # If staged file doesn't exist, we might be comparing a deleted file or something is wrong.
        # But if we got here, we usually have a staged file.

        import difflib

        diff_lines = []
        matcher = difflib.SequenceMatcher(None, orig_lines, curr_lines)
        for tag, i1, i2, j1, j2 in matcher.get_opcodes():
            if tag == "equal":
                for i in range(i1, i2):
                    diff_lines.append(
                        {
                            "type": "unchanged",
                            "line": orig_lines[i].rstrip("\n"),
                            "orig_ln": i + 1,
                            "curr_ln": j1 + (i - i1) + 1,
                        }
                    )
            elif tag == "replace":
                for i in range(i1, i2):
                    diff_lines.append(
                        {
                            "type": "removed",
                            "line": orig_lines[i].rstrip("\n"),
                            "orig_ln": i + 1,
                        }
                    )
                for j in range(j1, j2):
                    diff_lines.append(
                        {
                            "type": "added",
                            "line": curr_lines[j].rstrip("\n"),
                            "curr_ln": j + 1,
                        }
                    )
            elif tag == "delete":
                for i in range(i1, i2):
                    diff_lines.append(
                        {
                            "type": "removed",
                            "line": orig_lines[i].rstrip("\n"),
                            "orig_ln": i + 1,
                        }
                    )
            elif tag == "insert":
                for j in range(j1, j2):
                    diff_lines.append(
                        {
                            "type": "added",
                            "line": curr_lines[j].rstrip("\n"),
                            "curr_ln": j + 1,
                        }
                    )

        return diff_lines

    def rollback(self, job_id, backup_name=None):
        """Restore a job's managed files, serialized with deployments."""
        with self.lock:
            return self._rollback_locked(job_id, backup_name)

    def _rollback_locked(self, job_id, backup_name=None):
        job = self._jobs.get(job_id)
        if not job:
            raise ValueError("job not found")
        if not job.get("backups"):
            raise ValueError("no backups available")
        if backup_name is None:
            backup = job["backups"][-1]
        else:
            backup = next((b for b in job["backups"] if b["name"] == backup_name), None)
        if not backup:
            raise ValueError("backup not found")
        import importlib

        project_root = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
        if project_root not in sys.path:
            sys.path.insert(0, project_root)
        config_module = importlib.reload(importlib.import_module("config"))
        openhab_root, managed = configured_managed_paths(config_module.config, project_root)
        job_root = os.path.realpath(job.get("openhab_root", openhab_root))
        if job_root != openhab_root:
            raise ValueError(
                "OpenHAB path changed since this job; generate a new job before rollback"
            )

        configured_relatives = set(managed.values())
        job_relatives = set(job.get("managed_targets", configured_relatives))
        restore_relatives = configured_relatives.intersection(job_relatives)
        backup_path = backup.get("path")
        if not backup_path or os.path.islink(backup_path):
            raise ValueError("backup path is invalid")
        backup_path = os.path.abspath(backup_path)
        if os.path.commonpath([backup_path, os.path.abspath(self.backups_dir)]) != os.path.abspath(
            self.backups_dir
        ):
            raise ValueError("backup path is outside the configured backup directory")

        restore_managed_files(backup_path, openhab_root, restore_relatives)
        return True, f'restored managed files from {backup["name"]}'

    def deploy(self, job_id):
        """Deploy staged files to live environment."""
        with self.lock:
            return self._deploy_locked(job_id)

    def _deploy_locked(self, job_id):
        job = self._jobs.get(job_id)
        if not job:
            raise ValueError("Job not found")

        if not job.get("staged"):
            raise ValueError("Job is not staged or already deployed")

        mapping = job.get("stage_mapping", {})
        if not mapping:
            raise ValueError("No staged files found")

        import importlib

        project_root = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
        if project_root not in sys.path:
            sys.path.insert(0, project_root)
        config_module = importlib.reload(importlib.import_module("config"))
        openhab_path, managed_paths = configured_managed_paths(config_module.config, project_root)
        output_format = str(config_module.config.get("output_format", "legacy")).casefold()
        if output_format not in {"legacy", "yaml"}:
            raise ValueError("Unsupported output format; select legacy or yaml and generate again")
        if str(job.get("output_format", output_format)).casefold() != output_format:
            raise ValueError("Output format changed since generation; generate a new job before deploy")
        obsolete_keys = (
            ("items_path", "things_path", "sitemaps_path")
            if output_format == "yaml"
            else ("yaml_path",)
        )
        expected_retired = {managed_paths[key] for key in obsolete_keys if key in managed_paths}
        saved_retired = set()
        for value in job.get("retired_paths", expected_retired):
            relative = os.path.relpath(value, openhab_path) if os.path.isabs(value) else value
            saved_retired.add(relative.replace(os.sep, "/"))
        if saved_retired != expected_retired:
            raise ValueError("Retired output list changed; generate a new job before deploy")
        job_root = os.path.realpath(job.get("openhab_root", openhab_path))
        if job_root != openhab_path:
            raise ValueError(
                "OpenHAB path changed since generation; generate a new job before deploy"
            )

        # Keep a full backup for download and recovery. Rollback restores only
        # the managed files listed by the current deployment policy.
        ts = __import__("time").strftime("%Y%m%d-%H%M%S")
        backup_name = f"pre-deploy-{job_id}-{ts}.tar.gz"
        backup_path = os.path.join(self.backups_dir, backup_name)
        try:
            if not os.path.isdir(openhab_path):
                raise ValueError(f"OpenHAB configuration root is missing: {openhab_path}")
            with tarfile.open(backup_path, "w:gz") as tar:
                tar.add(openhab_path, arcname=os.path.basename(openhab_path))
            job["backups"].append({"name": backup_name, "path": backup_path, "ts": ts})
            save_jobs(self.jobs_dir, self._jobs)
        except Exception as e:
            logger.error(f"Failed to create pre-deploy backup: {e}")
            # Proceed? Or abort? Abort is safer.
            raise Exception(f"Backup failed, aborting deploy: {e}")

        deployed_count = 0
        retired_count = 0
        try:
            deployed_count = deploy_staged_files(
                mapping,
                job.get("staging_dir", ""),
                openhab_path,
                managed_paths,
            )

            job["deployed"] = True
            save_jobs(self.jobs_dir, self._jobs)
            if expected_retired:
                try:
                    from knxoh_paths import get_paths

                    if get_paths(project_root).secrets_file is None:
                        retired_count = retire_managed_files(
                            openhab_path, expected_retired, managed_paths
                        )
                    else:
                        result = subprocess.run(
                            [
                                "sudo",
                                "-n",
                                "/usr/local/sbin/knxohui-retire-managed-outputs",
                                output_format,
                            ],
                            check=False,
                            capture_output=True,
                            text=True,
                            timeout=30,
                        )
                        if result.returncode != 0:
                            raise RuntimeError(
                                result.stderr.strip()
                                or "The managed-output retirement helper failed"
                            )
                        retired_count = int(result.stdout.strip() or "0")
                except Exception:
                    job["deployed"] = False
                    save_jobs(self.jobs_dir, self._jobs)
                    raise
            return (
                True,
                f"Deployed {deployed_count} files; retired {retired_count} old model files.",
            )

        except Exception as e:
            logger.error(f"Deploy failed: {e}")
            try:
                restore_managed_files(backup_path, openhab_path, managed_paths.values())
            except Exception as restore_error:
                logger.error(
                    "Failed to restore managed outputs after deploy failure: %s", restore_error
                )
            raise

    def enforce_retention(self):
        """Enforce retention policy: delete backups older than days or trim by count/size."""
        r = self.cfg.get("retention", {})
        days = int(r.get("days", 14))
        max_backups = int(r.get("max_backups", 50))
        max_size_mb = int(r.get("max_backups_size_mb", 500))
        # delete by age
        import time

        now = time.time()
        backups = []
        for fn in os.listdir(self.backups_dir):
            if not fn.endswith(".tar.gz"):
                continue
            fp = os.path.join(self.backups_dir, fn)
            st = os.stat(fp)
            backups.append({"name": fn, "path": fp, "mtime": st.st_mtime, "size": st.st_size})
        # by age
        cutoff = now - days * 86400
        for b in backups:
            if b["mtime"] < cutoff:
                try:
                    os.remove(b["path"])
                except Exception:
                    pass
        # refresh list
        backups = sorted(
            [b for b in backups if os.path.exists(b["path"])], key=lambda x: x["mtime"]
        )
        # trim by count
        while len(backups) > max_backups:
            b = backups.pop(0)
            try:
                os.remove(b["path"])
            except Exception:
                pass
        # trim by size
        total = sum(b["size"] for b in backups)
        max_bytes = max_size_mb * 1024 * 1024
        while total > max_bytes and backups:
            b = backups.pop(0)
            try:
                os.remove(b["path"])
                total -= b["size"]
            except Exception:
                pass

    def status(self):
        running = [j for j in self._jobs.values() if j["status"] == "running"]
        return {"jobs_total": len(self._jobs), "jobs_running": len(running)}

    def update_job(self, job_id, updates):
        """Update job fields (used for persisting logs from frontend)."""
        if job_id not in self._jobs:
            return False
        job = self._jobs[job_id]
        if "log" in updates:
            job["log"] = updates["log"]
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
            # SECURITY: Clear password from memory
            passwords = getattr(self, "_passwords", {})
            passwords.pop(job_id, None)
            self._preview_cache.pop(job_id, None)
            preview_path = os.path.join(self.jobs_dir, job_id, "project-preview.json")
            try:
                os.remove(preview_path)
            except FileNotFoundError:
                pass
            except OSError:
                logger.warning("Failed to remove cached preview for %s", job_id, exc_info=True)
            save_jobs(self.jobs_dir, self._jobs)
        return True
