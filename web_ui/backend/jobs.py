import base64
import hashlib
import io
import json
import logging
import os
import queue
import re
import stat as stat_module
import subprocess
import sys
import tarfile
import threading
import traceback
import uuid
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from ipaddress import ip_address
from pathlib import PurePosixPath

from completeness import check_completeness, iter_thing_lines

from . import gateway_config, gateway_undo
from .deploy_policy import (
    configured_managed_paths,
    deploy_staged_files,
    read_managed_file,
    restore_managed_files,
    write_managed_file,
)
from .service_updates import package_version
from .storage import (
    ensure_dirs,
    load_generator_config,
    load_jobs,
    save_generator_config,
    save_jobs,
)
from .things_format import (
    FORMAT_OUTPUT_KEYS,
    assert_no_unmanaged_bridge_definitions,
    validate_yaml_compatibility,
)

logger = logging.getLogger(__name__)

_RETIRABLE_MODEL_SUFFIXES = {
    "items": (".items",),
    "things": (".things",),
    "sitemaps": (".sitemap", ".sitemaps"),
    "yaml": (".yaml", ".yml"),
}
_DIR_FD_RETIREMENT = (
    hasattr(os, "O_NOFOLLOW") and os.open in os.supports_dir_fd and os.stat in os.supports_dir_fd
)


def _validate_retired_model_paths(retired_paths, deployed_targets, openhab_root):
    """Validate old model outputs before deployment can change any live files."""
    root = os.path.abspath(openhab_root)
    deployed = {os.path.normcase(os.path.abspath(path)) for path in deployed_targets}
    targets = []

    for value in retired_paths:
        if not isinstance(value, (str, os.PathLike)):
            raise ValueError("Retired model output must be a filesystem path")
        raw_path = os.fspath(value)
        if not raw_path or "\x00" in raw_path or ".." in raw_path.split(os.sep):
            raise ValueError("Retired model output contains an invalid path")

        target = os.path.abspath(raw_path)
        try:
            common = os.path.commonpath([root, target])
        except ValueError as error:
            raise ValueError("Retired model output must be under the OpenHAB directory") from error
        if os.path.normcase(common) != os.path.normcase(root):
            raise ValueError("Retired model output must be under the OpenHAB directory")

        relative = os.path.relpath(target, root)
        parts = relative.replace("\\", "/").split("/")
        if len(parts) != 2 or parts[0] not in _RETIRABLE_MODEL_SUFFIXES:
            raise ValueError(
                "Only configured model files directly under OpenHAB model folders may retire"
            )
        if not parts[1].lower().endswith(_RETIRABLE_MODEL_SUFFIXES[parts[0]]):
            raise ValueError("Retired model output has an unsupported file extension")
        if os.path.normcase(target) in deployed:
            continue

        if _inspect_retired_model_file(root, relative):
            targets.append(relative)

    return targets


def _inspect_retired_model_file(root, relative):
    """Validate a model file without following symlinks."""
    folder, filename = relative.split(os.sep) if os.sep in relative else relative.split("/")
    if _DIR_FD_RETIREMENT:
        directory_flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | os.O_NOFOLLOW
        root_fd = None
        folder_fd = None
        try:
            root_fd = os.open(root, directory_flags)
            folder_fd = os.open(folder, directory_flags, dir_fd=root_fd)
            try:
                info = os.stat(filename, dir_fd=folder_fd, follow_symlinks=False)
            except FileNotFoundError:
                return False
            if not stat_module.S_ISREG(info.st_mode) or info.st_nlink != 1:
                raise ValueError("Retired model output must be a single-link regular file")
            return True
        except FileNotFoundError:
            return False
        except OSError as error:
            raise ValueError("Retired model output has an unsafe directory or file") from error
        finally:
            if folder_fd is not None:
                os.close(folder_fd)
            if root_fd is not None:
                os.close(root_fd)

    root_info = os.lstat(root)
    folder_path = os.path.join(root, folder)
    folder_info = os.lstat(folder_path)
    if stat_module.S_ISLNK(root_info.st_mode) or not stat_module.S_ISDIR(root_info.st_mode):
        raise ValueError("OpenHAB directory must be a real directory")
    if stat_module.S_ISLNK(folder_info.st_mode) or not stat_module.S_ISDIR(folder_info.st_mode):
        raise ValueError("Retired model output directory must be a real directory")
    target = os.path.join(folder_path, filename)
    try:
        info = os.lstat(target)
    except FileNotFoundError:
        return False
    if not stat_module.S_ISREG(info.st_mode) or info.st_nlink != 1:
        raise ValueError("Retired model output must be a single-link regular file")
    return True


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
        self.operation_lock = threading.Lock()
        self.gateway_state_lock = threading.Lock()

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

    def get_last_deployed_things_format(self):
        """Return the deployed output format normalized for KNX bridge handling."""
        self._reload_jobs()
        deployed_jobs = [job for job in self._jobs.values() if job.get("deployed")]
        if not deployed_jobs:
            return "dsl"
        latest = max(
            deployed_jobs,
            key=lambda job: job.get("deployed_at", job.get("created", 0)),
        )
        output_format = latest.get("output_format", "legacy")
        return "yaml" if output_format == "yaml" else "dsl"

    def get_last_deployed_gateway_source(self):
        """Return reset-source metadata from the latest deployed job, if available."""
        self._reload_jobs()
        deployed_jobs = [job for job in self._jobs.values() if job.get("deployed")]
        if not deployed_jobs:
            return None
        latest = max(
            deployed_jobs,
            key=lambda job: job.get("deployed_at", job.get("created", 0)),
        )
        if "detected_gateway_ip" not in latest:
            return None
        output_format = latest.get("output_format", "legacy")
        if output_format not in {"legacy", "yaml"}:
            return None
        return {
            "job_id": latest["id"],
            "detected_gateway_ip": latest["detected_gateway_ip"],
            "things_format": "dsl" if output_format == "legacy" else "yaml",
        }

    def get_last_deployed_things_target(self):
        """Return the latest deployed, explicitly managed KNX Things target."""
        self._reload_jobs()
        deployed_jobs = [(job_id, job) for job_id, job in self._jobs.items() if job.get("deployed")]
        if not deployed_jobs:
            return None
        latest_key, latest = max(
            deployed_jobs,
            key=lambda entry: entry[1].get("deployed_at", entry[1].get("created", 0)),
        )
        output_format = latest.get("output_format")
        things_format = {"legacy": "dsl", "yaml": "yaml"}.get(output_format)
        openhab_root = latest.get("openhab_root")
        managed_path = latest.get("active_things_path")
        managed_targets = latest.get("managed_targets")
        if (
            output_format not in {"legacy", "yaml"}
            or things_format not in FORMAT_OUTPUT_KEYS
            or not isinstance(openhab_root, str)
            or not openhab_root
            or not isinstance(managed_path, str)
            or not isinstance(managed_targets, list)
            or managed_path not in managed_targets
        ):
            return None
        job_id = latest.get("id") or latest_key
        if not isinstance(job_id, str) or not job_id:
            return None
        deployment_id = latest.get("deployment_id")
        if not isinstance(deployment_id, str) or not deployment_id:
            deployment_id = f"{job_id}:{latest.get('deployed_at', latest.get('created', 0))}"
        return {
            "job_id": job_id,
            "deployment_id": deployment_id,
            "openhab_root": openhab_root,
            "managed_path": managed_path,
            "output_format": output_format,
            "things_format": things_format,
        }

    def _gateway_target_configuration(self, configuration, project_root, target):
        """Build and revalidate a minimal managed-path config for a deployed target."""
        things_format = target["things_format"]
        output_key = FORMAT_OUTPUT_KEYS[things_format]
        openhab_root = target["openhab_root"]
        managed_path = target["managed_path"]
        target_config = {
            "openhab_path": openhab_root,
            "output_format": target["output_format"],
            output_key: os.path.join(openhab_root, *PurePosixPath(managed_path).parts),
            "devices": deepcopy(configuration.get("devices", {})),
        }
        try:
            validated_root, managed_paths = configured_managed_paths(target_config, project_root)
        except (TypeError, ValueError) as error:
            raise ValueError(f"Last deployed KNX Things target is not usable: {error}") from error
        if validated_root != os.path.realpath(os.path.abspath(openhab_root)):
            raise ValueError("Last deployed KNX Things target has an invalid OpenHAB root")
        if managed_paths.get(output_key) != managed_path:
            raise ValueError("Last deployed KNX Things target is outside its managed output path")
        return target_config, validated_root, managed_paths

    def _require_live_format_compatibility(self, things_format: str) -> None:
        """Reject YAML live operations unless a local OpenHAB 5.2+ version is known."""
        if things_format == "dsl":
            return
        if things_format != "yaml":
            raise ValueError(f"Unsupported KNX Things format: {things_format}")
        version_info = package_version("openhab")
        installed = version_info.get("installed") if isinstance(version_info, dict) else None
        version_match = (
            re.match(r"^(\d+)\.(\d+)(?:\.|[-+]|$)", installed)
            if isinstance(installed, str)
            else None
        )
        if version_match is None or (int(version_match.group(1)), int(version_match.group(2))) < (
            5,
            2,
        ):
            detail = (
                f" Installed version: {installed}."
                if installed
                else " Installed version is unknown."
            )
            raise ValueError(f"YAML live changes require OpenHAB 5.2 or newer.{detail}")

    def _gateway_undo_path(self):
        return os.path.join(self.backups_dir, "gateway-live-undo.json")

    def _gateway_undo_available(
        self, target, openhab_root, managed_paths, current_gateway_override
    ):
        try:
            snapshot = gateway_undo.load_snapshot(self._gateway_undo_path())
            if snapshot is None:
                return False
            if (
                snapshot.get("job_id") != target["job_id"]
                or snapshot.get("deployment_id") != target["deployment_id"]
                or snapshot["openhab_root"] != openhab_root
                or snapshot["managed_path"] != target["managed_path"]
                or snapshot["things_format"] != target["things_format"]
            ):
                return False
            if snapshot.get("post_change_gateway_override") != current_gateway_override:
                return False
            current_content = read_managed_file(openhab_root, target["managed_path"], managed_paths)
            return hashlib.sha256(current_content).hexdigest() == snapshot["post_change_sha256"]
        except (OSError, ValueError) as error:
            logger.warning("KNX gateway undo snapshot is unavailable: %s", error)
            return False

    def get_gateway_state(self):
        """Read active managed bridge settings under the narrow live-file lock."""
        with self.gateway_state_lock:
            project_root = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
            configuration = load_generator_config(project_root)
            target = self.get_last_deployed_things_target()
            if target is None:
                raise ValueError("No usable successfully deployed KNX Things target is available")
            state_config, openhab_root, _managed_paths = self._gateway_target_configuration(
                configuration, project_root, target
            )
            state_config["_gateway_reset_available"] = (
                self.get_last_deployed_gateway_source() is not None
            )
            state = gateway_config.read_gateway_state(state_config, project_root)
            state["configured_path"] = os.path.join(
                openhab_root, *PurePosixPath(target["managed_path"]).parts
            )
            devices = configuration.get("devices", {})
            gateway = devices.get("gateway", {}) if isinstance(devices, dict) else {}
            current_override = gateway.get("ip_address", "") if isinstance(gateway, dict) else ""
            current_override = current_override or ""
            if not isinstance(current_override, str):
                raise ValueError("Generator gateway IP override must be a string")
            state["saved_override"] = current_override
            state["undo_available"] = self._gateway_undo_available(
                target, openhab_root, _managed_paths, current_override
            )
            return state

    def _update_live_gateway(self, transform, gateway_ip, gateway_mode, override):
        project_root = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
        original_config = load_generator_config(project_root)
        target = self.get_last_deployed_things_target()
        if target is None:
            raise ValueError("No usable successfully deployed KNX Things target is available")
        state_config, openhab_root, managed_paths = self._gateway_target_configuration(
            original_config, project_root, target
        )
        self._require_live_format_compatibility(target["things_format"])
        state_config["_gateway_reset_available"] = (
            self.get_last_deployed_gateway_source() is not None
        )
        state = gateway_config.read_gateway_state(state_config, project_root)
        relative_path = target["managed_path"]
        if (
            state["managed_path"] != relative_path
            or state["things_format"] != target["things_format"]
        ):
            raise ValueError("Last deployed KNX Things target did not resolve consistently")
        if relative_path not in managed_paths.values():
            raise ValueError("Active KNX Things file is not a managed output")

        old_content = read_managed_file(openhab_root, relative_path, managed_paths)
        try:
            old_text = old_content.decode("utf-8")
        except UnicodeError as error:
            raise ValueError(f"Active KNX Things file is not valid UTF-8: {error}") from error
        new_text = transform(old_text, state["things_format"])
        new_content = new_text.encode("utf-8")

        updated_config = deepcopy(original_config)
        devices = updated_config.setdefault("devices", {})
        if not isinstance(devices, dict):
            raise ValueError("Generator devices configuration must be an object")
        gateway = devices.setdefault("gateway", {})
        if not isinstance(gateway, dict):
            raise ValueError("Generator gateway configuration must be an object")
        previous_override = gateway.get("ip_address", "") or ""
        if not isinstance(previous_override, str):
            raise ValueError("Generator gateway IP override must be a string")
        gateway["ip_address"] = override

        undo_path = self._gateway_undo_path()
        previous_snapshot = gateway_undo.load_snapshot(undo_path)
        new_snapshot = {
            "version": gateway_undo.SNAPSHOT_VERSION,
            "job_id": target["job_id"],
            "deployment_id": target["deployment_id"],
            "file_content_b64": base64.b64encode(old_content).decode("ascii"),
            "previous_gateway_override": previous_override,
            "post_change_gateway_override": override,
            "openhab_root": openhab_root,
            "managed_path": relative_path,
            "things_format": state["things_format"],
            "post_change_sha256": hashlib.sha256(new_content).hexdigest(),
        }
        gateway_undo.save_snapshot(undo_path, new_snapshot)

        try:
            save_generator_config(updated_config, project_root)
            write_managed_file(openhab_root, relative_path, new_content, managed_paths)
        except Exception as update_error:
            restore_errors = []
            try:
                write_managed_file(openhab_root, relative_path, old_content, managed_paths)
            except Exception as restore_error:
                restore_errors.append(f"live file: {restore_error}")
            try:
                save_generator_config(original_config, project_root)
            except Exception as restore_error:
                restore_errors.append(f"generator configuration: {restore_error}")
            try:
                if previous_snapshot is None:
                    gateway_undo.clear_snapshot(undo_path)
                else:
                    gateway_undo.save_snapshot(undo_path, previous_snapshot)
            except Exception as restore_error:
                restore_errors.append(f"undo snapshot: {restore_error}")
            if restore_errors:
                raise RuntimeError(
                    f"Gateway update failed: {update_error}; compensation failed: "
                    + "; ".join(restore_errors)
                ) from update_error
            raise

        return {
            "success": True,
            "things_format": state["things_format"],
            "managed_path": relative_path,
            "gateway_ip": gateway_ip,
            "gateway_mode": gateway_mode,
            "saved_override": override,
            "undo_available": True,
            "message": (
                "KNX gateway configuration file updated; OpenHAB runtime status was not checked."
            ),
        }

    def apply_gateway_ip(self, ip_address_value):
        """Update only the active KNX gateway settings and saved IP override."""
        try:
            normalized_ip = str(ip_address(ip_address_value.strip()))
        except (AttributeError, ValueError) as error:
            raise ValueError(f"Invalid IP address: {ip_address_value}") from error

        with self.operation_lock, self.gateway_state_lock:
            return self._update_live_gateway(
                lambda content, format_name: gateway_config.update_gateway_file(
                    content, format_name, normalized_ip
                ),
                gateway_ip=normalized_ip,
                gateway_mode="TUNNEL",
                override=normalized_ip,
            )

    def restore_gateway_ip(self):
        """Restore the last deployed ETS gateway address or KNX router mode."""
        with self.operation_lock, self.gateway_state_lock:
            source = self.get_last_deployed_gateway_source()
            if source is None:
                raise ValueError("No successfully deployed ETS gateway source is available")
            detected_ip = source["detected_gateway_ip"]
            normalized_ip = str(ip_address(detected_ip)) if detected_ip is not None else None
            return self._update_live_gateway(
                lambda content, format_name: gateway_config.restore_ets_gateway_file(
                    content, format_name, normalized_ip
                ),
                gateway_ip=normalized_ip,
                gateway_mode="TUNNEL" if normalized_ip is not None else "ROUTER",
                override="",
            )

    def undo_gateway_ip(self):
        """Restore the exact prior managed file and override from the last live action."""
        with self.operation_lock, self.gateway_state_lock:
            project_root = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
            original_config = load_generator_config(project_root)
            target = self.get_last_deployed_things_target()
            if target is None:
                raise ValueError("No usable successfully deployed KNX Things target is available")
            _target_config, openhab_root, managed_paths = self._gateway_target_configuration(
                original_config, project_root, target
            )
            self._require_live_format_compatibility(target["things_format"])

            undo_path = self._gateway_undo_path()
            snapshot = gateway_undo.load_snapshot(undo_path)
            if snapshot is None:
                raise ValueError("No live gateway undo snapshot is available")
            if (
                snapshot.get("job_id") != target["job_id"]
                or snapshot.get("deployment_id") != target["deployment_id"]
                or snapshot["openhab_root"] != openhab_root
                or snapshot["managed_path"] != target["managed_path"]
                or snapshot["things_format"] != target["things_format"]
            ):
                raise ValueError("Undo snapshot is stale because the deployed target has changed")

            devices = original_config.get("devices", {})
            gateway = devices.get("gateway", {}) if isinstance(devices, dict) else {}
            current_override = gateway.get("ip_address", "") if isinstance(gateway, dict) else ""
            current_override = current_override or ""
            if not isinstance(current_override, str):
                raise ValueError("Generator gateway IP override must be a string")
            if snapshot.get("post_change_gateway_override") != current_override:
                raise ValueError(
                    "Undo snapshot is stale because the saved gateway override has changed"
                )

            relative_path = target["managed_path"]
            current_content = read_managed_file(openhab_root, relative_path, managed_paths)
            current_digest = hashlib.sha256(current_content).hexdigest()
            if current_digest != snapshot["post_change_sha256"]:
                raise ValueError("Undo snapshot is stale because the managed file has changed")
            previous_content = base64.b64decode(snapshot["file_content_b64"], validate=True)

            updated_config = deepcopy(original_config)
            devices = updated_config.setdefault("devices", {})
            if not isinstance(devices, dict):
                raise ValueError("Generator devices configuration must be an object")
            gateway = devices.setdefault("gateway", {})
            if not isinstance(gateway, dict):
                raise ValueError("Generator gateway configuration must be an object")
            previous_override = snapshot["previous_gateway_override"]
            gateway["ip_address"] = previous_override

            try:
                save_generator_config(updated_config, project_root)
                write_managed_file(openhab_root, relative_path, previous_content, managed_paths)
                gateway_undo.clear_snapshot(undo_path)
            except Exception as update_error:
                restore_errors = []
                try:
                    write_managed_file(openhab_root, relative_path, current_content, managed_paths)
                except Exception as restore_error:
                    restore_errors.append(f"live file: {restore_error}")
                try:
                    save_generator_config(original_config, project_root)
                except Exception as restore_error:
                    restore_errors.append(f"generator configuration: {restore_error}")
                if restore_errors:
                    raise RuntimeError(
                        f"Gateway undo failed: {update_error}; compensation failed: "
                        + "; ".join(restore_errors)
                    ) from update_error
                raise

            return {
                "success": True,
                "things_format": target["things_format"],
                "managed_path": relative_path,
                "gateway_ip": previous_override or None,
                "saved_override": previous_override,
                "undo_available": False,
                "message": ("KNX gateway file restored; OpenHAB runtime status was not checked."),
            }

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
        with self.operation_lock:
            self._run_job_serialized(job_id)

    def _run_job_serialized(self, job_id):
        job = self._jobs[job_id]
        q = self.queues[job_id]
        job["status"] = "running"
        save_jobs(self.jobs_dir, self._jobs)

        # Retrieve password from in-memory store (not from job JSON)
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

            # Resolve the protected output boundary from the freshly reloaded
            # generator config, so the gateway override and deploy paths share it.
            openhab_path, managed_paths = configured_managed_paths(
                global_config_module.config, project_root
            )
            job["openhab_root"] = openhab_path
            job["managed_targets"] = sorted(set(managed_paths.values()))
            output_format = str(
                global_config_module.config.get("output_format", "legacy")
            ).casefold()
            if output_format not in {"legacy", "yaml"}:
                raise ValueError('output_format must be either "legacy" or "yaml"')
            selected_format = "dsl" if output_format == "legacy" else "yaml"
            active_output_key = FORMAT_OUTPUT_KEYS[selected_format]
            if active_output_key not in managed_paths:
                raise ValueError(f"{active_output_key} is required for {output_format} output")
            job["output_format"] = output_format
            job["active_things_path"] = managed_paths[active_output_key]
            previous_format = self.get_last_deployed_things_format()
            if selected_format != previous_format:
                managed_things_relpaths = {
                    managed_paths[key]
                    for key in ("items_path", "things_path", "sitemaps_path", "yaml_path")
                    if key in managed_paths
                }
                assert_no_unmanaged_bridge_definitions(openhab_path, managed_things_relpaths)

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

            # Stage the selected model output and an empty file for the retired format.
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
            retired_paths = [
                os.path.join(openhab_path, *managed_paths[key].split("/"))
                for key in retired_keys
                if key in managed_paths and key in global_config_module.config
            ]
            output_keys = [
                key
                for key in (*model_output_keys, *retired_keys, "influx_path", "fenster_path")
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
                detected_ip = knxmod.detect_gateway_ip(project)
                job["gateway_ip"] = ip
                job["detected_gateway_ip"] = detected_ip
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

                # The service account can write managed files, but cannot unlink
                # entries from OpenHAB directories. An empty staged model file
                # retires the previous format while preserving rollback capability.
                for key in retired_keys:
                    if key in staged_config and key in managed_paths:
                        with open(staged_config[key], "w", encoding="utf-8"):
                            pass

                # Generate completeness report from staged knx.things
                try:
                    report_path = self._write_completeness_report(
                        staged_config.get(FORMAT_OUTPUT_KEYS[selected_format]),
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
            absolute_path = os.path.normpath(os.path.abspath(path))
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
            relative_path = (
                os.path.relpath(absolute_path, abs_openhab_path)
                if in_openhab
                else os.path.basename(absolute_path)
            )
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
        with self.operation_lock:
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
        with self.operation_lock, self.gateway_state_lock:
            with self.lock:
                deployed_jobs = [job for job in self._jobs.values() if job.get("deployed")]
                if deployed_jobs:
                    latest = max(
                        deployed_jobs,
                        key=lambda job: job.get("deployed_at", job.get("created", 0)),
                    )
                    previous_things_format = (
                        "yaml" if latest.get("output_format") == "yaml" else "dsl"
                    )
                else:
                    previous_things_format = "dsl"
            with self.lock:
                return self._deploy_locked(job_id, previous_things_format)

    def _deploy_locked(self, job_id, previous_things_format):
        job = self._jobs.get(job_id)
        if not job:
            raise ValueError("Job not found")

        if not job.get("staged"):
            raise ValueError("Job is not staged or already deployed")

        mapping = job.get("stage_mapping", {})
        if not mapping:
            raise ValueError("No staged files found")

        if job.get("output_format", "legacy") == "yaml":
            version_info = package_version("openhab")
            installed_version = (
                version_info.get("installed") if isinstance(version_info, dict) else None
            )
            compatibility_warning = validate_yaml_compatibility(installed_version)
            if compatibility_warning:
                job["compatibility_warning"] = compatibility_warning
            else:
                job.pop("compatibility_warning", None)

        import importlib

        project_root = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
        if project_root not in sys.path:
            sys.path.insert(0, project_root)
        config_module = importlib.reload(importlib.import_module("config"))
        openhab_path, managed_paths = configured_managed_paths(config_module.config, project_root)
        job_root = os.path.realpath(job.get("openhab_root", openhab_path))
        if job_root != openhab_path:
            raise ValueError(
                "OpenHAB path changed since generation; generate a new job before deploy"
            )

        # Ignore the staged empty files for the old format when checking which
        # model outputs are being actively deployed.
        retired_absolute = {
            os.path.normcase(os.path.abspath(path)) for path in job.get("retired_paths", [])
        }
        deployed_targets = {
            os.path.normcase(os.path.abspath(path))
            for path in mapping.values()
            if isinstance(path, (str, os.PathLike))
            and os.path.normcase(os.path.abspath(path)) not in retired_absolute
        }
        retirement_targets = _validate_retired_model_paths(
            job.get("retired_paths", []), deployed_targets, openhab_path
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
        retired_count = len(retirement_targets)
        try:
            selected_things_format = "yaml" if job.get("output_format") == "yaml" else "dsl"
            if selected_things_format != previous_things_format:
                managed_things_relpaths = {
                    managed_paths[key]
                    for key in ("items_path", "things_path", "sitemaps_path", "yaml_path")
                    if key in managed_paths
                }
                assert_no_unmanaged_bridge_definitions(openhab_path, managed_things_relpaths)

            deployed_count = deploy_staged_files(
                mapping,
                job.get("staging_dir", ""),
                openhab_path,
                managed_paths,
            )

            job["deployed"] = True
            job["deployed_at"] = __import__("time").time()
            job["deployment_id"] = uuid.uuid4().hex
            save_jobs(self.jobs_dir, self._jobs)
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
