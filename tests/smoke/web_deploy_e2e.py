#!/usr/bin/env python3
"""Exercise the live Web UI HTTP workflow against real openHAB on a disposable CI VM.

This deliberately calls production /api/upload, /api/job/*/deploy, config and
rollback endpoints. No backend mocks, direct file copies or fake deploy replies.
"""

from __future__ import annotations

import base64
import json
import os
import sys
import time
import uuid
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from openhab_log_guard import check_since, snapshot
from verify_openhab_rest import verify

WEB = "http://127.0.0.1:8085"
USERNAME = "smoke"
PASSWORD = "smoke-only-not-a-secret-12345"
MAX_JOB_WAIT = 180
MAX_RUNTIME_WAIT = 240


def request_json(
    endpoint: str,
    method: str = "GET",
    payload: dict | None = None,
    upload: Path | None = None,
) -> dict:
    authorization = base64.b64encode(f"{USERNAME}:{PASSWORD}".encode()).decode("ascii")
    headers = {
        "Accept": "application/json",
        "Authorization": f"Basic {authorization}",
        "Origin": WEB,
    }
    body = None
    if upload is not None:
        boundary = "knxoh-ci-" + uuid.uuid4().hex
        headers["Content-Type"] = f"multipart/form-data; boundary={boundary}"
        body = (
            (
                f"--{boundary}\r\n"
                f'Content-Disposition: form-data; name="file"; filename="{upload.name}"\r\n'
                "Content-Type: application/json\r\n\r\n"
            ).encode()
            + upload.read_bytes()
            + f"\r\n--{boundary}--\r\n".encode()
        )
    elif payload is not None:
        headers["Content-Type"] = "application/json"
        body = json.dumps(payload).encode()
    req = Request(WEB + endpoint, data=body, headers=headers, method=method)
    try:
        with urlopen(req, timeout=30) as response:
            value = json.load(response)
            if not isinstance(value, dict):
                raise AssertionError(f"{endpoint}: expected a JSON object")
            return value
    except HTTPError as error:
        detail = error.read(2500).decode("utf-8", errors="replace")
        raise AssertionError(f"{method} {endpoint} -> HTTP {error.code}: {detail}") from error


def set_format(output_format: str) -> None:
    configuration = request_json("/api/config")
    configuration["output_format"] = output_format
    result = request_json("/api/config", "POST", configuration)
    if result.get("error"):
        raise AssertionError(f"Could not choose {output_format}: {result['error']}")
    assert request_json("/api/config")["output_format"] == output_format


def await_job(job_id: str, expected_format: str) -> dict:
    deadline = time.monotonic() + MAX_JOB_WAIT
    last: dict = {}
    while time.monotonic() < deadline:
        last = request_json(f"/api/job/{job_id}")
        status = last.get("status")
        if status == "failed":
            raise AssertionError(
                f"Generator job {job_id} failed: {last.get('error')}; "
                f"job log: {str(last.get('log', []))[-2000:]}"
            )
        if status == "completed":
            assert last.get("staged"), f"Completed job is not staged: {job_id}"
            assert last.get("output_format") == expected_format
            assert last.get("stage_mapping"), "Generator produced no staged files"
            return last
        time.sleep(2)
    raise TimeoutError(f"Job {job_id} did not finish in {MAX_JOB_WAIT}s: {last}")


def upload_project(project: Path, expected_format: str) -> dict:
    result = request_json("/api/upload", "POST", upload=project)
    job_id = result.get("id")
    assert isinstance(job_id, str) and job_id, f"Invalid upload result: {result}"
    job = await_job(job_id, expected_format)
    print(
        f"PASS upload + generator: {project.name}, format={expected_format}, job={job_id}",
        flush=True,
    )
    return job


def deploy(job: dict) -> dict:
    result = request_json(f"/api/job/{job['id']}/deploy", "POST", {})
    assert result.get("success") is True, f"Actual backend deploy failed: {result}"
    current = request_json(f"/api/job/{job['id']}")
    assert current.get("deployed") is True, "Job not marked as deployed"
    assert current.get("backups"), "Real deploy did not create a rollback backup"
    for backup in current["backups"]:
        assert Path(backup["path"]).is_file(), f"Missing backup: {backup['path']}"
    print(f"PASS actual Web UI deploy: {job['id']}: {result.get('message')}", flush=True)
    return current


def verify_live(manifest: dict, label: str, report_dir: Path) -> None:
    deadline = time.monotonic() + MAX_RUNTIME_WAIT
    last_reason = "not started"
    summary: dict = {}
    while time.monotonic() < deadline:
        try:
            ok, last_reason, summary = verify(manifest)
            if ok:
                (report_dir / f"{label}-rest.json").write_text(
                    json.dumps({"phase": label, "status": "passed", **summary}, indent=2) + "\n",
                    encoding="utf-8",
                )
                print(f"PASS [{label}]: {last_reason}", flush=True)
                return
        except (URLError, HTTPError, TimeoutError, ValueError, KeyError) as error:
            last_reason = f"{type(error).__name__}: {error}"
        time.sleep(5)
    raise AssertionError(f"openHAB did not load generated configuration [{label}]: {last_reason}")


def read_live(name: str) -> bytes:
    return (Path("/etc/openhab") / name).read_bytes()


def verify_files(output_format: str) -> None:
    yaml = read_live("yaml/knx.yaml")
    things = read_live("things/knx.things")
    items = read_live("items/knx.items")
    if output_format == "yaml":
        assert yaml.strip(), "Real deploy did not write YAML"
        assert not things.strip() and not items.strip(), "Legacy Things/Items were not retired"
    else:
        assert things.strip() and items.strip(), "Real deploy did not write legacy outputs"
        assert not yaml.strip(), "YAML file was not retired"


def write_report(report_dir: Path, name: str, payload: dict) -> None:
    (report_dir / name).write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    if os.environ.get("CI") != "true" or os.environ.get("GITHUB_ACTIONS") != "true":
        raise SystemExit("Disposable GitHub Actions VM only")
    if len(sys.argv) != 3:
        raise SystemExit("Usage: web_deploy_e2e.py MINI_PROJECT_JSON REPORT_DIR")
    project = Path(sys.argv[1]).resolve()
    reports = Path(sys.argv[2]).resolve()
    reports.mkdir(parents=True, exist_ok=True)
    assert project.name == "mini_project.json", "Only public synthetic fixture is allowed"
    manifest = json.loads((reports / "generated/manifest.json").read_text(encoding="utf-8"))

    # Existing runtime smoke has already loaded the legacy model.
    set_format("legacy")
    baseline = (
        read_live("items/knx.items"),
        read_live("things/knx.things"),
        read_live("yaml/knx.yaml"),
    )

    before_legacy = snapshot()
    first = deploy(upload_project(project, "legacy"))
    verify_files("legacy")
    verify_live(manifest, "web-deploy-legacy", reports)
    time.sleep(8)
    check_since(before_legacy, "web-deploy-legacy", reports / "web-deploy-legacy-logs.json")
    first_files = (read_live("items/knx.items"), read_live("things/knx.things"))

    # Browser's "rerun" calls the same endpoint; prove an unchanged project is
    # idempotent and creates a new pre-deploy backup.
    before_repeat = snapshot()
    rerun = request_json(f"/api/job/{first['id']}/rerun", "POST", {})
    rerun_job_id = rerun.get("id")
    assert rerun_job_id, f"Rerun did not create a job: {rerun}"
    again = deploy(await_job(rerun_job_id, "legacy"))
    verify_files("legacy")
    verify_live(manifest, "web-deploy-repeat", reports)
    time.sleep(8)
    check_since(before_repeat, "web-deploy-repeat", reports / "web-deploy-repeat-logs.json")
    assert first_files == (
        read_live("items/knx.items"),
        read_live("things/knx.things"),
    ), "Repeated deploy changed unchanged generator outputs"

    # Now switch the generator via its actual Web UI settings API and deploy
    # native YAML. This exercises format retirement and openHAB's file watcher.
    before_yaml = snapshot()
    set_format("yaml")
    yaml_job = deploy(upload_project(project, "yaml"))
    verify_files("yaml")
    verify_live(manifest, "web-deploy-yaml", reports)
    time.sleep(8)
    check_since(before_yaml, "web-deploy-yaml", reports / "web-deploy-yaml-logs.json")

    # Restore exactly the pre-YAML configuration through the production
    # rollback API, not by copying files in this test.
    before_rollback = snapshot()
    rolled_back = request_json(f"/api/job/{yaml_job['id']}/rollback", "POST", {})
    assert rolled_back.get("ok") is True, f"Web rollback failed: {rolled_back}"
    verify_files("legacy")
    assert first_files == (
        read_live("items/knx.items"),
        read_live("things/knx.things"),
    ), "Rollback did not restore earlier legacy files"
    verify_live(manifest, "web-deploy-rollback", reports)
    time.sleep(8)
    check_since(before_rollback, "web-deploy-rollback", reports / "web-deploy-rollback-logs.json")
    write_report(
        reports,
        "web-deploy-e2e.json",
        {
            "status": "passed",
            "test_project": project.name,
            "legacy_job": first["id"],
            "repeat_job": again["id"],
            "yaml_job": yaml_job["id"],
            "phases": ["legacy", "repeat", "yaml", "rollback"],
            "baseline_pre_deploy_files_exist": all(baseline[:2]),
        },
    )
    print("PASS: real upload, generator, deploy, rerun, YAML switch and rollback", flush=True)


if __name__ == "__main__":
    main()
