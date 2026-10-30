"""Local-only transaction boundary processes; NOT a systemd confinement test.

Launched with a demoted UID by test_update_transaction, never by installed units.
Only the fixture downloader is substituted; production stage code is exercised.
"""

import json
import os
import sys
import urllib.request
from pathlib import Path


def main():
    mode, source, *args = sys.argv[1:]
    sys.path.insert(0, source)
    if mode == "stage":
        from installer import update_prepare

        stage, workspace, candidate, base, failure = args

        def download(url, limit):
            # Coordinator still validates genuine GitHub metadata/asset URLs.
            # Transport ONLY is redirected to an ephemeral loopback fixture.
            key = "metadata" if "api.github.com" in url else url.rsplit("/", 1)[-1]
            with urllib.request.urlopen(base + "/" + key, timeout=5) as response:
                data = response.read(limit + 1)
            assert len(data) <= limit
            return data

        update_prepare.download = download
        if stage == failure == "dependencies":
            (Path(candidate) / "poison-partial-venv").write_text("must never resume")
            # Exercise a REAL failed isolated pip installation, offline,
            # after the final-path venv has actually been constructed.
            (Path(candidate) / "requirements.txt").write_text(
                "/nonexistent/knxoh_missing_fixture_dependency-1.0-py3-none-any.whl\n"
            )
        update_prepare.run_stage(stage, Path(workspace), Path(candidate) if candidate else None)
    elif mode == "app":
        from web_ui.backend.jobs import JobManager
        from web_ui.backend.session_store import SessionStore
        from web_ui.backend.storage import save_jobs

        data, port, bad_health = args
        data = Path(data)
        context = json.loads((data / "context.json").read_text())
        store = SessionStore(data / "sessions.sqlite3", b"fixture-session-key" * 2)
        assert store.get(context["token"]).username == "operator"
        assert store.verify_csrf(context["token"], context["csrf"])
        for token, username in context.get("writer_sessions", []):
            assert store.get(token).username == username
        manager = JobManager({"jobs_dir": str(data / "jobs"), "backups_dir": str(data / "backup")})
        assert manager.get_job("existing")["stats"] == {"count": 7}
        version = (Path(source) / "VERSION").read_text().strip()
        evidence = data / "startup-evidence.json"
        starts = json.loads(evidence.read_text()) if evidence.exists() else []
        starts.append(
            {
                "version": version,
                "source": source,
                "read_jobs": list(manager._jobs),
                "read_sessions": [u for _, u in context.get("writer_sessions", [])],
            }
        )
        evidence.write_text(json.dumps(starts))
        manager._jobs["written-" + version] = {"id": "written-" + version, "status": "completed"}
        save_jobs(manager.jobs_dir, manager._jobs)
        writer_token, _ = store.create("writer-" + version)
        context.setdefault("writer_sessions", []).append([writer_token, "writer-" + version])
        (data / "context.json").write_text(json.dumps(context))
        manager.executor.shutdown(wait=True)
        from web_ui.backend.app import app

        if bad_health == "yes":
            app.view_functions["health"] = lambda: ({"status": "ready", "version": "wrong"}, 200)
        app.run(host="127.0.0.1", port=int(port), use_reloader=False, threaded=True)
    elif mode == "coordinator":
        # Trusted test controller, not candidate code; root is needed for the
        # real ownership/snapshot protocol. All release execution is demoted.
        sys.path.insert(0, str(Path(__file__).parent))
        from test_update_transaction import crash_coordinator

        crash_coordinator(*args)
    elif mode == "installer-lock":
        from installer.update_bootstrap import LifecycleLock

        with LifecycleLock(Path(args[0])).acquire():
            print("locked", flush=True)
            sys.stdin.readline()
    elif mode == "submit":
        from dataclasses import asdict
        from subprocess import CompletedProcess

        from installer import update_submit
        from installer.update_core.protocol import Paths

        paths = Paths(*(Path(p) for p in json.loads(args[0])))

        def manager(argv, **kwargs):
            if argv == [
                "sudo",
                "-n",
                update_submit.SYSTEMCTL,
                "start",
                "--no-block",
                update_submit.UNIT,
            ]:
                (paths.data_dir / "submission-started").touch()
                return CompletedProcess(argv, 0, "", "")
            assert argv == [
                update_submit.SYSTEMCTL,
                "show",
                update_submit.UNIT,
                "--property=LoadState,ActiveState,SubState,Job",
                "--all",
                "--no-pager",
            ]
            return CompletedProcess(
                argv, 0, "LoadState=loaded\nActiveState=inactive\nSubState=dead\nJob=\n", ""
            )

        update_submit.subprocess.run = manager
        print(json.dumps(asdict(update_submit.submit_update(paths))), flush=True)
    else:
        raise ValueError(mode)


if __name__ == "__main__":
    if sys.argv[1] not in ("coordinator", "installer-lock"):
        assert os.geteuid() != 0, "fixture application/stage must never run as root"
    main()
