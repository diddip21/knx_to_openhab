import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
UNIT_MANAGER = ROOT / "installer" / "setup_systemd_unit.sh"
MANAGED_UNITS = (
    "knxohui.service",
    "knxohui-update.service",
    "knxohui-backup-cleanup.service",
    "knxohui-backup-cleanup.timer",
)


def run_setup_unit_manager(
    tmp_path,
    unit,
    load_state,
    *,
    source_text="[Service]\nExecStart=/bin/true\n",
    paths_file=None,
    runtime_mask=False,
    destination_text=None,
    fragment_path=None,
):
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    events = tmp_path / "events.log"
    (fake_bin / "systemctl").write_text(
        "#!/usr/bin/env bash\n"
        'printf "%s\\n" "$*" >> "$UNIT_TEST_EVENTS"\n'
        'if [[ "${1:-}" == show ]]; then\n'
        '  if [[ "${2:-}" == --property=FragmentPath ]]; then\n'
        '    echo "$UNIT_TEST_FRAGMENT_PATH"\n'
        '  elif [[ "${4:-}" == "$UNIT_TEST_MASKED_UNIT" ]]; then\n'
        '    echo masked\n'
        '  else\n'
        '    echo loaded\n'
        '  fi\n'
        "else\n"
        '  [[ "${1:-}" == enable || "${1:-}" == restart || "${1:-}" == start ]] || exit 2\n'
        '  printf "action:%s\\n" "$*" >> "$UNIT_TEST_EVENTS"\n'
        "fi\n",
        encoding="utf-8",
    )
    (fake_bin / "systemctl").chmod(0o755)
    (fake_bin / "sudo").write_text(
        "#!/usr/bin/env bash\n"
        '[[ "${1:-}" == systemctl || "${1:-}" == install ]] || exit 2\n'
        'exec "$@"\n',
        encoding="utf-8",
    )
    (fake_bin / "sudo").chmod(0o755)
    source = tmp_path / "unit.service"
    source.write_text(source_text, encoding="utf-8")
    paths_file = paths_file or tmp_path / "paths.env"
    destination = tmp_path / "systemd" / unit
    destination.parent.mkdir()
    if runtime_mask:
        destination.write_text("[Service]\nExecStart=/old/runtime-masked-unit\n", encoding="utf-8")
    elif load_state == "masked":
        destination.symlink_to("/dev/null")
    else:
        destination.write_text(
            destination_text or "# Managed by knx_to_openhab installer\n[Service]\n",
            encoding="utf-8",
        )
    environment = os.environ.copy()
    environment.update(
        {
            "PATH": f"{fake_bin}{os.pathsep}{environment['PATH']}",
            "UNIT_TEST_EVENTS": str(events),
            "UNIT_TEST_MASKED_UNIT": unit if load_state == "masked" else "",
            "UNIT_TEST_FRAGMENT_PATH": (
                str(destination) if fragment_path is None else str(fragment_path)
            ),
        }
    )

    result = subprocess.run(
        [
            "bash",
            "-c",
            'set -e; source "$1"; install_setup_systemd_unit "$2" "$3" "$4" "$5"; '
            'setup_systemctl_if_unmasked "$4" enable; '
            'setup_systemctl_if_unmasked "$4" restart',
            "setup-unit-test",
            str(UNIT_MANAGER),
            str(source),
            str(destination),
            unit,
            str(paths_file),
        ],
        env=environment,
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )
    return result, destination, events


@pytest.mark.parametrize("unit", MANAGED_UNITS)
def test_setup_preserves_and_does_not_start_masked_managed_units(tmp_path, unit):
    result, destination, events = run_setup_unit_manager(tmp_path, unit, "masked")

    assert result.returncode == 0, result.stdout + result.stderr
    assert destination.is_symlink()
    assert os.readlink(destination) == "/dev/null"
    calls = events.read_text(encoding="utf-8").splitlines()
    assert calls == [
        f"show --property=LoadState --value {unit}",
        f"show --property=LoadState --value {unit}",
        f"show --property=LoadState --value {unit}",
        f"show --property=LoadState --value {unit}",
    ]


def test_setup_installs_and_starts_an_unmasked_managed_unit(tmp_path):
    unit = "knxohui.service"
    result, destination, events = run_setup_unit_manager(tmp_path, unit, "loaded")

    assert result.returncode == 0, result.stdout + result.stderr
    assert destination.is_file() and not destination.is_symlink()
    assert destination.read_text(encoding="utf-8") == "[Service]\nExecStart=/bin/true\n"
    calls = events.read_text(encoding="utf-8").splitlines()
    assert f"action:enable {unit}" in calls
    assert f"action:restart {unit}" in calls


@pytest.mark.parametrize("unit", MANAGED_UNITS)
def test_setup_refuses_foreign_unit_without_overwriting_or_starting_it(tmp_path, unit):
    foreign = "[Unit]\nDescription=Unrelated service\n[Service]\nExecStart=/bin/false\n"
    result, destination, events = run_setup_unit_manager(
        tmp_path, unit, "loaded", destination_text=foreign
    )

    assert result.returncode != 0
    assert "Refusing to replace an unrecognized systemd unit" in result.stderr
    assert destination.read_text(encoding="utf-8") == foreign
    assert all(call.startswith("show ") for call in events.read_text().splitlines())


@pytest.mark.parametrize("fragment_path", ["/usr/lib/systemd/system/knxohui.service", ""])
def test_setup_refuses_unit_loaded_from_another_location(tmp_path, fragment_path):
    result, destination, events = run_setup_unit_manager(
        tmp_path,
        "knxohui.service",
        "loaded",
        fragment_path=fragment_path,
    )

    assert result.returncode != 0
    assert "outside the managed location" in result.stderr
    assert destination.read_text(encoding="utf-8").startswith("# Managed by")
    assert all(call.startswith("show ") for call in events.read_text().splitlines())


@pytest.mark.parametrize("unit", MANAGED_UNITS)
def test_setup_accepts_an_existing_unmarked_project_unit(tmp_path, unit):
    legacy = (ROOT / "installer" / unit).read_text(encoding="utf-8").replace(
        "# Managed by knx_to_openhab installer\n", ""
    )
    if unit == "knxohui.service":
        legacy = legacy.replace(
            "ExecStart=/usr/local/libexec/knx_to_openhab/launch_web.sh",
            "ExecStart=/opt/custom/venv/bin/gunicorn -c /opt/custom/gunicorn_conf.py "
            "web_ui.backend.app:app",
        )
    elif unit == "knxohui-backup-cleanup.service":
        legacy = legacy.replace(
            "ExecStart=/usr/local/libexec/knx_to_openhab/launch_backup_cleanup.sh",
            "ExecStart=/opt/custom/installer/backup_cleanup.sh",
        )
    result, destination, _ = run_setup_unit_manager(
        tmp_path, unit, "loaded", destination_text=legacy
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert destination.read_text(encoding="utf-8") == "[Service]\nExecStart=/bin/true\n"


def test_setup_does_not_overwrite_or_start_unit_masked_at_runtime(tmp_path):
    unit = "knxohui.service"
    result, destination, events = run_setup_unit_manager(
        tmp_path, unit, "masked", runtime_mask=True
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert destination.is_file() and not destination.is_symlink()
    assert (
        destination.read_text(encoding="utf-8") == "[Service]\nExecStart=/old/runtime-masked-unit\n"
    )
    calls = events.read_text(encoding="utf-8").splitlines()
    assert all(call.startswith("show ") for call in calls)
    assert len(calls) == 4


def test_setup_routes_every_managed_unit_install_and_start_through_mask_checks():
    setup = (ROOT / "installer" / "setup.sh").read_text(encoding="utf-8")

    assert 'source "$SCRIPT_DIR/setup_systemd_unit.sh"' in setup
    assert setup.count("install_setup_systemd_unit") == 4
    assert "setup_systemctl_if_unmasked knxohui.service enable" in setup
    assert "setup_systemctl_if_unmasked knxohui.service restart" in setup
    assert "setup_systemctl_if_unmasked knxohui-backup-cleanup.timer enable" in setup
    assert "setup_systemctl_if_unmasked knxohui-backup-cleanup.timer start" in setup
    assert "setup_systemctl_if_unmasked knxohui-backup-cleanup.timer enable --now" not in setup
    assert setup.count('"$PATHS_FILE"') >= 4
    assert setup.count("preflight_setup_systemd_unit") == 4
    assert setup.index("preflight_setup_systemd_unit knxohui.service") < setup.index(
        'getent group "$SERVICE_USER"'
    )


@pytest.mark.parametrize(
    "unit",
    ("knxohui.service", "knxohui-update.service", "knxohui-backup-cleanup.service"),
)
def test_setup_installs_configured_paths_file_in_service_unit(tmp_path, unit):
    paths_file = tmp_path / "custom config" / "paths.env"
    paths_file.parent.mkdir()
    paths_file.write_text("KNXOH_TEST=ok\n", encoding="utf-8")
    source_text = (ROOT / "installer" / unit).read_text(encoding="utf-8")
    result, destination, _ = run_setup_unit_manager(
        tmp_path,
        unit,
        "loaded",
        source_text=source_text,
        paths_file=paths_file,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    escaped_paths_file = str(paths_file).replace(" ", r"\x20")
    unit_contents = destination.read_text(encoding="utf-8")
    assert f"EnvironmentFile={escaped_paths_file}" in unit_contents
    if shutil.which("systemd-analyze"):
        validation = subprocess.run(
            ["systemd-analyze", "verify", str(destination)],
            capture_output=True,
            text=True,
            check=False,
            timeout=10,
        )
        assert "EnvironmentFile= path is not absolute" not in validation.stderr
