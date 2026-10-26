import base64
import binascii
import json
import os
import tempfile

from knxoh_paths import get_paths

from .auth import is_password_hash


def load_config(project_root=None):
    paths = get_paths(project_root)
    config = {
        "openhab_path": "openhab",
        "jobs_dir": str(paths.jobs_dir),
        "staging_dir": str(paths.staging_dir),
        "generated_dir": str(paths.generated_dir),
        "backups_dir": str(paths.backup_dir),
        "bind_host": "0.0.0.0",
        "port": 8085,
        "auth": {"enabled": True, "user": "admin"},
        "retention": {"days": 14, "max_backups": 50, "max_backups_size_mb": 500},
        "general": {"auto_place_unknown": False},
    }
    if paths.web_config_file.is_file():
        with paths.web_config_file.open(encoding="utf-8") as config_file:
            stored_config = json.load(config_file)
        if not isinstance(stored_config, dict):
            raise ValueError(f"Web UI configuration must be a JSON object: {paths.web_config_file}")
        config.update(stored_config)

    for key in ("auth", "retention", "general"):
        if not isinstance(config.get(key), dict):
            raise ValueError(f"Web UI configuration field '{key}' must be an object")

    auth = config["auth"]
    legacy_password = auth.pop("password", None)
    if legacy_password is not None:
        auth["legacy_password"] = str(legacy_password)

    for key, fallback in (
        ("jobs_dir", paths.jobs_dir),
        ("staging_dir", paths.staging_dir),
        ("generated_dir", paths.generated_dir),
        ("backups_dir", paths.backup_dir),
    ):
        value = config.get(key, str(fallback))
        value = os.path.expanduser(os.fspath(value))
        if not os.path.isabs(value):
            value = os.path.join(str(paths.project_root), value)
        config[key] = os.path.abspath(value)

    openhab_path = os.path.expanduser(os.fspath(config.get("openhab_path", "openhab")))
    if not os.path.isabs(openhab_path):
        openhab_path = os.path.join(str(paths.project_root), openhab_path)
    config["openhab_path"] = os.path.abspath(openhab_path)

    if paths.secrets_file and paths.secrets_file.is_file():
        password_values = {}
        for line in paths.secrets_file.read_text(encoding="utf-8").splitlines():
            name, separator, value = line.partition("=")
            if separator and name in (
                "KNXOH_UI_PASSWORD_HASH_B64",
                "KNXOH_UI_PASSWORD_B64",
            ):
                password_values[name] = value.strip()
        hash_b64 = password_values.get("KNXOH_UI_PASSWORD_HASH_B64")
        legacy_b64 = password_values.get("KNXOH_UI_PASSWORD_B64")
        if hash_b64:
            try:
                password_hash = base64.b64decode(hash_b64, validate=True).decode("utf-8")
            except (binascii.Error, UnicodeDecodeError) as error:
                raise ValueError("The stored Web UI password hash is invalid") from error
            if not is_password_hash(password_hash):
                raise ValueError("The stored Web UI password hash is invalid")
            auth["password_hash"] = password_hash
            auth.pop("legacy_password", None)
        elif legacy_b64 and "legacy_password" not in auth:
            try:
                auth["legacy_password"] = base64.b64decode(legacy_b64, validate=True).decode(
                    "utf-8"
                )
            except (binascii.Error, UnicodeDecodeError) as error:
                raise ValueError("The stored legacy Web UI password is invalid") from error

    # The browser suite starts the app as a local test server. It must not rely
    # on a production credential stored in the repository or external config.
    if os.environ.get("FLASK_ENV") == "testing":
        auth["enabled"] = False
    return config


def load_generator_config(project_root=None):
    paths = get_paths(project_root)
    with paths.generator_config_file.open(encoding="utf-8") as config_file:
        return json.load(config_file)


def save_generator_config(config, project_root=None):
    paths = get_paths(project_root)
    save_json_atomic(paths.generator_config_file, config)


def save_json_atomic(path, value):
    path = os.fspath(path)
    parent = os.path.dirname(path)
    os.makedirs(parent, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(prefix=".config-", dir=parent, text=True)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as config_file:
            json.dump(value, config_file, indent=2, ensure_ascii=False)
            config_file.write("\n")
            config_file.flush()
            os.fsync(config_file.fileno())
        os.replace(tmp_path, path)
    except Exception:
        try:
            os.unlink(tmp_path)
        except FileNotFoundError:
            pass
        raise


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
