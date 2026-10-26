import hashlib
import json
import logging
import os
import sys
import tarfile
import uuid
from typing import Any, Callable
from urllib.parse import urlsplit, urlunsplit

from knxoh_paths import get_paths

try:
    from flask import (
        Flask,
        Response,
        g,
        jsonify,
        make_response,
        redirect,
        render_template,
        request,
        stream_with_context,
        url_for,
    )
    from itsdangerous import BadData, URLSafeTimedSerializer
    from werkzeug.middleware.proxy_fix import ProxyFix
    from werkzeug.utils import secure_filename

    FLASK_AVAILABLE = True
except Exception:
    # allow module import when Flask is not installed (for static analysis/tests)
    Flask: Any = None  # type: ignore[no-redef]
    request: Any = None  # type: ignore[no-redef]
    g: Any = None  # type: ignore[no-redef]
    make_response: Any = None  # type: ignore[no-redef]
    redirect: Any = None  # type: ignore[no-redef]
    url_for: Any = None  # type: ignore[no-redef]
    jsonify: Callable[..., Any] = (  # type: ignore[no-redef]
        lambda *args, **kwargs: args[0] if args else None
    )
    render_template: Callable[..., str] = (  # type: ignore[no-redef]
        lambda n, *args, **kwargs: f"Template {n} not available"
    )
    stream_with_context: Callable[[Any], Any] = lambda g: g  # type: ignore[no-redef]
    Response: Any = object  # type: ignore[no-redef]
    secure_filename: Callable[[str], str] = lambda n: n  # type: ignore[no-redef]
    FLASK_AVAILABLE = False

from .auth import verify_password
from .jobs import JobManager
from .service_manager import get_service_status, restart_service
from .service_updates import PACKAGES, ServiceUpdates, package_version
from .session_store import SESSION_MAX_AGE, SessionStore
from .storage import get_session_secret, load_config, load_generator_config, save_generator_config
from .updater import Updater
from .upload_security import (
    MAX_UPLOAD_SIZE_BYTES,
    get_zip_validation_options,
    validate_upload_from_path,
)

logger = logging.getLogger(__name__)

cfg = load_config()


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


if FLASK_AVAILABLE:
    app = Flask(
        __name__,
        template_folder=os.path.join(os.path.dirname(__file__), "..", "templates"),
        static_folder=os.path.join(os.path.dirname(__file__), "..", "static"),
        static_url_path="/static",
    )
    trusted_proxy_hops = int(cfg.get("trusted_proxy_hops", 0))
    if trusted_proxy_hops < 0 or trusted_proxy_hops > 5:
        raise ValueError("trusted_proxy_hops must be between 0 and 5")
    if trusted_proxy_hops:
        app.wsgi_app = ProxyFix(  # type: ignore[method-assign]
            app.wsgi_app,
            x_for=trusted_proxy_hops,
            x_proto=trusted_proxy_hops,
            x_host=trusted_proxy_hops,
        )
    app.config["UPLOAD_FOLDER"] = cfg.get("jobs_dir", "./var/lib/knx_to_openhab")
    app.config["MAX_CONTENT_LENGTH"] = cfg.get("max_upload_size_bytes", MAX_UPLOAD_SIZE_BYTES)

    @app.errorhandler(413)
    def request_too_large(_error):
        limit = app.config.get("MAX_CONTENT_LENGTH", MAX_UPLOAD_SIZE_BYTES)
        return jsonify({"error": f"Upload exceeds the maximum allowed size ({limit} bytes)"}), 413

    # Fix openhab_path to be absolute if it's relative and based on project root

    project_root = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
    if "openhab_path" in cfg:
        openhab_path = cfg["openhab_path"]
        # If openhab_path is relative (doesn't start with / on Unix or a drive letter on Windows),
        # make it relative to project root
        if not os.path.isabs(openhab_path):
            cfg["openhab_path"] = os.path.join(project_root, openhab_path)

    job_mgr = JobManager(cfg)
    # Use project root directory as base path for updater
    updater = Updater(base_path=project_root)
    service_updates = ServiceUpdates()

    # Durable session and CSRF handling -------------------------------------------
    import hmac
    import secrets

    _session_store: SessionStore | None = None
    session_max_age = max(
        300, min(int(cfg.get("session_max_age_seconds", SESSION_MAX_AGE)), 604800)
    )

    def _sessions() -> SessionStore:
        global _session_store
        if _session_store is None:
            _session_store = SessionStore(cfg["sessions_file"], get_session_secret(project_root))
        return _session_store

    def _credential_version() -> str:
        auth_config = cfg.get("auth", {})
        password_hash = auth_config.get("password_hash")
        if password_hash:
            credential = [str(auth_config.get("user", "")), "hash", str(password_hash)]
        else:
            credential = [
                str(auth_config.get("user", "")),
                "legacy",
                str(auth_config.get("legacy_password", "")),
            ]
        payload = json.dumps(
            [bool(auth_config.get("enabled")), *credential],
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
        return hmac.new(
            get_session_secret(project_root), b"credential-version:" + payload, hashlib.sha256
        ).hexdigest()

    def _login_csrf_serializer() -> URLSafeTimedSerializer:
        return URLSafeTimedSerializer(get_session_secret(project_root), salt="knx-login-csrf")

    def _render_login(error: str | None = None, status: int = 200):
        token = _login_csrf_serializer().dumps(secrets.token_urlsafe(32))
        response = make_response(
            render_template(
                "login.html",
                csrf_token=token,
                error=error,
                next_url=request.args.get("next", "/"),
            ),
            status,
        )
        response.set_cookie(
            "knx_login_csrf",
            token,
            max_age=600,
            httponly=False,
            secure=request.is_secure,
            samesite="Lax",
            path="/",
        )
        return response

    def _valid_login_csrf() -> bool:
        cookie_token = request.cookies.get("knx_login_csrf", "")
        form_token = request.form.get("csrf_token", "")
        if not cookie_token or not form_token or not hmac.compare_digest(cookie_token, form_token):
            return False
        try:
            _login_csrf_serializer().loads(form_token, max_age=600)
        except BadData:
            return False
        return True

    def _safe_redirect_target(value: str | None) -> str:
        if not value or not value.startswith("/") or "\\" in value:
            return "/"
        try:
            parsed = urlsplit(value)
        except ValueError:
            return "/"
        if parsed.scheme or parsed.netloc or parsed.path.startswith("//"):
            return "/"
        return urlunsplit(("", "", parsed.path, parsed.query, parsed.fragment))

    def _verify_login(username: str, password: str) -> bool:
        acfg = cfg.get("auth", {})
        password_hash = acfg.get("password_hash")
        legacy_password = acfg.get("legacy_password")
        user_matches = hmac.compare_digest(
            str(acfg.get("user", "")).encode("utf-8"), username.encode("utf-8")
        )
        if password_hash:
            password_matches = verify_password(password_hash, password)
        elif isinstance(legacy_password, str):
            password_matches = hmac.compare_digest(
                legacy_password.encode("utf-8"), password.encode("utf-8")
            )
        else:
            password_matches = False
        return user_matches and password_matches

    @app.before_request
    def require_auth():
        acfg = cfg.get("auth", {})
        if not acfg.get("enabled"):
            return None
        path = request.path or ""
        if path.startswith("/static"):
            return None
        if path in ("/api/status", "/login"):
            return None
        if not acfg.get("password_hash") and not acfg.get("legacy_password"):
            return (
                "Web UI credentials are not configured. Run installer/setup.sh as an administrator.",
                503,
            )

        session_token = request.cookies.get("knx_session", "")
        session = (
            _sessions().get(session_token, credential_version=_credential_version())
            if session_token
            else None
        )
        if session is None:
            if path.startswith("/api/"):
                return jsonify({"error": "authentication required"}), 401
            return redirect(url_for("login", next=request.full_path))

        g.authenticated_user = session.username
        g.session_token = session_token
        if request.method not in ("GET", "HEAD", "OPTIONS"):
            csrf_cookie = request.cookies.get("knx_csrf", "")
            csrf_header = request.headers.get("X-CSRF-Token", "")
            if not csrf_header:
                csrf_header = request.form.get("csrf_token", "")
            if (
                not csrf_cookie
                or not csrf_header
                or not hmac.compare_digest(csrf_cookie, csrf_header)
                or not _sessions().verify_csrf(session_token, csrf_header)
            ):
                return jsonify({"error": "valid CSRF token required"}), 403
        return None

    @app.route("/login", methods=["GET", "POST"])
    def login():
        acfg = cfg.get("auth", {})
        if not acfg.get("enabled"):
            return redirect("/")
        if not acfg.get("password_hash") and not acfg.get("legacy_password"):
            return (
                "Web UI credentials are not configured. Run installer/setup.sh as an administrator.",
                503,
            )
        if request.method == "GET":
            session_token = request.cookies.get("knx_session", "")
            if session_token and _sessions().get(
                session_token, credential_version=_credential_version()
            ):
                return redirect("/")
            return _render_login()

        if not _valid_login_csrf():
            return _render_login("The sign-in request expired. Please try again.", 400)

        identity = request.remote_addr or "unknown"
        session_store = _sessions()
        if not session_store.is_login_allowed(identity):
            return _render_login("Too many attempts. Please try again later.", 429)
        username = request.form.get("username", "")
        password = request.form.get("password", "")
        if not _verify_login(username, password):
            session_store.record_login_failure(identity)
            return _render_login("Username or password is incorrect.", 401)

        session_store.clear_login_failures(identity)
        token, csrf_token = session_store.create(
            username,
            max_age=session_max_age,
            credential_version=_credential_version(),
        )
        response = make_response(redirect(_safe_redirect_target(request.args.get("next"))))
        response.set_cookie(
            "knx_session",
            token,
            max_age=session_max_age,
            httponly=True,
            secure=request.is_secure,
            samesite="Lax",
            path="/",
        )
        response.set_cookie(
            "knx_csrf",
            csrf_token,
            max_age=session_max_age,
            httponly=False,
            secure=request.is_secure,
            samesite="Lax",
            path="/",
        )
        response.delete_cookie("knx_login_csrf", path="/", samesite="Lax")
        return response

    @app.route("/api/logout", methods=["POST"])
    def logout():
        session_token = request.cookies.get("knx_session", "")
        if session_token:
            _sessions().revoke(session_token)
        response = jsonify({"ok": True})
        response.delete_cookie(
            "knx_session", path="/", httponly=True, secure=request.is_secure, samesite="Lax"
        )
        response.delete_cookie(
            "knx_csrf", path="/", httponly=False, secure=request.is_secure, samesite="Lax"
        )
        return response

    @app.route("/")
    def index():
        return render_template(
            "index.html",
            csrf_token=request.cookies.get("knx_csrf", ""),
            auth_enabled=cfg.get("auth", {}).get("enabled", False),
        )

    @app.route("/api/upload", methods=["POST"])
    def upload():
        if "file" not in request.files:
            return jsonify({"error": "no file part"}), 400
        f = request.files["file"]
        if f.filename == "":
            return jsonify({"error": "no selected file"}), 400

        fn = secure_filename(f.filename)
        password = request.form.get("password") or None
        os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)
        upload_id = uuid.uuid4().hex
        temp_path = os.path.join(app.config["UPLOAD_FOLDER"], f".upload-{upload_id}-{fn}")
        saved_path = os.path.join(app.config["UPLOAD_FOLDER"], f"{upload_id}-{fn}")
        try:
            # Werkzeug's FileStorage streams to disk; do not materialize the
            # full upload (or a second copy for ZIP inspection) in process RAM.
            f.save(temp_path)
            result = validate_upload_from_path(
                temp_path,
                max_size=app.config["MAX_CONTENT_LENGTH"],
                **get_zip_validation_options(cfg.get("security", {})),
                password=password,
            )
            if not result.valid:
                logger.warning("Upload rejected: %s (file: %s)", result.error_message, fn)
                return jsonify({"error": result.error_message}), 400

            os.replace(temp_path, saved_path)
            job = job_mgr.create_job(saved_path, original_name=fn, password=password)
            saved_path = ""
            return jsonify(job), 201
        except OSError as e:
            logger.error("Failed to save or validate uploaded file: %s", e)
            return jsonify({"error": "Failed to save uploaded file"}), 500
        except Exception:
            logger.exception("Failed to create processing job for uploaded file")
            return jsonify({"error": "Failed to create processing job"}), 500
        finally:
            for path in (temp_path, saved_path):
                if path and os.path.exists(path):
                    try:
                        os.remove(path)
                    except OSError as e:
                        logger.warning("Failed to remove temporary upload %s: %s", path, e)

    @app.route("/api/jobs", methods=["GET"])
    def jobs():
        return jsonify(job_mgr.list_jobs())

    @app.route("/api/job/<job_id>", methods=["GET"])
    def job_detail(job_id):
        j = job_mgr.get_job(job_id)
        if not j:
            return jsonify({"error": "not found"}), 404
        return jsonify(j)

    @app.route("/api/job/<job_id>/diff", methods=["GET"])
    def job_diff(job_id):
        job = job_mgr.get_job(job_id)
        if not job:
            return jsonify({"error": "not found"}), 404
        stats = job.get("stats", {}) or {}
        if not stats:
            return jsonify({"error": "no stats available"}), 400
        diffs = {
            rel_path: job_mgr.get_file_diff(job_id, rel_path) or [] for rel_path in stats.keys()
        }
        return jsonify(diffs)

    @app.route("/api/job/<job_id>", methods=["PATCH"])
    def update_job(job_id):
        data = request.get_json() or {}
        try:
            ok = job_mgr.update_job(job_id, data)
            if ok:
                return jsonify({"ok": True})
            else:
                return jsonify({"error": "not found"}), 404
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    @app.route("/api/job/<job_id>/rerun", methods=["POST"])
    def rerun_job(job_id):
        """Create a new job based on an existing job's input.

        Note: Passwords are not stored for security reasons.
        For password-protected projects, the user must re-upload with the password.
        """
        job = job_mgr.get_job(job_id)
        if not job:
            return jsonify({"error": "job not found"}), 404

        input_path = job.get("input")
        if not input_path or not os.path.exists(input_path):
            return jsonify({"error": "original input file not found"}), 404

        try:
            # SECURITY: Password is not stored - user must re-enter if needed
            new_job = job_mgr.create_job(input_path, original_name=job.get("name"), password=None)
            return jsonify(new_job), 201
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    @app.route("/api/job/<job_id>/file/diff", methods=["GET"])
    def job_file_diff(job_id):
        path = request.args.get("path")
        if not path:
            return jsonify({"error": "path required"}), 400

        # path is like "items/knx.items" (relative to openhab root)
        # normalize path
        path = path.replace("\\", "/")
        if path.startswith("openhab/"):
            path = path[8:]

        diff = job_mgr.get_file_diff(job_id, path)
        if diff is None:
            return jsonify({"error": "diff not available"}), 404
        return jsonify(diff)

    @app.route("/api/job/<job_id>/events")
    def job_events(job_id):
        # Wait briefly for the queue to be available (handles race condition)
        timeout = 5  # seconds
        import time

        start_time = time.time()

        while time.time() - start_time < timeout:
            q = job_mgr.get_queue(job_id)
            if q is not None:
                break
            time.sleep(0.1)  # Brief pause before checking again
        else:
            # After timeout, check one final time
            q = job_mgr.get_queue(job_id)
            if q is None:
                return jsonify({"error": "job not found or not ready"}), 404

        def event_stream():
            while True:
                msg = q.get()
                if msg is None:
                    yield "event: done\ndata: {}\n\n".format(json.dumps({"status": "done"}))
                    break
                yield "data: {}\n\n".format(json.dumps(msg))

        return Response(stream_with_context(event_stream()), mimetype="text/event-stream")

    @app.route("/api/job/<job_id>/rollback", methods=["POST"])
    def rollback(job_id):
        data = request.get_json() or {}
        backup = data.get("backup")
        try:
            ok, out = job_mgr.rollback(job_id, backup)
            return jsonify({"ok": ok, "output": out})
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    @app.route("/api/job/<job_id>", methods=["DELETE"])
    def delete_job(job_id):
        try:
            ok = job_mgr.delete_job(job_id)
            return jsonify({"ok": ok})
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    @app.route("/api/service/restart", methods=["POST"])
    def service_restart():
        data = request.get_json() or {}
        svc = data.get("service")
        if not svc:
            return jsonify({"error": "service missing"}), 400
        ok, out = restart_service(svc)
        return jsonify({"ok": ok, "output": out})

    @app.route("/api/service/<service_name>/status", methods=["GET"])
    def service_status(service_name):
        status = get_service_status(service_name)
        return jsonify(status)

    @app.route("/api/service/<package>/version", methods=["GET"])
    def service_version(package):
        if package not in PACKAGES:
            return jsonify({"error": "Unsupported service"}), 404
        return jsonify(package_version(package))

    @app.route("/api/service/updates/status", methods=["GET"])
    def service_update_status():
        return jsonify(service_updates.status())

    @app.route("/api/service/updates/<action>", methods=["POST"])
    def service_update_start(action):
        if action not in (*PACKAGES, "refresh"):
            return jsonify({"error": "Unsupported action"}), 404
        # Package installation grants system privileges; require a non-default password hash.
        acfg = cfg.get("auth", {})
        password_hash = acfg.get("password_hash")
        if (
            not acfg.get("enabled")
            or not isinstance(password_hash, str)
            or verify_password(password_hash, "logihome")
        ):
            return (
                jsonify({"error": "Set a personal Web UI password before using package updates."}),
                403,
            )
        if request.headers.get("X-Requested-With") != "XMLHttpRequest":
            return jsonify({"error": "Missing request header"}), 403
        data = request.get_json(silent=True) or {}
        ok, message = service_updates.start(action, data.get("version"))
        return jsonify({"ok": ok, "message": message}), 202 if ok else 409

    @app.route("/api/status")
    def status():
        s = job_mgr.status()
        s["auto_place_unknown"] = cfg.get("general", {}).get("auto_place_unknown", False)
        s["status"] = "ok"
        return jsonify(s)

    @app.route("/api/debug/stats", methods=["GET"])
    def debug_stats():
        """Debug endpoint to check stats generation for the latest job."""
        import json
        import os

        # Get the latest completed job
        all_jobs = job_mgr._jobs
        completed_jobs = [job for job in all_jobs.values() if job.get("status") == "completed"]
        if not completed_jobs:
            return jsonify({"error": "No completed jobs found"})

        latest_job = max(completed_jobs, key=lambda j: j.get("created", 0))
        job_id = latest_job["id"]

        # Check configured paths
        project_root = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
        main_config_path = get_paths(project_root).generator_config_file

        if main_config_path.exists():
            with open(main_config_path, "r", encoding="utf-8") as f:
                main_config = json.load(f)
        else:
            # Fallback to defaults
            main_config = {
                "items_path": "openhab/items/knx.items",
                "things_path": "openhab/things/knx.things",
                "sitemaps_path": "openhab/sitemaps/knx.sitemap",
                "influx_path": "openhab/persistence/influxdb.persist",
                "fenster_path": "openhab/rules/fenster.rules",
            }

        # Check actual file locations
        openhab_path = job_mgr.cfg.get("openhab_path", "openhab")
        expected_paths = [
            main_config.get("items_path", "openhab/items/knx.items"),
            main_config.get("things_path", "openhab/things/knx.things"),
            main_config.get("sitemaps_path", "openhab/sitemaps/knx.sitemap"),
            main_config.get("influx_path", "openhab/persistence/influxdb.persist"),
            main_config.get("fenster_path", "openhab/rules/fenster.rules"),
        ]

        # Build full paths
        actual_paths = []
        for config_path in expected_paths:
            if os.path.isabs(config_path):
                full_path = config_path
            else:
                full_path = os.path.join(openhab_path, config_path)
                if not os.path.exists(full_path):
                    full_path = config_path  # Try as-is
            actual_paths.append(
                {
                    "config_path": config_path,
                    "full_path": full_path,
                    "exists": os.path.exists(full_path),
                    "size": (os.path.getsize(full_path) if os.path.exists(full_path) else 0),
                }
            )

        # Also scan the entire openhab directory for generated files
        generated_files = []
        if os.path.exists(openhab_path):
            for root, dirs, files in os.walk(openhab_path):
                for file in files:
                    if file.endswith(
                        (
                            ".items",
                            ".things",
                            ".sitemap",
                            ".rules",
                            ".persist",
                            ".script",
                            ".transform",
                        )
                    ):
                        full_path = os.path.join(root, file)
                        rel_path = os.path.relpath(full_path, openhab_path)
                        generated_files.append(
                            {
                                "path": rel_path,
                                "full_path": full_path,
                                "size": os.path.getsize(full_path),
                            }
                        )

        return jsonify(
            {
                "job_id": job_id,
                "openhab_path": openhab_path,
                "configured_paths": actual_paths,
                "generated_files": generated_files,
                "job_stats": latest_job.get("stats", {}),
            }
        )

    @app.route("/api/debug/config", methods=["GET"])
    def debug_config():
        """Debug endpoint to check the current configuration."""
        import os

        # Get the main config (from the main config.json)
        project_root = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
        main_config_path = get_paths(project_root).generator_config_file

        main_config = {}
        if main_config_path.exists():
            with open(main_config_path, "r", encoding="utf-8") as f:
                main_config = json.load(f)

        # Return both main config and backend config
        return jsonify(
            {
                "backend_config": {
                    "openhab_path": job_mgr.cfg.get("openhab_path", "openhab"),
                    "jobs_dir": job_mgr.cfg.get("jobs_dir", "./var/lib/knx_to_openhab"),
                    "backups_dir": job_mgr.cfg.get("backups_dir", "./var/backups/knx_to_openhab"),
                    "retention": job_mgr.cfg.get("retention", {}),
                },
                "main_config_paths": {
                    "items_path": main_config.get("items_path", "openhab/items/knx.items"),
                    "things_path": main_config.get("things_path", "openhab/things/knx.things"),
                    "sitemaps_path": main_config.get(
                        "sitemaps_path", "openhab/sitemaps/knx.sitemap"
                    ),
                    "influx_path": main_config.get(
                        "influx_path", "openhab/persistence/influxdb.persist"
                    ),
                    "fenster_path": main_config.get("fenster_path", "openhab/rules/fenster.rules"),
                },
                "project_root": project_root,
                "main_config_exists": main_config_path.exists(),
            }
        )

    @app.route("/api/version", methods=["GET"])
    def get_version():
        """Get current version information."""
        try:
            version_info = updater.get_current_version()
            return jsonify(version_info)
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    @app.route("/api/version/check", methods=["GET"])
    def check_version():
        """Check for available updates from GitHub."""
        try:
            update_info = updater.check_for_updates()
            return jsonify(update_info)
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    @app.route("/api/version/update", methods=["POST"])
    def trigger_update():
        """Trigger the self-update process."""
        acfg = cfg.get("auth", {})
        if acfg.get("enabled") and not acfg.get("password_hash"):
            return (
                jsonify(
                    {
                        "error": (
                            "A migrated Web UI password hash is required before updating. "
                            f"Run 'sudo bash {project_root}/installer/setup.sh' as an administrator."
                        )
                    }
                ),
                409,
            )
        try:
            # Check if running on Windows (dev) or Linux (prod)
            if sys.platform == "win32":
                return jsonify(
                    {
                        "status": "simulated",
                        "message": "Update simulation: Script would run on Linux.",
                    }
                )

            success, message = updater.trigger_update()
            if success:
                return jsonify({"status": "updating", "message": message})
            else:
                return jsonify({"error": message}), 500
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    @app.route("/api/version/log", methods=["GET"])
    def get_update_log():
        """Get the log of the last update attempt."""
        return jsonify({"log": updater.get_update_log()})

    @app.route("/api/file/preview", methods=["GET"])
    def file_preview():
        """Preview a generated OpenHAB configuration file."""
        file_path = request.args.get("path", "")
        backup_name = request.args.get("backup", None)  # Optional: fetch from backup
        job_id = request.args.get("job_id", None)  # Optional: fetch from job staging

        if not file_path:
            return jsonify({"error": "path parameter required"}), 400

        # Security: Allow files within openhab directory OR jobs directory
        openhab_base = os.path.normpath(os.path.abspath(cfg.get("openhab_path", "openhab")))
        jobs_base = os.path.normpath(os.path.abspath(cfg.get("jobs_dir", "jobs")))
        requested_path = os.path.normpath(os.path.abspath(file_path))

        # Check if requested path is safe (within allowed directories)
        # Use os.path.commonpath to prevent prefix-based bypasses
        def _is_path_under(path: str, base: str) -> bool:
            """Check if path is safely under base directory."""
            try:
                return os.path.commonpath([path, base]) == base
            except ValueError:
                return False

        is_safe = _is_path_under(requested_path, openhab_base) or _is_path_under(
            requested_path, jobs_base
        )

        # Enhanced security: If job_id is provided, whitelist paths from job stats
        if not is_safe and job_id:
            job = job_mgr.get_job(job_id)
            if job and "stats" in job:
                for stat in job["stats"].values():
                    # Check both staged and real paths
                    staged = stat.get("staged_path")
                    real = stat.get("real_path")
                    if staged and os.path.normpath(os.path.abspath(staged)) == requested_path:
                        is_safe = True
                        break
                    if real and os.path.normpath(os.path.abspath(real)) == requested_path:
                        is_safe = True
                        break

        if not is_safe:
            return (
                jsonify({"error": "access denied: path outside allowed directories"}),
                403,
            )

        # If job_id specified, check staged files
        if job_id:
            job = job_mgr.get_job(job_id)
            if job:
                rel_path = os.path.relpath(requested_path, openhab_base).replace("\\", "/")
                staged_path = None

                # 1. Try to get from stats (new jobs)
                if "stats" in job and rel_path in job["stats"]:
                    staged_path = job["stats"][rel_path].get("staged_path")

                # 2. Fallback: construct from staging_dir (supports older jobs on remote)
                if (not staged_path or not os.path.exists(staged_path)) and "staging_dir" in job:
                    staged_path = os.path.join(job["staging_dir"], "openhab", rel_path)

                if staged_path and os.path.isfile(staged_path):
                    try:
                        with open(staged_path, "r", encoding="utf-8", errors="replace") as f:
                            content = f.read()

                        if len(content) > 1024 * 1024:
                            content = (
                                content[: 1024 * 1024]
                                + "\n\n... [Content truncated, file too large]"
                            )

                        return jsonify(
                            {
                                "path": file_path,
                                "content": content,
                                "size": os.path.getsize(staged_path),
                                "from_staged": True,
                                "job_id": job_id,
                            }
                        )
                    except Exception as e:
                        return (
                            jsonify({"error": f"failed to read staged file: {str(e)}"}),
                            500,
                        )
            # If job not found or file not in staged, fall back to current/backup logic

        # If backup specified, extract file from backup
        if backup_name:
            # Use the configured backup directory from config, with a sensible default
            project_root = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
            backups_dir_config = cfg.get("backups_dir", "var/backups/knx_to_openhab")
            if not os.path.isabs(backups_dir_config):
                backups_dir = os.path.join(project_root, backups_dir_config)
            else:
                backups_dir = backups_dir_config
            backup_path = os.path.join(backups_dir, backup_name)

            if not os.path.isfile(backup_path):
                return jsonify({"error": "backup not found"}), 404

            try:
                # Get relative path within openhab directory
                rel_path = os.path.relpath(requested_path, openhab_base)
                # Normalize to forward slashes for tarfile
                rel_path = rel_path.replace("\\", "/")

                # Extract file from backup
                with tarfile.open(backup_path, "r:gz") as tar:
                    # Backup contains directory named 'openhab', so prepend it
                    member_path = f"openhab/{rel_path}"
                    try:
                        # Validate member path to prevent path traversal
                        normalized_member = os.path.normpath(member_path)
                        if ".." in normalized_member.split(os.sep) or os.path.isabs(member_path):
                            return jsonify({"error": "invalid path in backup"}), 400

                        member = tar.getmember(member_path)
                        f = tar.extractfile(member)
                        if f:
                            content = f.read().decode("utf-8", errors="replace")
                            # Limit content size
                            if len(content) > 1024 * 1024:
                                content = (
                                    content[: 1024 * 1024]
                                    + "\n\n... [Content truncated, file too large]"
                                )
                            return jsonify(
                                {
                                    "path": file_path,
                                    "content": content,
                                    "size": member.size,
                                    "from_backup": True,
                                }
                            )
                        else:
                            return jsonify({"error": "file not found in backup"}), 404
                    except KeyError:
                        return jsonify({"error": "file not found in backup"}), 404
            except Exception as e:
                return (
                    jsonify({"error": f"failed to read file from backup: {str(e)}"}),
                    500,
                )

        # Otherwise, read current file
        if not os.path.isfile(requested_path):
            return jsonify({"error": "file not found"}), 404

        # Read file content
        try:
            with open(requested_path, "r", encoding="utf-8", errors="replace") as f:
                content = f.read()

            # Limit content size to prevent memory issues (max 1MB)
            if len(content) > 1024 * 1024:
                content = content[: 1024 * 1024] + "\n\n... [Content truncated, file too large]"

            return jsonify(
                {
                    "path": file_path,
                    "content": content,
                    "size": os.path.getsize(requested_path),
                    "from_backup": False,
                }
            )
        except Exception as e:
            return jsonify({"error": f"failed to read file: {str(e)}"}), 500

    @app.route("/api/config", methods=["GET"])
    def get_config():
        """Get the current configuration."""
        try:
            # Load the main config.json file which contains knxproject_to_openhab settings
            main_config = load_generator_config(project_root)
            return jsonify(main_config)
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    @app.route("/api/config", methods=["POST"])
    def set_config():
        """Update the configuration."""
        try:
            new_config = request.get_json()
            if not new_config:
                return jsonify({"error": "No config data provided"}), 400

            # Validate that it's a dict
            if not isinstance(new_config, dict):
                return jsonify({"error": "Config must be a JSON object"}), 400

            # Save to the main config file (which contains knxproject_to_openhab settings)
            save_generator_config(new_config, project_root)

            return jsonify({"message": "Configuration updated successfully"})
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    @app.route("/api/config/schema", methods=["GET"])
    def get_config_schema():
        """Get the configuration schema."""
        try:
            schema_path = os.path.join(os.path.dirname(__file__), "config_schema.json")
            with open(schema_path, "r", encoding="utf-8") as f:
                schema = json.load(f)
            return jsonify(schema)
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    @app.route("/api/project/preview", methods=["POST"])
    def project_preview():
        """Preview a KNX project structure without processing it."""
        if "file" not in request.files:
            return jsonify({"error": "no file part"}), 400
        f = request.files["file"]
        if f.filename == "":
            return jsonify({"error": "no selected file"}), 400

        fn = secure_filename(f.filename)
        password = request.form.get("password") or None
        temp_path = os.path.join(app.config["UPLOAD_FOLDER"], f"temp_{uuid.uuid4().hex}_{fn}")
        try:
            # Save to Werkzeug's spooled stream target, then inspect the file
            # on disk so large projects are not copied into process RAM.
            f.save(temp_path)
            result = validate_upload_from_path(
                temp_path,
                max_size=app.config["MAX_CONTENT_LENGTH"],
                **get_zip_validation_options(cfg.get("security", {})),
                password=password,
            )
            if not result.valid:
                return jsonify({"error": result.error_message}), 400

            # Load project (json dump or parse knxproj)
            if temp_path.lower().endswith(".json"):
                with open(temp_path, "r", encoding="utf8") as file:
                    project = json.load(file)
            else:
                # Parse knxproj archive using XKNXProj
                from xknxproject.xknxproj import XKNXProj

                knxproj = XKNXProj(path=temp_path, password=password, language="de-DE")
                project = knxproj.parse()

            # Extract project metadata
            import importlib

            knxmod = importlib.import_module("knxproject_to_openhab")

            # Get building structure
            building = knxmod.create_building(project)
            addresses = knxmod.get_addresses(project)
            house = knxmod.put_addresses_in_building(building, addresses, project)

            # Extract metadata
            project_name = house[0].get("name_long") if house else None
            gateway_ip = knxmod.get_gateway_ip(project)
            homekit_enabled = knxmod.is_homekit_enabled(project)
            alexa_enabled = knxmod.is_alexa_enabled(project)

            # Detect unknown items (addresses without proper room/floor assignments or with default names)
            unknown_items = []
            for addr in addresses:
                floor_name = addr.get("Floor", "").strip()
                room_name = addr.get("Room", "").strip()

                # Check if floor or room is unknown/empty
                if (
                    (not floor_name or floor_name.upper() in ["UNKNOWN", "UNBEKANNT"])
                    or (not room_name or room_name.upper() in ["UNKNOWN", "UNBEKANNT"])
                    or (not floor_name and not room_name)
                ):  # Items without both floor and room
                    unknown_items.append(
                        {
                            "name": addr.get("Group name", "Unknown Address"),
                            "address": addr.get("Address", "N/A"),
                            "floor": floor_name or "None",
                            "room": room_name or "None",
                        }
                    )

            # Build preview structure
            preview_data = {
                "metadata": {
                    "project_name": project_name,
                    "gateway_ip": gateway_ip,
                    "homekit_enabled": homekit_enabled,
                    "alexa_enabled": alexa_enabled,
                    "total_addresses": len(addresses),
                    "unknown_items": unknown_items,
                },
                "buildings": [],
            }

            if house:
                for building_data in house:
                    building_info = {
                        "name": building_data.get(
                            "Description",
                            building_data.get("Group name", "Unknown Building"),
                        ),
                        "description": building_data.get("name_long", ""),
                        "floors": [],
                    }

                    for floor_data in building_data.get("floors", []):
                        floor_info = {
                            "name": floor_data.get(
                                "Description",
                                floor_data.get("Group name", "Unknown Floor"),
                            ),
                            "description": floor_data.get("name_long", ""),
                            "rooms": [],
                        }

                        for room_data in floor_data.get("rooms", []):
                            # Format addresses to ensure they have the required fields
                            raw_addresses = room_data.get("Addresses", [])
                            formatted_addresses = []
                            for addr in raw_addresses:
                                formatted_addr = {
                                    "Group name": addr.get(
                                        "Group name",
                                        addr.get("name", "Unknown Address"),
                                    ),
                                    "Address": addr.get("Address", addr.get("address", "N/A")),
                                }
                                formatted_addresses.append(formatted_addr)

                            room_info = {
                                "name": room_data.get(
                                    "Description",
                                    room_data.get("Group name", "Unknown Room"),
                                ),
                                "description": room_data.get("name_long", ""),
                                "address_count": len(formatted_addresses),
                                "device_count": len(room_data.get("devices", [])),
                                "addresses": formatted_addresses,
                            }
                            floor_info["rooms"].append(room_info)

                        building_info["floors"].append(floor_info)

                    preview_data["buildings"].append(building_info)

            return jsonify(preview_data)

        except Exception as e:
            friendly_msg = _password_error_message(e)
            if friendly_msg:
                return jsonify({"error": friendly_msg}), 400
            return jsonify({"error": str(e)}), 500
        finally:
            # Clean up temp file safely
            try:
                if os.path.exists(temp_path):
                    os.remove(temp_path)
            except OSError as e:
                logger.warning("Failed to remove temp file %s: %s", temp_path, e)

    @app.route("/api/job/<job_id>/deploy", methods=["POST"])
    def job_deploy(job_id):
        try:
            success, msg = job_mgr.deploy(job_id)
            return jsonify({"success": success, "message": msg})
        except ValueError as e:
            if "not found" in str(e).lower():
                return jsonify({"error": str(e)}), 404
            return jsonify({"error": str(e)}), 400
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    @app.route("/api/job/<job_id>/preview", methods=["GET"])
    def job_preview(job_id):
        """Generate structure preview for a past job."""
        job = job_mgr.get_job(job_id)
        if not job:
            return jsonify({"error": "job not found"}), 404

        # A completed password-protected project cannot be parsed again after
        # its passphrase has been cleared. Prefer the safe, cached projection.
        cached_preview = job_mgr.get_job_preview(job_id)
        if isinstance(cached_preview, dict):
            return jsonify(cached_preview)

        input_path = job.get("input")
        if not input_path or not os.path.exists(input_path):
            return jsonify({"error": "job input file not found"}), 404

        try:
            # SECURITY: Get password from in-memory store (not from job JSON)
            passwords = getattr(job_mgr, "_passwords", {})
            password = passwords.get(job_id)

            # Load project (json dump or parse knxproj)
            if input_path.lower().endswith(".json"):
                with open(input_path, "r", encoding="utf8") as file:
                    project = json.load(file)
            else:
                # Parse knxproj archive using XKNXProj
                from xknxproject.xknxproj import XKNXProj

                knxproj = XKNXProj(path=input_path, password=password, language="de-DE")
                project = knxproj.parse()

            # Extract project metadata
            import importlib

            knxmod = importlib.import_module("knxproject_to_openhab")

            # Get building structure
            building = knxmod.create_building(project)
            addresses = knxmod.get_addresses(project)
            house = knxmod.put_addresses_in_building(building, addresses, project)

            # Extract metadata
            project_name = house[0].get("name_long") if house else None
            gateway_ip = knxmod.get_gateway_ip(project)
            homekit_enabled = knxmod.is_homekit_enabled(project)
            alexa_enabled = knxmod.is_alexa_enabled(project)

            # Detect unknown items (addresses without proper room/floor assignments or with default names)
            unknown_items = []
            for addr in addresses:
                floor_name = addr.get("Floor", "").strip()
                room_name = addr.get("Room", "").strip()

                # Check if floor or room is unknown/empty
                if (
                    (not floor_name or floor_name.upper() in ["UNKNOWN", "UNBEKANNT"])
                    or (not room_name or room_name.upper() in ["UNKNOWN", "UNBEKANNT"])
                    or (not floor_name and not room_name)
                ):  # Items without both floor and room
                    unknown_items.append(
                        {
                            "name": addr.get("Group name", "Unknown Address"),
                            "address": addr.get("Address", "N/A"),
                            "floor": floor_name or "None",
                            "room": room_name or "None",
                        }
                    )

            # Build preview structure
            preview_data = {
                "metadata": {
                    "project_name": project_name,
                    "gateway_ip": gateway_ip,
                    "homekit_enabled": homekit_enabled,
                    "alexa_enabled": alexa_enabled,
                    "total_addresses": len(addresses),
                    "unknown_items": unknown_items,
                },
                "buildings": [],
            }

            if house:
                for building_data in house:
                    building_info = {
                        "name": building_data.get(
                            "Description",
                            building_data.get("Group name", "Unknown Building"),
                        ),
                        "description": building_data.get("name_long", ""),
                        "floors": [],
                    }

                    for floor_data in building_data.get("floors", []):
                        floor_info = {
                            "name": floor_data.get(
                                "Description",
                                floor_data.get("Group name", "Unknown Floor"),
                            ),
                            "description": floor_data.get("name_long", ""),
                            "rooms": [],
                        }

                        for room_data in floor_data.get("rooms", []):
                            # Format addresses to ensure they have the required fields
                            raw_addresses = room_data.get("Addresses", [])
                            formatted_addresses = []
                            for addr in raw_addresses:
                                formatted_addr = {
                                    "Group name": addr.get(
                                        "Group name",
                                        addr.get("name", "Unknown Address"),
                                    ),
                                    "Address": addr.get("Address", addr.get("address", "N/A")),
                                }
                                formatted_addresses.append(formatted_addr)

                            room_info = {
                                "name": room_data.get(
                                    "Description",
                                    room_data.get("Group name", "Unknown Room"),
                                ),
                                "description": room_data.get("name_long", ""),
                                "address_count": len(formatted_addresses),
                                "device_count": len(room_data.get("devices", [])),
                                "addresses": formatted_addresses,
                            }
                            floor_info["rooms"].append(room_info)

                        building_info["floors"].append(floor_info)

                    preview_data["buildings"].append(building_info)

            return jsonify(preview_data)

        except Exception as e:
            friendly_msg = _password_error_message(e)
            if friendly_msg:
                return jsonify({"error": friendly_msg}), 400
            return jsonify({"error": str(e)}), 500

    @app.route("/api/openhab/cloud-info", methods=["GET"])
    def openhab_cloud_info():
        """Read openHAB Cloud UUID and Secret from the local filesystem."""
        candidate_paths = [
            ("/var/lib/openhab/uuid", "/var/lib/openhab/openhabcloud/secret"),
            ("/var/lib/openhab2/uuid", "/var/lib/openhab2/openhabcloud/secret"),
        ]
        openhab_userdata = cfg.get("openhab_userdata", None)
        if openhab_userdata:
            candidate_paths.insert(
                0,
                (
                    os.path.join(openhab_userdata, "uuid"),
                    os.path.join(openhab_userdata, "openhabcloud", "secret"),
                ),
            )

        uuid_val = secret_val = uuid_path_found = secret_path_found = None

        for uuid_p, secret_p in candidate_paths:
            if os.path.isfile(uuid_p) and not uuid_val:
                try:
                    with open(uuid_p, "r", encoding="utf-8") as f:
                        uuid_val = f.read().strip()
                    uuid_path_found = uuid_p
                except Exception:
                    pass
            if os.path.isfile(secret_p) and not secret_val:
                try:
                    with open(secret_p, "r", encoding="utf-8") as f:
                        secret_val = f.read().strip()
                    secret_path_found = secret_p
                except Exception:
                    pass

        return jsonify(
            {
                "uuid": uuid_val,
                "secret": secret_val,
                "uuid_path": uuid_path_found,
                "secret_path": secret_path_found,
            }
        )

    if __name__ == "__main__":
        host = cfg.get("bind_host", "0.0.0.0")
        port = cfg.get("port", 8080)
        app.run(host=host, port=port)
else:
    # Provide a minimal message when Flask is not available
    if __name__ == "__main__":
        print("Flask is not installed. Please install requirements to run the server.")
