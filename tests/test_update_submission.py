"""Real no-follow publication and acknowledgement tests; no host service calls."""

import json
import os
import subprocess
import tempfile
import time
from pathlib import Path
from unittest.mock import Mock
from uuid import uuid4

import pytest

from installer import update_submit as submit
from installer.update_core.protocol import Paths, parse_request
from installer.update_core.transaction import UpdateResult

REAL_RUN = subprocess.run


@pytest.mark.parametrize(
    "argv,channel",
    [
        ([], "stable"),
        (["--channel", "stable"], "stable"),
        (["--channel", "prerelease"], "prerelease"),
    ],
)
def test_actual_cli_main_defaults_and_explicit_channels(
    monkeypatch, tmp_path, capsys, argv, channel
):
    from types import SimpleNamespace

    import knxoh_paths

    monkeypatch.setattr(submit, "os", SimpleNamespace(name="posix", geteuid=lambda: 65534))
    monkeypatch.setattr(
        knxoh_paths,
        "get_paths",
        lambda: SimpleNamespace(
            install_dir=tmp_path / "install",
            config_dir=tmp_path / "config",
            data_dir=tmp_path / "data",
            backup_dir=tmp_path / "backup",
        ),
    )
    publish = Mock(
        return_value=UpdateResult("submitted", request_id="10000000-0000-4000-8000-000000000001")
    )
    monkeypatch.setattr(submit, "submit_update", publish)
    assert submit.main(argv) == 0
    assert publish.call_args.args[1] == channel
    assert json.loads(capsys.readouterr().out)["status"] == "submitted"
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize(
    "argv,root,code",
    [
        (["--channel", "beta"], False, 2),
        (["--url", "https://example.invalid"], False, 2),
        ([], True, 1),
        (["--channel", "prerelease"], True, 1),
    ],
)
def test_actual_cli_rejects_before_path_import_or_effects(monkeypatch, capsys, argv, root, code):
    import builtins
    from types import SimpleNamespace

    original_import = builtins.__import__

    def guarded_import(name, *args, **kwargs):
        assert name != "knxoh_paths", "path import/effect before CLI refusal"
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(
        submit, "os", SimpleNamespace(name="posix", geteuid=lambda: 0 if root else 65534)
    )
    monkeypatch.setattr(builtins, "__import__", guarded_import)
    publish = Mock(side_effect=AssertionError("submission before CLI validation"))
    monkeypatch.setattr(submit, "submit_update", publish)
    with pytest.raises(SystemExit) as result:
        submit.main(argv)
    assert result.value.code == code
    publish.assert_not_called()
    assert ("not root" if root else "error:") in capsys.readouterr().err


@pytest.fixture
def layout(monkeypatch):
    if os.name != "posix" or os.geteuid() != 0:
        pytest.skip("isolated Linux root-private no-follow fixture")
    with tempfile.TemporaryDirectory(prefix="task8-", dir="/run") as root:
        root = Path(root)
        for name in ("releases", "config", "data", "backup"):
            (root / name).mkdir(mode=0o700)
        (root / "releases/1.0.0").mkdir()
        (root / "current").symlink_to(root / "releases/1.0.0")
        paths = Paths(
            root / "releases", root / "current", root / "config", root / "data", root / "backup"
        )
        status(paths)
        runner = Mock(
            return_value=Mock(
                returncode=0, stdout="LoadState=loaded\nActiveState=inactive\nSubState=dead\nJob=\n"
            )
        )
        monkeypatch.setattr(submit.subprocess, "run", runner)
        monkeypatch.setattr(submit, "ACK_TIMEOUT", 0.02)
        monkeypatch.setattr(submit, "POLL_INTERVAL", 0.001)
        yield paths, runner


def status(paths, request_id=None, phase="rolled-back"):
    value = {"format_version": 1, "phase": phase, "message": "No update requested"}
    if request_id:
        value["request_id"] = request_id
    (paths.config_dir / ".updater-status.json").write_text(json.dumps(value))


def ack_on_start(paths, runner, phase="claimed"):
    def run(argv, **kwargs):
        if argv[0] == "sudo":
            request = parse_request((paths.data_dir / "update/request.json").read_bytes())
            status(paths, request.request_id, phase)
        return Mock(
            returncode=0, stdout="LoadState=loaded\nActiveState=inactive\nSubState=dead\nJob=\n"
        )

    runner.side_effect = run


def test_exact_atomic_request_and_fixed_nonblocking_start(layout):
    paths, runner = layout
    ack_on_start(paths, runner)
    result = submit.submit_update(paths)
    assert result.status == "submitted"
    request_path = paths.data_dir / "update/request.json"
    value = json.loads(request_path.read_bytes())
    assert set(value) == {"format_version", "request_id", "channel"}
    assert parse_request(request_path.read_bytes()).request_id == result.request_id
    assert value["channel"] == "stable"
    assert request_path.stat().st_mode & 0o777 == 0o600
    start = [c.args[0] for c in runner.call_args_list if c.args[0][0] == "sudo"]
    assert start == [
        ["sudo", "-n", "/usr/bin/systemctl", "start", "--no-block", "knxohui-update.service"]
    ]


@pytest.mark.parametrize("channel", [None, {}, [], "nightly", "stable;sh"])
def test_invalid_channel_before_filesystem_or_service(channel, tmp_path):
    paths = Paths(tmp_path / "releases", tmp_path / "current")
    assert submit.submit_update(paths, channel).status == "failed"
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("phase", ["claimed", "committed", "rolled-back"])
def test_matching_ack_even_if_worker_finished_fast(layout, phase):
    paths, runner = layout
    ack_on_start(paths, runner, phase)
    assert submit.submit_update(paths, "prerelease").status == "submitted"
    assert (
        json.loads((paths.data_dir / "update/request.json").read_bytes())["channel"] == "prerelease"
    )


def test_initial_or_unrelated_status_not_ack_and_no_overwrite_on_retry(layout):
    paths, runner = layout
    assert submit.submit_update(paths).status == "failed"
    original = (paths.data_dir / "update/request.json").read_bytes()
    status(paths, str(uuid4()), "committed")
    assert submit.submit_update(paths).status == "busy"
    assert (paths.data_dir / "update/request.json").read_bytes() == original


@pytest.mark.parametrize("active", ["active", "activating", "deactivating", "reloading"])
def test_never_replace_live_request_even_if_stale(layout, active):
    paths, runner = layout
    submit.submit_update(paths)
    request = paths.data_dir / "update/request.json"
    original = request.read_bytes()
    os.utime(request, (time.time() - 60,) * 2)
    runner.return_value.stdout = f"LoadState=loaded\nActiveState={active}\nSubState=running\nJob=\n"
    assert submit.submit_update(paths).status == "busy"
    assert request.read_bytes() == original


def test_queued_worker_job_is_busy_even_before_active_state_changes(layout):
    paths, runner = layout
    submit.submit_update(paths)
    request = paths.data_dir / "update/request.json"
    original = request.read_bytes()
    os.utime(request, (time.time() - 60,) * 2)
    runner.return_value.stdout = "LoadState=loaded\nActiveState=inactive\nSubState=dead\nJob=123\n"
    assert submit.submit_update(paths).status == "busy"
    assert request.read_bytes() == original


def test_stale_unclaimed_inactive_request_replaced_with_fresh_id(layout):
    paths, runner = layout
    submit.submit_update(paths)
    request = paths.data_dir / "update/request.json"
    previous = request.read_bytes()
    os.utime(request, (time.time() - 31,) * 2)
    ack_on_start(paths, runner)
    assert submit.submit_update(paths).status == "submitted"
    assert request.read_bytes() != previous


def test_crash_after_claim_requires_recovery_not_replay(layout):
    paths, runner = layout
    ack_on_start(paths, runner)
    assert submit.submit_update(paths).status == "submitted"
    request = paths.data_dir / "update/request.json"
    original = request.read_bytes()
    os.utime(request, (time.time() - 60,) * 2)
    assert submit.submit_update(paths).status == "blocked"
    assert request.read_bytes() == original


def test_completed_request_may_be_replaced_but_never_replayed(layout):
    paths, runner = layout
    ack_on_start(paths, runner, "committed")
    first = submit.submit_update(paths)
    second = submit.submit_update(paths)
    assert first.status == second.status == "submitted"
    assert first.request_id != second.request_id


def test_service_absent_and_legacy_actionable_without_publication(layout):
    paths, runner = layout
    runner.return_value.stdout = "LoadState=not-found\nActiveState=inactive\nSubState=dead\nJob=\n"
    result = submit.submit_update(paths)
    assert result.status == "failed" and "verified" in result.error
    assert not (paths.data_dir / "update/request.json").exists()
    paths.current.unlink()
    result = submit.submit_update(paths)
    assert result.status == "failed" and "bootstrap" in result.error


@pytest.mark.parametrize("leaf", ["update", "submit.lock", "request.json"])
def test_symlink_refused_without_touching_target(layout, leaf):
    paths, runner = layout
    update = paths.data_dir / "update"
    target = paths.data_dir / "target"
    target.write_text("unchanged")
    if leaf == "update":
        update.symlink_to(paths.data_dir, target_is_directory=True)
    else:
        update.mkdir(mode=0o700)
        (update / leaf).symlink_to(target)
    assert submit.submit_update(paths).status == "failed"
    assert target.read_text() == "unchanged"
    assert not [c for c in runner.call_args_list if c.args[0][0] == "sudo"]


def test_submission_lock_uses_same_inode_across_processes(layout):
    import fcntl
    import sys

    paths, runner = layout
    ack_on_start(paths, runner, "committed")
    assert submit.submit_update(paths).status == "submitted"
    lock = paths.data_dir / "update/submit.lock"
    identity = lock.stat().st_ino
    with lock.open("r+") as held:
        fcntl.flock(held, fcntl.LOCK_EX)
        code = (
            "import fcntl,sys; f=open(sys.argv[1],'r+'); fcntl.flock(f,fcntl.LOCK_EX|fcntl.LOCK_NB)"
        )
        child = REAL_RUN([sys.executable, "-c", code, str(lock)], capture_output=True)
        assert child.returncode != 0
        assert submit.submit_update(paths).status == "busy"
    assert lock.stat().st_ino == identity


def test_publication_race_never_overwrites_another_request(layout, monkeypatch):
    paths, runner = layout
    original_rename = submit._rename_no_replace
    other = {"format_version": 1, "request_id": str(uuid4()), "channel": "prerelease"}

    def race(parent, src, dst):
        (paths.data_dir / "update/request.json").write_text(json.dumps(other))
        return original_rename(parent, src, dst)

    monkeypatch.setattr(submit, "_rename_no_replace", race)
    assert submit.submit_update(paths).status == "failed"
    assert json.loads((paths.data_dir / "update/request.json").read_bytes()) == other
    assert not [c for c in runner.call_args_list if c.args[0][0] == "sudo"]


def test_swapped_lock_inode_is_rejected_before_publication(layout, monkeypatch):
    paths, runner = layout
    original = submit._worker_state

    def race():
        lock = paths.data_dir / "update/submit.lock"
        lock.rename(lock.with_suffix(".old"))
        lock.write_text("")
        return original()

    monkeypatch.setattr(submit, "_worker_state", race)
    assert submit.submit_update(paths).status == "failed"
    assert not (paths.data_dir / "update/request.json").exists()
    assert not [c for c in runner.call_args_list if c.args[0][0] == "sudo"]


@pytest.mark.parametrize("after", [False, True])
def test_crash_at_start_preserves_uncertain_request(layout, after):
    paths, runner = layout

    def start(argv, **kwargs):
        if argv[0] == "sudo":
            if after:
                value = parse_request((paths.data_dir / "update/request.json").read_bytes())
                status(paths, value.request_id, "claimed")
            raise subprocess.TimeoutExpired(argv, 5)
        return Mock(
            returncode=0, stdout="LoadState=loaded\nActiveState=inactive\nSubState=dead\nJob=\n"
        )

    runner.side_effect = start
    assert submit.submit_update(paths).status == "failed"
    previous = (paths.data_dir / "update/request.json").read_bytes()
    assert submit.submit_update(paths).status == ("blocked" if after else "busy")
    assert (paths.data_dir / "update/request.json").read_bytes() == previous


def test_status_reset_does_not_ack_and_old_id_is_never_reused(layout):
    paths, runner = layout
    ack_on_start(paths, runner, "committed")
    first = submit.submit_update(paths)
    status(paths)  # Administrator/restart reset, no ID: NOT acknowledgement.
    request = paths.data_dir / "update/request.json"
    os.utime(request, (time.time() - 31,) * 2)
    runner.side_effect = None
    second = submit.submit_update(paths)
    assert second.status == "failed"
    assert first.request_id != second.request_id
    assert parse_request(request.read_bytes()).request_id == second.request_id


@pytest.mark.parametrize("damage", ["large", "hardlink", "writable", "malformed"])
def test_bad_request_file_fails_closed(layout, damage):
    paths, runner = layout
    update = paths.data_dir / "update"
    update.mkdir(mode=0o700)
    request = update / "request.json"
    request.write_text("x" * (4097 if damage == "large" else 1))
    if damage == "hardlink":
        os.link(request, update / "alias")
    elif damage == "writable":
        request.chmod(0o666)
    assert submit.submit_update(paths).status == "failed"
    assert not [c for c in runner.call_args_list if c.args[0][0] == "sudo"]


def test_real_unprivileged_service_context(layout):
    import sys

    paths, _ = layout
    root = paths.current.parent
    root.chmod(0o755)
    os.chown(paths.data_dir, 65534, 65534)
    code = """
import json,sys
from pathlib import Path
from unittest.mock import Mock
from installer import update_submit as s
from installer.update_core.protocol import Paths,parse_request
root=Path(sys.argv[1])
p=Paths(root/'releases',root/'current',root/'config',root/'data',root/'backup')
# Root status is readable, never writable by this identity; emulate the root
# claim observation in memory, not by weakening status ownership in production.
initial=s.read_status(p)
assert initial['message']=='No update requested'
def run(argv,**kwargs):
    if argv[0]=='sudo':
        request=parse_request((p.data_dir/'update/request.json').read_bytes())
        s.read_status=lambda p: dict(initial, request_id=request.request_id, phase='claimed')
    return Mock(returncode=0,stdout='LoadState=loaded\\nActiveState=inactive\\nSubState=dead\\nJob=\\n')
s.subprocess.run=run
r=s.submit_update(p)
assert r.status=='submitted',r
print(r.request_id)
"""
    # Only these disposable fixture directories gain traversal; no host directory
    # or production ownership boundary is modified.
    paths.config_dir.chmod(0o755)
    paths.releases.chmod(0o755)
    child = REAL_RUN(
        [sys.executable, "-c", code, str(root)],
        user=65534,
        group=65534,
        extra_groups=(),
        capture_output=True,
        text=True,
    )
    assert child.returncode == 0, child.stderr


def test_actual_publishers_serialize_through_acknowledgement(layout):
    import sys

    paths, _ = layout
    root = paths.current.parent
    ready, finish = root / "ready", root / "finish"
    code = """
import json,sys,time
from pathlib import Path
from unittest.mock import Mock
from installer import update_submit as s
from installer.update_core.protocol import Paths,parse_request
root=Path(sys.argv[1])
p=Paths(root/'releases',root/'current',root/'config',root/'data',root/'backup')
def run(argv,**kwargs):
    if argv[0]=='sudo':
        (root/'ready').touch()
        deadline=time.monotonic()+5
        while not (root/'finish').exists():
            assert time.monotonic()<deadline
            time.sleep(.001)
        value=parse_request((p.data_dir/'update/request.json').read_bytes())
        (p.config_dir/'.updater-status.json').write_text(json.dumps(dict(format_version=1,request_id=value.request_id,phase='claimed',message='claimed')))
    return Mock(returncode=0,stdout='LoadState=loaded\\nActiveState=inactive\\nSubState=dead\\nJob=\\n')
s.subprocess.run=run
assert s.submit_update(p).status=='submitted'
"""
    worker = subprocess.Popen(
        [sys.executable, "-c", code, str(root)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        deadline = time.monotonic() + 5
        while not ready.exists() and time.monotonic() < deadline:
            time.sleep(0.001)
        assert ready.exists()
        request = paths.data_dir / "update/request.json"
        original = request.read_bytes()
        result = submit.submit_update(paths, "prerelease")
        assert result.status == "busy"
        assert request.read_bytes() == original
        finish.touch()
        _, error = worker.communicate(timeout=5)
        assert worker.returncode == 0, error
    finally:
        finish.touch()
        if worker.poll() is None:
            worker.terminate()
            worker.communicate(timeout=5)


@pytest.mark.parametrize("phase", ["before-claim", "after-claim"])
def test_real_process_crash_releases_lock_without_losing_request(layout, phase):
    import sys

    paths, runner = layout
    code = """
import json,os,sys
from pathlib import Path
from unittest.mock import Mock
from installer import update_submit as s
from installer.update_core.protocol import Paths,parse_request
root=Path(sys.argv[1])
p=Paths(root/'releases',root/'current',root/'config',root/'data',root/'backup')
def run(argv,**kwargs):
    if argv[0]=='sudo':
        value=parse_request((p.data_dir/'update/request.json').read_bytes())
        assert (p.data_dir/'update/request.json').stat().st_nlink==1
        if sys.argv[2]=='after-claim':
            (p.config_dir/'.updater-status.json').write_text(json.dumps(dict(format_version=1,request_id=value.request_id,phase='claimed',message='claimed')))
        os._exit(23)
    return Mock(returncode=0,stdout='LoadState=loaded\\nActiveState=inactive\\nSubState=dead\\nJob=\\n')
s.subprocess.run=run
s.submit_update(p)
"""
    child = REAL_RUN(
        [sys.executable, "-c", code, str(paths.current.parent), phase],
        capture_output=True,
        text=True,
    )
    assert child.returncode == 23, child.stderr
    request = paths.data_dir / "update/request.json"
    original = request.read_bytes()
    os.utime(request, (time.time() - 31,) * 2)
    ack_on_start(paths, runner)
    result = submit.submit_update(paths)
    assert result.status == ("blocked" if phase == "after-claim" else "submitted")
    assert (request.read_bytes() == original) is (phase == "after-claim")


@pytest.mark.parametrize("where", ["base", "release"])
def test_wrapper_finds_application_client_without_trusting_it_as_root(layout, where):
    paths, _ = layout
    root = paths.current.parent
    app = paths.releases / "1.0.0"
    root.chmod(0o755)
    paths.releases.chmod(0o755)
    os.chown(paths.data_dir, 65534, 65534)
    (app / "installer").mkdir()
    (app / "installer/update_submit.py").write_text("# application client\n")
    (app / "venv/bin").mkdir(parents=True)
    python = app / "venv/bin/python"
    python.write_text('#!/bin/sh\nprintf "%s\\n" "$PWD" "$@" > "$KNX_TEST_OUT"\n')
    python.chmod(0o755)
    script = (root if where == "base" else app) / "update.sh"
    source = Path(__file__).parents[1] / "update.sh"
    script.write_bytes(source.read_bytes())
    output = paths.data_dir / "args"
    result = REAL_RUN(
        ["bash", str(script), "--channel", "prerelease"],
        user=65534,
        group=65534,
        extra_groups=(),
        env={"PATH": "/usr/bin:/bin", "KNX_TEST_OUT": str(output)},
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    lines = output.read_text().splitlines()
    assert Path(lines[0]).resolve() == app
    assert lines[1:] == ["-m", "installer.update_submit", "--channel", "prerelease"]
