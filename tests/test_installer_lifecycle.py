import hashlib
import io
import json
import os
import subprocess
import tarfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
INSTALLER = ROOT / "install.sh"


def _shell_fixture_text(source):
    """Shell transaction tests fake the separately tested privileged envelope.

    These fixtures already fake sudo/systemctl/accounts and must NEVER acquire
    the host lease or provision real policy. Real envelope/FD/provisioning tests
    live in test_update_units.py with protected disposable paths.
    """
    raw = source.read_text(encoding="utf-8")
    if source.name == "setup.sh":
        start = raw.index("# The verified administrator bootstrap holds ONE lease")
        end = raw.index('if [[ -L "$BASE/releases" ]]', start)
        raw = (
            raw[:start]
            + "provision_updater() { :; }\ncheck_repair_release() { :; }\n\n"
            + raw[end:]
        )
    return raw


def _installer_copy(tmp_path: Path) -> Path:
    script = tmp_path / "install.sh"
    script.write_text(INSTALLER.read_text(encoding="utf-8"), encoding="utf-8", newline="\n")
    return script


def _sandbox_environment(tmp_path: Path, install_dir: Path) -> tuple[dict[str, str], Path]:
    command_dir = tmp_path / "commands"
    command_dir.mkdir(exist_ok=True)
    command_log = tmp_path / "system-commands.log"
    for command in ("sudo", "apt-get", "dpkg", "git", "curl"):
        stub = command_dir / command
        stub.write_text(
            "#!/bin/sh\n"
            f"printf '%s\\n' '{command} $*' >> \"$INSTALLER_COMMAND_LOG\"\n"
            'if [ "$1" = "-n" ] && [ "$2" = "true" ]; then exit 0; fi\n'
            "exit 1\n",
            encoding="utf-8",
        )
        stub.chmod(0o755)
    environment = os.environ.copy()
    environment.update(
        {
            "ALLOW_ROOT": "1",
            "KNXOH_NONINTERACTIVE": "1",
            "KNXOH_INSTALL_DIR": str(install_dir),
            "INSTALLER_COMMAND_LOG": str(command_log),
            "PATH": f"{command_dir}{os.pathsep}{environment['PATH']}",
        }
    )
    return environment, command_log


def _release_downloads(
    tmp_path: Path,
    *,
    corrupt_checksum: bool = False,
    version: str = "1.2.3",
    prerelease: bool = False,
) -> dict[str, str]:
    release_root = tmp_path / f"artifact/knx_to_openhab-{version}"
    installer_dir = release_root / "installer"
    (release_root / "web_ui").mkdir(parents=True)
    installer_dir.mkdir()
    (release_root / "VERSION").write_text(f"{version}\n", encoding="ascii")
    (installer_dir / "setup.sh").write_text(
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        'setup_root="${KNXOH_SETUP_ROOT:-$(cd "$(dirname "$0")/.." && pwd)}"\n'
        'version="$(tr -d \'\\r\\n\' < "$setup_root/VERSION")"\n'
        'release="$KNXOH_INSTALL_DIR/releases/$version"\n'
        'if [ "${1:-}" = --repair ]; then\n'
        '  if [ "${2:-}" = --activate-existing ]; then\n'
        '    ln -s "$KNXOH_REPAIR_TARGET" "$KNXOH_INSTALL_DIR/.current-test"\n'
        '    mv -Tf "$KNXOH_INSTALL_DIR/.current-test" "$KNXOH_INSTALL_DIR/current"\n'
        "  fi\n"
        '  printf \'%s\\n\' "$*" > "$INSTALLER_SETUP_LOG"\n'
        "  exit 0\n"
        "fi\n"
        'mkdir -p "$release"\n'
        'cp -a "$setup_root/." "$release/"\n'
        'ln -s "releases/$version" "$KNXOH_INSTALL_DIR/.current-test"\n'
        'mv -Tf "$KNXOH_INSTALL_DIR/.current-test" "$KNXOH_INSTALL_DIR/current"\n'
        'printf \'%s\\n\' "$*" > "$INSTALLER_SETUP_LOG"\n',
        encoding="utf-8",
        newline="\n",
    )
    (release_root / "installer/web_ui_endpoint.py").write_text(
        "print('loopback')\nprint('127.0.0.1')\nprint('8085')\n", encoding="utf-8"
    )
    archive = tmp_path / f"knx_to_openhab-{version}.tar.gz"
    with tarfile.open(archive, "w:gz") as output:
        output.add(release_root, arcname=release_root.name)
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    if corrupt_checksum:
        digest = "0" * 64
    checksum = tmp_path / f"{archive.name}.sha256"
    checksum.write_text(f"{digest}  {archive.name}\n", encoding="ascii")
    metadata = tmp_path / "release.json"
    release = {
        "tag_name": f"v{version}",
        "draft": False,
        "prerelease": prerelease,
        "assets": [
            {
                "name": archive.name,
                "browser_download_url": "https://downloads.example/release.tar.gz",
            },
            {
                "name": checksum.name,
                "browser_download_url": "https://downloads.example/release.sha256",
            },
        ],
    }
    metadata_value = release
    if prerelease:
        metadata_value = [
            {"tag_name": "v1.2.3", "draft": False, "prerelease": False, "assets": []},
            release,
        ]
    metadata.write_text(json.dumps(metadata_value), encoding="utf-8")
    api_url = "https://api.example/prereleases" if prerelease else "https://api.example/stable"
    release_env = {
        "INSTALLER_TEST_RELEASE_JSON": str(metadata),
        "INSTALLER_TEST_ARCHIVE": str(archive),
        "INSTALLER_TEST_CHECKSUM": str(checksum),
        "INSTALLER_SETUP_LOG": str(tmp_path / "setup-args.log"),
        "INSTALLER_TEST_METADATA_URL": api_url,
    }
    key = "KNXOH_PRERELEASE_RELEASES_API_URL" if prerelease else "KNXOH_STABLE_RELEASE_API_URL"
    release_env[key] = api_url
    return release_env


def _install_artifact_environment(
    tmp_path: Path, install_dir: Path, release_env: dict[str, str]
) -> tuple[dict[str, str], Path]:
    command_dir = tmp_path / "artifact-commands"
    command_dir.mkdir()
    command_log = tmp_path / "artifact-commands.log"
    (command_dir / "sudo").write_text(
        "#!/bin/sh\n"
        'if [ "$1" = "-n" ] && [ "$2" = "true" ]; then exit 0; fi\n'
        'if [ "$1" = "env" ]; then shift; exec env "$@"; fi\n'
        'exec "$@"\n',
        encoding="utf-8",
    )
    (command_dir / "dpkg").write_text(
        "#!/bin/sh\nprintf '%s\\n' 'Status: install ok installed'\n", encoding="utf-8"
    )
    (command_dir / "git").write_text(
        "#!/bin/sh\nprintf '%s\\n' 'git invoked' >> \"$INSTALLER_COMMAND_LOG\"\nexit 1\n",
        encoding="utf-8",
    )
    (command_dir / "curl").write_text(
        "#!/bin/sh\n"
        "output=\nurl=\n"
        "while [ $# -gt 0 ]; do\n"
        '  case "$1" in\n'
        "    -o) output=$2; shift 2 ;;\n"
        "    -H) shift 2 ;;\n"
        "    -*) shift ;;\n"
        "    *) url=$1; shift ;;\n"
        "  esac\n"
        "done\n"
        'case "$url" in\n'
        '  "$INSTALLER_TEST_METADATA_URL") cp "$INSTALLER_TEST_RELEASE_JSON" "$output" ;;\n'
        '  https://downloads.example/release.tar.gz) cp "$INSTALLER_TEST_ARCHIVE" "$output" ;;\n'
        '  https://downloads.example/release.sha256) cp "$INSTALLER_TEST_CHECKSUM" "$output" ;;\n'
        '  *) echo "unexpected download URL: $url" >&2; exit 1 ;;\n'
        "esac\n"
        'printf \'%s\\n\' "$url" >> "$INSTALLER_COMMAND_LOG"\n',
        encoding="utf-8",
    )
    for command in command_dir.iterdir():
        command.chmod(0o755)
    environment = os.environ.copy()
    environment.update(
        {
            "ALLOW_ROOT": "1",
            "KNXOH_INSTALL_DIR": str(install_dir),
            "KNXOH_CONFIG_DIR": str(tmp_path / "etc/knx_to_openhab"),
            "KNXOH_DATA_DIR": str(tmp_path / "var/lib/knx_to_openhab"),
            "KNXOH_BACKUP_DIR": str(tmp_path / "var/backups/knx_to_openhab"),
            "INSTALLER_COMMAND_LOG": str(command_log),
            "PATH": f"{command_dir}{os.pathsep}{environment['PATH']}",
        }
    )
    environment.update(release_env)
    return environment, command_log


@pytest.mark.skipif(os.name != "posix", reason="installer lifecycle requires POSIX Bash")
def test_fresh_install_plan_selects_stable_release_artifact_without_git_checkout(tmp_path):
    install_dir = tmp_path / "opt/knx_to_openhab"
    script = _installer_copy(tmp_path)
    environment, command_log = _sandbox_environment(tmp_path, install_dir)

    result = subprocess.run(
        ["bash", str(script), "--plan"],
        env=environment,
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )

    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {
        "action": "install",
        "channel": "stable",
        "install_dir": str(install_dir),
        "source": "github-release",
    }
    assert not install_dir.exists()
    assert not command_log.exists()


@pytest.mark.skipif(os.name != "posix", reason="installer lifecycle requires POSIX Bash")
def test_fresh_install_downloads_and_activates_verified_stable_release(tmp_path):
    install_dir = tmp_path / "opt/knx_to_openhab"
    script = _installer_copy(tmp_path)
    release_env = _release_downloads(tmp_path)
    environment, command_log = _install_artifact_environment(tmp_path, install_dir, release_env)

    result = subprocess.run(
        ["bash", str(script)],
        env=environment,
        capture_output=True,
        text=True,
        check=False,
        timeout=15,
    )

    assert result.returncode == 0, result.stderr
    assert (install_dir / "current").resolve() == install_dir / "releases/1.2.3"
    assert (install_dir / "releases/1.2.3/VERSION").read_text(encoding="ascii").strip() == "1.2.3"
    assert Path(release_env["INSTALLER_SETUP_LOG"]).read_text(encoding="utf-8") == "\n"
    assert "https://api.example/stable" in command_log.read_text(encoding="utf-8")
    assert not any("git" in line.lower() for line in command_log.read_text().splitlines())


@pytest.mark.skipif(os.name != "posix", reason="installer lifecycle requires POSIX Bash")
def test_prerelease_channel_selects_prerelease_asset_only_when_explicit(tmp_path):
    install_dir = tmp_path / "opt/knx_to_openhab"
    script = _installer_copy(tmp_path)
    release_env = _release_downloads(tmp_path, version="1.3.0-rc.1", prerelease=True)
    environment, command_log = _install_artifact_environment(tmp_path, install_dir, release_env)

    result = subprocess.run(
        ["bash", str(script), "--channel", "prerelease"],
        env=environment,
        capture_output=True,
        text=True,
        check=False,
        timeout=15,
    )

    assert result.returncode == 0, result.stderr
    assert (install_dir / "current").resolve() == install_dir / "releases/1.3.0-rc.1"
    assert (
        command_log.read_text(encoding="utf-8").splitlines()[0] == "https://api.example/prereleases"
    )


@pytest.mark.skipif(os.name != "posix", reason="installer lifecycle requires POSIX Bash")
def test_stable_channel_rejects_semver_prerelease_tag_mislabeled_by_github(tmp_path):
    install_dir = tmp_path / "opt/knx_to_openhab"
    script = _installer_copy(tmp_path)
    release_env = _release_downloads(tmp_path, version="1.2.3-rc.1", prerelease=False)
    environment, _ = _install_artifact_environment(tmp_path, install_dir, release_env)

    result = subprocess.run(
        ["bash", str(script)],
        env=environment,
        capture_output=True,
        text=True,
        check=False,
        timeout=15,
    )

    assert result.returncode != 0
    assert "No stable release with valid archive assets was found" in result.stderr
    assert not (install_dir / "current").exists()


@pytest.mark.skipif(os.name != "posix", reason="installer lifecycle requires POSIX Bash")
def test_interrupted_staging_repair_honors_explicit_prerelease_channel(tmp_path):
    install_dir = tmp_path / "opt/knx_to_openhab"
    (install_dir / "releases/.1.2.2.staging.1234").mkdir(parents=True)
    script = _installer_copy(tmp_path)
    release_env = _release_downloads(tmp_path, version="1.2.3-rc.1", prerelease=True)
    environment, command_log = _install_artifact_environment(tmp_path, install_dir, release_env)

    result = subprocess.run(
        ["bash", str(script), "--repair", "--channel", "prerelease"],
        env=environment,
        capture_output=True,
        text=True,
        check=False,
        timeout=15,
    )

    assert result.returncode == 0, result.stderr
    assert (install_dir / "current").resolve() == install_dir / "releases/1.2.3-rc.1"
    assert (
        command_log.read_text(encoding="utf-8").splitlines()[0] == "https://api.example/prereleases"
    )


@pytest.mark.skipif(os.name != "posix", reason="installer lifecycle requires POSIX Bash")
@pytest.mark.parametrize("action", ["--update", "--reinstall"])
def test_update_and_reinstall_activate_new_release_without_replacing_user_data(tmp_path, action):
    install_dir = tmp_path / "opt/knx_to_openhab"
    previous_release = install_dir / "releases/1.2.2"
    (previous_release / "installer").mkdir(parents=True)
    (previous_release / "VERSION").write_text("1.2.2\n", encoding="ascii")
    (previous_release / "keep.txt").write_text("old immutable release", encoding="utf-8")
    (install_dir / "current").symlink_to("releases/1.2.2")

    config_dir = tmp_path / "etc/knx_to_openhab"
    data_dir = tmp_path / "var/lib/knx_to_openhab"
    backup_dir = tmp_path / "var/backups/knx_to_openhab"
    (data_dir / "jobs").mkdir(parents=True)
    config_dir.mkdir(parents=True)
    backup_dir.mkdir(parents=True)
    protected_files = {
        config_dir / "config.json": b'{"bind_host":"127.0.0.1","port":8123}\n',
        config_dir / "secrets.env": b"PASSWORD_HASH=external\n",
        data_dir / "generator.json": b'{"custom_rules":true}\n',
        data_dir / "jobs/jobs.json": b'{"job-1":{"status":"done"}}\n',
        backup_dir / "job-1.tar.gz": b"backup bytes stay outside releases",
    }
    for path, contents in protected_files.items():
        path.write_bytes(contents)

    script = _installer_copy(tmp_path)
    release_env = _release_downloads(tmp_path, version="1.2.3")
    environment, command_log = _install_artifact_environment(tmp_path, install_dir, release_env)
    environment.update(
        {
            "KNXOH_CONFIG_DIR": str(config_dir),
            "KNXOH_DATA_DIR": str(data_dir),
            "KNXOH_BACKUP_DIR": str(backup_dir),
        }
    )

    result = subprocess.run(
        ["bash", str(script), action],
        env=environment,
        capture_output=True,
        text=True,
        check=False,
        timeout=15,
    )

    assert result.returncode == 0, result.stderr
    assert (install_dir / "current").resolve() == install_dir / "releases/1.2.3"
    assert (previous_release / "keep.txt").read_text(encoding="utf-8") == "old immutable release"
    assert {path: path.read_bytes() for path in protected_files} == protected_files
    assert command_log.read_text(encoding="utf-8").splitlines()[0] == "https://api.example/stable"


@pytest.mark.skipif(os.name != "posix", reason="installer lifecycle requires POSIX Bash")
def test_update_reuses_complete_inactive_release_without_overwriting_it(tmp_path):
    install_dir = tmp_path / "opt/knx_to_openhab"
    active_release = install_dir / "releases/1.2.2"
    existing_release = install_dir / "releases/1.2.3"
    (active_release / "installer").mkdir(parents=True)
    (active_release / "VERSION").write_text("1.2.2\n", encoding="ascii")
    (install_dir / "current").symlink_to("releases/1.2.2")
    (existing_release / "installer").mkdir(parents=True)
    (existing_release / "web_ui").mkdir()
    (existing_release / "VERSION").write_text("1.2.3\n", encoding="ascii")
    (existing_release / "keep.txt").write_text("immutable complete release", encoding="utf-8")
    setup_path = existing_release / "installer/setup.sh"
    setup_path.write_text(
        "#!/usr/bin/env bash\n"
        'setup_root="${KNXOH_SETUP_ROOT:-$(cd "$(dirname "$0")/.." && pwd)}"\n'
        'version="$(tr -d \'\\r\\n\' < "$setup_root/VERSION")"\n'
        'ln -s "releases/$version" "$KNXOH_INSTALL_DIR/.repair-current"\n'
        'mv -Tf "$KNXOH_INSTALL_DIR/.repair-current" "$KNXOH_INSTALL_DIR/current"\n'
        'printf \'%s\\n\' "$*" > "$INSTALLER_SETUP_LOG"\n',
        encoding="utf-8",
    )
    (existing_release / "installer/web_ui_endpoint.py").write_text(
        "print('loopback')\nprint('127.0.0.1')\nprint('8085')\n", encoding="utf-8"
    )
    script = _installer_copy(tmp_path)
    release_env = _release_downloads(tmp_path)
    environment, command_log = _install_artifact_environment(tmp_path, install_dir, release_env)

    result = subprocess.run(
        ["bash", str(script), "--update"],
        env=environment,
        capture_output=True,
        text=True,
        check=False,
        timeout=15,
    )

    assert result.returncode == 0, result.stderr
    assert (install_dir / "current").resolve() == existing_release
    assert (existing_release / "keep.txt").read_text(
        encoding="utf-8"
    ) == "immutable complete release"
    assert Path(release_env["INSTALLER_SETUP_LOG"]).read_text(encoding="utf-8") == (
        "--repair --activate-existing\n"
    )
    assert command_log.read_text(encoding="utf-8").splitlines() == [
        "https://api.example/stable",
        "https://downloads.example/release.tar.gz",
        "https://downloads.example/release.sha256",
    ]


@pytest.mark.skipif(os.name != "posix", reason="installer lifecycle requires POSIX Bash")
@pytest.mark.parametrize("interrupted", [False, True])
def test_verified_repair_preserves_same_version_mode_and_explicit_interrupted_target(
    tmp_path, interrupted
):
    install_dir = tmp_path / "app"
    active = install_dir / "releases/1.2.3"
    (active / "installer").mkdir(parents=True)
    (active / "web_ui").mkdir()
    (active / "VERSION").write_text("1.2.3\n")
    (active / "installer/setup.sh").write_text("exit 99\n")
    (install_dir / "current").symlink_to(active)
    target = active
    if interrupted:
        target = install_dir / "releases/1.2.4"
        (target / "installer").mkdir(parents=True)
        (target / "VERSION").write_text("1.2.4\n")
        (target / "installer/setup.sh").write_text("exit 99\n")
        (target / ".install-incomplete").write_bytes(b"")
    script = _installer_copy(tmp_path)
    release_env = _release_downloads(tmp_path)
    environment, _ = _install_artifact_environment(tmp_path, install_dir, release_env)
    result = subprocess.run(
        ["bash", str(script), "--repair" if interrupted else "--update"],
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    expected = "--repair --activate-existing\n" if interrupted else "--repair\n"
    assert Path(release_env["INSTALLER_SETUP_LOG"]).read_text() == expected
    assert (install_dir / "current").resolve() == target


@pytest.mark.skipif(os.name != "posix", reason="installer lifecycle requires POSIX Bash")
def test_fresh_install_rejects_checksum_mismatch_before_setup_or_activation(tmp_path):
    install_dir = tmp_path / "opt/knx_to_openhab"
    script = _installer_copy(tmp_path)
    release_env = _release_downloads(tmp_path, corrupt_checksum=True)
    environment, _ = _install_artifact_environment(tmp_path, install_dir, release_env)

    result = subprocess.run(
        ["bash", str(script)],
        env=environment,
        capture_output=True,
        text=True,
        check=False,
        timeout=15,
    )

    assert result.returncode != 0
    assert "SHA-256 verification failed" in result.stderr
    assert not (install_dir / "current").exists()
    assert not Path(release_env["INSTALLER_SETUP_LOG"]).exists()


@pytest.mark.skipif(os.name != "posix", reason="installer lifecycle requires POSIX Bash")
def test_fresh_install_rejects_archive_traversal_even_with_matching_checksum(tmp_path):
    install_dir = tmp_path / "opt/knx_to_openhab"
    script = _installer_copy(tmp_path)
    release_env = _release_downloads(tmp_path)
    archive = Path(release_env["INSTALLER_TEST_ARCHIVE"])
    with tarfile.open(archive, "w:gz") as output:
        member = tarfile.TarInfo("knx_to_openhab-1.2.3/../../escaped.txt")
        member.size = len(b"escaped")
        output.addfile(member, io.BytesIO(b"escaped"))
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    checksum = Path(release_env["INSTALLER_TEST_CHECKSUM"])
    checksum.write_text(f"{digest}  {archive.name}\n", encoding="ascii")
    environment, _ = _install_artifact_environment(tmp_path, install_dir, release_env)

    result = subprocess.run(
        ["bash", str(script)],
        env=environment,
        capture_output=True,
        text=True,
        check=False,
        timeout=15,
    )

    assert result.returncode != 0
    assert "Unsafe or unexpected archive member" in result.stderr
    assert not (install_dir / "current").exists()
    assert not (tmp_path / "escaped.txt").exists()


@pytest.mark.skipif(os.name != "posix", reason="installer lifecycle requires POSIX Bash")
@pytest.mark.parametrize(
    ("option", "expected_urls"),
    [
        (
            "--repair",
            [
                "https://api.example/stable",
                "https://downloads.example/release.tar.gz",
                "https://downloads.example/release.sha256",
            ],
        ),
        (
            "--update",
            [
                "https://api.example/stable",
                "https://downloads.example/release.tar.gz",
                "https://downloads.example/release.sha256",
            ],
        ),
    ],
)
def test_existing_install_repair_preserves_user_data_and_never_replaces_active_release(
    tmp_path, option, expected_urls
):
    install_dir = tmp_path / "opt/knx_to_openhab"
    active_release = install_dir / "releases/1.2.3"
    (active_release / "installer").mkdir(parents=True)
    (active_release / "web_ui").mkdir()
    (active_release / "VERSION").write_text("1.2.3\n", encoding="ascii")
    (active_release / "installer/setup.sh").write_text(
        '#!/usr/bin/env bash\nprintf \'%s\\n\' "$*" > "$INSTALLER_SETUP_LOG"\n',
        encoding="utf-8",
    )
    (active_release / "installer/web_ui_endpoint.py").write_text(
        "print('loopback')\nprint('127.0.0.1')\nprint('8085')\n", encoding="utf-8"
    )
    (install_dir / "current").symlink_to("releases/1.2.3")
    script = _installer_copy(tmp_path)
    release_env = _release_downloads(tmp_path, version="1.2.4")
    config_dir = tmp_path / "etc/knx_to_openhab"
    config_dir.mkdir(parents=True)
    config = config_dir / "config.json"
    config.write_bytes(b'{"custom":"do not replace"}\n')
    release_env["INSTALLER_SETUP_LOG"] = str(tmp_path / "setup-args.log")
    environment, command_log = _install_artifact_environment(tmp_path, install_dir, release_env)
    environment["KNXOH_CONFIG_DIR"] = str(config_dir)

    result = subprocess.run(
        ["bash", str(script), option],
        env=environment,
        capture_output=True,
        text=True,
        check=False,
        timeout=15,
    )

    assert result.returncode == 0, result.stderr
    assert config.read_bytes() == b'{"custom":"do not replace"}\n'
    expected_setup_args = "--repair\n" if option == "--repair" else "\n"
    assert (
        Path(release_env["INSTALLER_SETUP_LOG"]).read_text(encoding="utf-8") == expected_setup_args
    )
    assert (install_dir / "current").resolve() == (
        install_dir / ("releases/1.2.3" if option == "--repair" else "releases/1.2.4")
    )
    recorded_urls = (
        command_log.read_text(encoding="utf-8").splitlines() if command_log.exists() else []
    )
    assert recorded_urls == expected_urls


@pytest.mark.skipif(
    os.name != "posix" or getattr(os, "geteuid", lambda: 0)() == 0,
    reason="requires a non-root POSIX account to model service-owned release files",
)
def test_repair_refuses_to_execute_service_writable_release_setup_as_root(tmp_path):
    install_dir = tmp_path / "opt/knx_to_openhab"
    release_dir = install_dir / "releases/1.2.3"
    (release_dir / "installer").mkdir(parents=True)
    marker = tmp_path / "setup-executed-as-root"
    (release_dir / "VERSION").write_text("1.2.3\n", encoding="ascii")
    (release_dir / "installer/setup.sh").write_text(
        f"#!/usr/bin/env bash\ntouch {marker}\n", encoding="utf-8"
    )
    (release_dir / "installer/setup.sh").chmod(0o666)
    (release_dir / "installer/web_ui_endpoint.py").write_text(
        "print('loopback')\nprint('127.0.0.1')\nprint('8085')\n", encoding="utf-8"
    )
    (install_dir / "current").symlink_to("releases/1.2.3")
    script = _installer_copy(tmp_path)
    release_env = _release_downloads(tmp_path)
    environment, _ = _install_artifact_environment(tmp_path, install_dir, release_env)

    result = subprocess.run(
        ["bash", str(script), "--repair"],
        env=environment,
        capture_output=True,
        text=True,
        check=False,
        timeout=15,
    )

    assert result.returncode != 0
    assert "release path is writable by the service account" in result.stderr
    assert not marker.exists()


@pytest.mark.skipif(os.name != "posix", reason="installer lifecycle requires POSIX Bash")
@pytest.mark.skipif(getattr(os, "geteuid", lambda: 0)() == 0, reason="requires a non-root account")
def test_repair_rejects_directory_symlink_with_service_writable_setup_script(tmp_path):
    install_dir = tmp_path / "opt/knx_to_openhab"
    release_dir = install_dir / "releases/1.2.3"
    payload_dir = release_dir / "payload/installer"
    payload_dir.mkdir(parents=True)
    marker = tmp_path / "symlinked-setup-executed"
    setup_path = payload_dir / "setup.sh"
    setup_path.write_text(f"#!/usr/bin/env bash\ntouch {marker}\n", encoding="utf-8")
    setup_path.chmod(0o666)
    (release_dir / "installer").symlink_to("payload/installer", target_is_directory=True)
    (release_dir / "VERSION").write_text("1.2.3\n", encoding="ascii")
    (release_dir / "installer/web_ui_endpoint.py").write_text(
        "print('loopback')\nprint('127.0.0.1')\nprint('8085')\n", encoding="utf-8"
    )
    (install_dir / "current").symlink_to("releases/1.2.3")
    script = _installer_copy(tmp_path)
    release_env = _release_downloads(tmp_path)
    environment, _ = _install_artifact_environment(tmp_path, install_dir, release_env)

    result = subprocess.run(
        ["bash", str(script), "--repair"],
        env=environment,
        capture_output=True,
        text=True,
        check=False,
        timeout=15,
    )

    assert result.returncode != 0
    assert "directory symlink" in result.stderr.lower()
    assert not marker.exists()


@pytest.mark.skipif(os.name != "posix", reason="installer lifecycle requires POSIX Bash")
def test_repair_rejects_release_under_service_writable_ancestor(tmp_path):
    writable_parent = tmp_path / "service-writable-parent"
    writable_parent.mkdir()
    writable_parent.chmod(0o777)
    install_dir = writable_parent / "opt/knx_to_openhab"
    release_dir = install_dir / "releases/1.2.3"
    (release_dir / "installer").mkdir(parents=True)
    marker = tmp_path / "ancestor-setup-executed"
    (release_dir / "installer/setup.sh").write_text(
        f"#!/usr/bin/env bash\ntouch {marker}\n", encoding="utf-8"
    )
    (release_dir / "installer/web_ui_endpoint.py").write_text(
        "print('loopback')\nprint('127.0.0.1')\nprint('8085')\n", encoding="utf-8"
    )
    (install_dir / "current").symlink_to("releases/1.2.3")
    script = _installer_copy(tmp_path)
    release_env = _release_downloads(tmp_path)
    environment, _ = _install_artifact_environment(tmp_path, install_dir, release_env)

    result = subprocess.run(
        ["bash", str(script), "--repair"],
        env=environment,
        capture_output=True,
        text=True,
        check=False,
        timeout=15,
    )

    assert result.returncode != 0
    assert "service-writable ancestor" in result.stderr.lower()
    assert not marker.exists()


@pytest.mark.skipif(os.name != "posix", reason="installer lifecycle requires POSIX Bash")
def test_privileged_repair_uses_verified_payload_not_swapped_installed_setup(tmp_path):
    install_dir = tmp_path / "opt/knx_to_openhab"
    release_dir = install_dir / "releases/1.2.3"
    (release_dir / "installer").mkdir(parents=True)
    setup_path = release_dir / "installer/setup.sh"
    setup_path.write_text("printf 'safe\\n' > \"$INSTALLER_SETUP_LOG\"\n", encoding="utf-8")
    (release_dir / "installer/web_ui_endpoint.py").write_text(
        "print('loopback')\nprint('127.0.0.1')\nprint('8085')\n", encoding="utf-8"
    )
    (install_dir / "current").symlink_to("releases/1.2.3")
    script = _installer_copy(tmp_path)
    release_env = _release_downloads(tmp_path)
    environment, _ = _install_artifact_environment(tmp_path, install_dir, release_env)
    malicious_marker = tmp_path / "reopened-script-executed"
    setup_log = tmp_path / "validated-script.log"
    environment.update(
        {
            "INSTALLER_SETUP_TARGET": str(setup_path),
            "INSTALLER_MALICIOUS_MARKER": str(malicious_marker),
            "INSTALLER_SETUP_LOG": str(setup_log),
        }
    )
    sudo = Path(environment["PATH"].split(os.pathsep)[0]) / "sudo"
    sudo.write_text(
        "#!/bin/sh\n"
        'if [ "$1" = "-n" ] && [ "$2" = "true" ]; then exit 0; fi\n'
        'if [ "$1" = "env" ]; then\n'
        '  replacement="$INSTALLER_SETUP_TARGET.replacement"\n'
        '  printf \'#!/usr/bin/env bash\\ntouch "%s"\\n\' "$INSTALLER_MALICIOUS_MARKER" '
        '> "$replacement"\n'
        '  mv "$replacement" "$INSTALLER_SETUP_TARGET"\n'
        '  shift; exec env "$@"\n'
        "fi\n"
        'exec "$@"\n',
        encoding="utf-8",
    )
    sudo.chmod(0o755)

    result = subprocess.run(
        ["bash", str(script), "--repair"],
        env=environment,
        capture_output=True,
        text=True,
        check=False,
        timeout=15,
    )

    assert result.returncode == 0, result.stderr
    assert not malicious_marker.exists()
    assert setup_log.read_text(encoding="utf-8") == "--repair\n"


@pytest.mark.skipif(os.name != "posix", reason="installer lifecycle requires POSIX Bash")
def test_legacy_repair_refuses_privileged_execution_and_directs_to_verified_update(tmp_path):
    install_dir = tmp_path / "opt/knx_to_openhab"
    (install_dir / "installer").mkdir(parents=True)
    marker = tmp_path / "legacy-setup-executed"
    (install_dir / "installer/setup.sh").write_text(
        f"#!/usr/bin/env bash\ntouch {marker}\n", encoding="utf-8"
    )
    (install_dir / "installer/web_ui_endpoint.py").write_text(
        "print('loopback')\nprint('127.0.0.1')\nprint('8085')\n", encoding="utf-8"
    )
    script = _installer_copy(tmp_path)
    release_env = _release_downloads(tmp_path)
    environment, _ = _install_artifact_environment(tmp_path, install_dir, release_env)

    result = subprocess.run(
        ["bash", str(script), "--repair"],
        env=environment,
        capture_output=True,
        text=True,
        check=False,
        timeout=15,
    )

    assert result.returncode != 0
    assert "Legacy flat installations cannot be safely repaired in place" in result.stderr
    assert "--update" in result.stderr
    assert not marker.exists()


@pytest.mark.skipif(os.name != "posix", reason="installer lifecycle requires POSIX Bash")
def test_repair_rejects_symlinked_release_root_before_privileged_cleanup(tmp_path):
    install_dir = tmp_path / "opt/knx_to_openhab"
    install_dir.mkdir(parents=True)
    external_releases = tmp_path / "external/releases"
    active_release = external_releases / "1.2.2"
    (active_release / "installer").mkdir(parents=True)
    (active_release / "VERSION").write_text("1.2.2\n", encoding="ascii")
    (active_release / "installer/setup.sh").write_text("exit 0\n", encoding="utf-8")
    staging = external_releases / ".1.2.3.staging.999"
    staging.mkdir(parents=True)
    sentinel = staging / "keep-me.txt"
    sentinel.write_text("outside the install root", encoding="utf-8")
    (install_dir / "releases").symlink_to(external_releases, target_is_directory=True)
    (install_dir / "current").symlink_to("releases/1.2.2")
    script = _installer_copy(tmp_path)
    release_env = _release_downloads(tmp_path)
    environment, command_log = _install_artifact_environment(tmp_path, install_dir, release_env)

    result = subprocess.run(
        ["bash", str(script), "--repair"],
        env=environment,
        capture_output=True,
        text=True,
        check=False,
        timeout=15,
    )

    assert result.returncode != 0
    assert sentinel.read_text(encoding="utf-8") == "outside the install root"
    assert "releases directory must not be a symlink" in result.stderr.lower()
    commands = command_log.read_text().splitlines() if command_log.exists() else []
    assert not any(line.startswith("rm -rf") for line in commands)


@pytest.mark.skipif(os.name != "posix", reason="installer lifecycle requires POSIX Bash")
@pytest.mark.parametrize("active_previous_release", [True, False])
def test_repair_activates_release_interrupted_before_current_switch_without_touching_user_data(
    tmp_path, active_previous_release
):
    install_dir = tmp_path / "opt/knx_to_openhab"
    previous_release = install_dir / "releases/1.0.0"
    interrupted_release = install_dir / "releases/1.1.0"
    (previous_release / "installer").mkdir(parents=True)
    (previous_release / "VERSION").write_text("1.0.0\n", encoding="ascii")
    (previous_release / "installer/setup.sh").write_text("exit 0\n", encoding="utf-8")
    (previous_release / "installer/web_ui_endpoint.py").write_text(
        "print('loopback')\nprint('127.0.0.1')\nprint('8085')\n", encoding="utf-8"
    )
    if active_previous_release:
        (install_dir / "current").symlink_to("releases/1.0.0")
    (interrupted_release / "installer").mkdir(parents=True)
    for name in (
        "setup.sh",
        "knxohui.service",
        "knxohui-backup-cleanup.service",
        "knxohui-backup-cleanup.timer",
        "launch_web.sh",
        "launch_backup_cleanup.sh",
        "set_ui_password.py",
        "service_update.sh",
        "migrate_sudoers.sh",
    ):
        source = ROOT / "installer" / name
        target = interrupted_release / "installer" / name
        target.write_text(_shell_fixture_text(source), encoding="utf-8", newline="\n")
    (interrupted_release / "VERSION").write_text("1.1.0\n", encoding="ascii")
    (interrupted_release / "installer/web_ui_endpoint.py").write_text(
        "print('loopback')\nprint('127.0.0.1')\nprint('8085')\n", encoding="utf-8"
    )
    (interrupted_release / ".install-incomplete").write_text("1.1.0\n", encoding="ascii")

    config_dir = tmp_path / "etc/knx_to_openhab"
    data_dir = tmp_path / "var/lib/knx_to_openhab"
    backup_dir = tmp_path / "var/backups/knx_to_openhab"
    config_dir.mkdir(parents=True)
    data_dir.mkdir(parents=True)
    backup_dir.mkdir(parents=True)
    paths_file = config_dir / "paths.env"
    paths_file.write_text(
        f"KNXOH_INSTALL_DIR={install_dir}\n"
        f"KNXOH_CONFIG_DIR={config_dir}\n"
        f"KNXOH_DATA_DIR={data_dir}\n"
        f"KNXOH_BACKUP_DIR={backup_dir}\n",
        encoding="utf-8",
    )
    protected_files = {
        config_dir / "config.json": b'{"custom":"retain"}\n',
        config_dir / "secrets.env": b"SECRET_HASH=retain\n",
        data_dir / "generator.json": b'{"rules":"retain"}\n',
        data_dir / "jobs/jobs.json": b'{"job-1":{"input":"retain"}}\n',
        backup_dir / "job.tar.gz": b"backup bytes",
    }
    (data_dir / "jobs").mkdir()
    for path, contents in protected_files.items():
        path.write_bytes(contents)

    command_dir = tmp_path / "repair-system-commands"
    command_dir.mkdir()
    command_log = tmp_path / "repair-system-commands.log"
    stubs = {
        "sudo": (
            "#!/bin/sh\n"
            'printf \'%s \' "$@" >> "$INSTALLER_COMMAND_LOG"\nprintf \'\\n\' >> "$INSTALLER_COMMAND_LOG"\n'
            'if [ "$1" = "-n" ]; then exit 0; fi\n'
            'if [ "$1" = env ]; then shift; exec env "$@"; fi\n'
            'if [ "$1" = ln ]; then shift; exec ln "$@"; fi\n'
            'if [ "$1" = mv ] && [ "$2" = -Tf ]; then shift 2; exec mv -Tf "$@"; fi\n'
            'if [ "$1" = rm ]; then shift; exec rm "$@"; fi\n'
            'if [ "$1" = python3 ]; then shift; exec python3 "$@"; fi\n'
            "exit 0\n"
        ),
        "dpkg": (
            "#!/bin/sh\nprintf 'dpkg ' >> \"$INSTALLER_COMMAND_LOG\"\n"
            'printf \'%s \' "$@" >> "$INSTALLER_COMMAND_LOG"\n'
            "printf '\\n' >> \"$INSTALLER_COMMAND_LOG\"\n"
            "printf '%s\\n' 'Status: install ok installed'\n"
        ),
        "getent": "#!/bin/sh\nexit 1\n",
        "id": "#!/bin/sh\nexit 1\n",
    }
    for name, contents in stubs.items():
        stub = command_dir / name
        stub.write_text(contents, encoding="utf-8")
        stub.chmod(0o755)
    script = _installer_copy(tmp_path)
    environment = os.environ.copy()
    environment.update(
        {
            "ALLOW_ROOT": "1",
            "KNXOH_INSTALL_DIR": str(install_dir),
            "KNXOH_CONFIG_DIR": str(config_dir),
            "KNXOH_DATA_DIR": str(data_dir),
            "KNXOH_BACKUP_DIR": str(backup_dir),
            "KNXOH_PATHS_FILE": str(paths_file),
            "INSTALLER_COMMAND_LOG": str(command_log),
            "PATH": f"{command_dir}{os.pathsep}{environment['PATH']}",
        }
    )

    result = subprocess.run(
        [
            "bash",
            str(interrupted_release / "installer/setup.sh"),
            "--repair",
            "--activate-existing",
        ],
        env=environment,
        capture_output=True,
        text=True,
        check=False,
        timeout=20,
    )

    assert result.returncode == 0, result.stderr
    assert (install_dir / "current").resolve() == interrupted_release
    assert not (interrupted_release / ".install-incomplete").exists()
    assert {path: path.read_bytes() for path in protected_files} == protected_files
    operations = command_log.read_text(encoding="utf-8")
    assert "migrate_runtime_data.py" not in operations
    assert "migrate_sudoers.sh" not in operations


@pytest.mark.skipif(os.name != "posix", reason="installer lifecycle requires POSIX Bash")
@pytest.mark.parametrize("failure_point", ["groupadd", "restart"])
def test_failed_interrupted_repair_keeps_previous_current_release(tmp_path, failure_point):
    install_dir = tmp_path / "opt/knx_to_openhab"
    previous_release = install_dir / "releases/1.0.0"
    interrupted_release = install_dir / "releases/1.1.0"
    (previous_release / "installer").mkdir(parents=True)
    (previous_release / "VERSION").write_text("1.0.0\n", encoding="ascii")
    (interrupted_release / "installer").mkdir(parents=True)
    setup_path = interrupted_release / "installer/setup.sh"
    setup_path.write_text(
        _shell_fixture_text(ROOT / "installer/setup.sh"),
        encoding="utf-8",
        newline="\n",
    )
    (interrupted_release / "VERSION").write_text("1.1.0\n", encoding="ascii")
    (interrupted_release / ".install-incomplete").write_text("1.1.0\n", encoding="ascii")
    for name in ("knxohui.service", "launch_web.sh"):
        source = ROOT / "installer" / name
        target = interrupted_release / "installer" / name
        target.write_text(_shell_fixture_text(source), encoding="utf-8", newline="\n")
    (install_dir / "current").symlink_to("releases/1.0.0")

    config_dir = tmp_path / "etc/knx_to_openhab"
    config_dir.mkdir(parents=True)
    paths_file = config_dir / "paths.env"
    paths_file.write_text(
        f"KNXOH_INSTALL_DIR={install_dir}\n"
        f"KNXOH_CONFIG_DIR={config_dir}\n"
        f"KNXOH_DATA_DIR={tmp_path / 'var/lib/knx_to_openhab'}\n"
        f"KNXOH_BACKUP_DIR={tmp_path / 'var/backups/knx_to_openhab'}\n",
        encoding="utf-8",
    )

    command_dir = tmp_path / "commands"
    command_dir.mkdir()
    (command_dir / "sudo").write_text(
        "#!/bin/sh\n"
        'if [ "$1" = "groupadd" ] && [ "$INSTALLER_FAIL_POINT" = "groupadd" ]; then exit 1; fi\n'
        'if [ "$1" = "systemctl" ] && [ "$2" = "restart" ]; then\n'
        '  readlink -f "$INSTALLER_INSTALL_DIR/current" >> "$INSTALLER_RESTART_TARGETS"\n'
        '  if [ "$INSTALLER_FAIL_POINT" = "restart" ] && '
        '[ "$(readlink -f "$INSTALLER_INSTALL_DIR/current")" = "$INSTALLER_INTERRUPTED_RELEASE" ]; '
        "then exit 1; fi\n"
        "fi\n"
        'if [ "$1" = "ln" ]; then shift; exec ln "$@"; fi\n'
        'if [ "$1" = "mv" ] && [ "$2" = "-Tf" ]; then shift 2; exec mv -Tf "$@"; fi\n'
        'if [ "$1" = "rm" ]; then shift; exec rm "$@"; fi\n'
        "exit 0\n",
        encoding="utf-8",
    )
    (command_dir / "getent").write_text(
        '#!/bin/sh\n[ "$INSTALLER_FAIL_POINT" != "groupadd" ]\n', encoding="utf-8"
    )
    (command_dir / "id").write_text("#!/bin/sh\nexit 1\n", encoding="utf-8")
    for command in command_dir.iterdir():
        command.chmod(0o755)
    environment = os.environ.copy()
    environment.update(
        {
            "KNXOH_INSTALL_DIR": str(install_dir),
            "KNXOH_CONFIG_DIR": str(config_dir),
            "KNXOH_DATA_DIR": str(tmp_path / "var/lib/knx_to_openhab"),
            "KNXOH_BACKUP_DIR": str(tmp_path / "var/backups/knx_to_openhab"),
            "KNXOH_PATHS_FILE": str(paths_file),
            "INSTALLER_FAIL_POINT": failure_point,
            "INSTALLER_INSTALL_DIR": str(install_dir),
            "INSTALLER_INTERRUPTED_RELEASE": str(interrupted_release),
            "INSTALLER_RESTART_TARGETS": str(tmp_path / "restart-targets.log"),
            "PATH": f"{command_dir}{os.pathsep}{environment['PATH']}",
        }
    )

    result = subprocess.run(
        ["bash", str(setup_path), "--repair", "--activate-existing"],
        env=environment,
        capture_output=True,
        text=True,
        check=False,
        timeout=15,
    )

    assert result.returncode != 0
    assert (install_dir / "current").resolve() == previous_release
    assert (interrupted_release / ".install-incomplete").exists()
    if failure_point == "restart":
        restart_targets = (
            (tmp_path / "restart-targets.log").read_text(encoding="utf-8").splitlines()
        )
        assert restart_targets[-1] == str(previous_release)


@pytest.mark.skipif(os.name != "posix", reason="installer lifecycle requires POSIX Bash")
def test_failed_normal_setup_update_rolls_current_back_and_keeps_recovery_marker(tmp_path):
    from installer.config_migrations import create_snapshot

    source_root = tmp_path / "source"
    installer_dir = source_root / "installer"
    installer_dir.mkdir(parents=True)
    setup_script = installer_dir / "setup.sh"
    setup_script.write_text(
        _shell_fixture_text(ROOT / "installer/setup.sh"),
        encoding="utf-8",
        newline="\n",
    )
    (source_root / "VERSION").write_text("0.1.0\n", encoding="ascii")
    (source_root / "requirements.txt").write_text("# mocked setup test\n", encoding="utf-8")
    (source_root / "scripts").mkdir()
    (source_root / "scripts/build_release.py").write_text(
        (ROOT / "scripts/build_release.py").read_text(encoding="utf-8"),
        encoding="utf-8",
        newline="\n",
    )

    install_dir = tmp_path / "opt/knx_to_openhab"
    previous_release = install_dir / "releases/0.0.9"
    (previous_release / "installer").mkdir(parents=True)
    (previous_release / "VERSION").write_text("0.0.9\n", encoding="ascii")
    (install_dir / "current").symlink_to("releases/0.0.9")
    config_dir = tmp_path / "etc/knx_to_openhab"
    data_dir = tmp_path / "var/lib/knx_to_openhab"
    backup_dir = tmp_path / "var/backups/knx_to_openhab"
    config_dir.mkdir(parents=True)
    data_dir.mkdir(parents=True)
    backup_dir.mkdir(parents=True)
    config = config_dir / "config.json"
    config.write_text('{"port":8085}\n', encoding="utf-8")
    paths_file = config_dir / "paths.env"
    paths_file.write_text(
        f"KNXOH_INSTALL_DIR={install_dir}\n"
        f"KNXOH_CONFIG_DIR={config_dir}\n"
        f"KNXOH_DATA_DIR={data_dir}\n"
        f"KNXOH_BACKUP_DIR={backup_dir}\n",
        encoding="utf-8",
    )
    original_paths = paths_file.read_bytes()
    migration_snapshot = create_snapshot([config, paths_file], config_dir / ".installer-state")

    command_dir = tmp_path / "commands"
    command_dir.mkdir()
    (command_dir / "sudo").write_text(
        "#!/bin/sh\n"
        'if [ "$1" = "python3" ] && [ "${2##*/}" = "config_migrations.py" ]; then '
        'shift; exec python3 "$@"; fi\n'
        'if [ "$1" = "rsync" ]; then\n'
        '  previous=""; destination=""\n'
        '  for argument in "$@"; do previous="$destination"; destination="$argument"; done\n'
        '  mkdir -p "$destination/installer"\n'
        '  cp "$INSTALLER_TEST_CONFIG_MIGRATIONS" "$destination/installer/config_migrations.py"\n'
        "  exit 0\n"
        "fi\n"
        'if [ "${1##*/}" = "python" ] && [ "${2##*/}" = "migrate_runtime_data.py" ]; then\n'
        '  printf \'%s\\n\' "$*" >> "$INSTALLER_SETUP_COMMAND_LOG"\n'
        '  previous=""; snapshot_file=""\n'
        '  for argument in "$@"; do\n'
        '    if [ "$previous" = "--snapshot-path-file" ]; then snapshot_file="$argument"; fi\n'
        '    previous="$argument"\n'
        "  done\n"
        '  printf \'%s\\n\' "$INSTALLER_MIGRATION_SNAPSHOT_DIR" > "$snapshot_file"\n'
        '  printf \'{"port":9090}\\n\' > "$INSTALLER_CONFIG_FILE"\n'
        "  printf 'migrated paths\\n' > \"$INSTALLER_PATHS_FILE\"\n"
        "  exit 0\n"
        "fi\n"
        'if [ "$1" = "systemctl" ]; then\n'
        '  if [ "$2" = "is-active" ]; then exit 1; fi\n'
        '  if [ "$2" = "restart" ] && [ "$3" = "knxohui.service" ]; then exit 1; fi\n'
        "  exit 0\n"
        "fi\n"
        'if [ "$1" = "ln" ]; then shift; exec ln "$@"; fi\n'
        'if [ "$1" = "mv" ]; then shift; exec mv "$@"; fi\n'
        'if [ "$1" = "touch" ] || [ "$1" = "mkdir" ] || [ "$1" = "rm" ]; then '
        'exec "$@"; fi\n'
        "exit 0\n",
        encoding="utf-8",
    )
    for name, contents in (
        ("getent", "#!/bin/sh\nexit 0\n"),
        ("id", "#!/bin/sh\nexit 0\n"),
        ("rsync", "#!/bin/sh\nexit 0\n"),
    ):
        (command_dir / name).write_text(contents, encoding="utf-8")
    for command in command_dir.iterdir():
        command.chmod(0o755)
    environment = os.environ.copy()
    environment.update(
        {
            "KNXOH_INSTALL_DIR": str(install_dir),
            "KNXOH_CONFIG_DIR": str(config_dir),
            "KNXOH_DATA_DIR": str(data_dir),
            "KNXOH_BACKUP_DIR": str(backup_dir),
            "KNXOH_PATHS_FILE": str(paths_file),
            "INSTALLER_TEST_CONFIG_MIGRATIONS": str(ROOT / "installer/config_migrations.py"),
            "INSTALLER_MIGRATION_SNAPSHOT_DIR": str(migration_snapshot),
            "INSTALLER_CONFIG_FILE": str(config),
            "INSTALLER_PATHS_FILE": str(paths_file),
            "INSTALLER_SETUP_COMMAND_LOG": str(tmp_path / "setup-commands.log"),
            "PATH": f"{command_dir}{os.pathsep}{environment['PATH']}",
        }
    )

    result = subprocess.run(
        ["bash", str(setup_script)],
        env=environment,
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )

    failed_release = install_dir / "releases/0.1.0"
    assert result.returncode != 0
    assert (install_dir / "current").resolve() == previous_release
    assert (failed_release / ".install-incomplete").exists()
    assert config.read_text(encoding="utf-8") == '{"port":8085}\n'
    assert paths_file.read_bytes() == original_paths
    migration_commands = (tmp_path / "setup-commands.log").read_text(encoding="utf-8")
    assert "--defer-legacy-cleanup" in migration_commands
    assert "--snapshot-backup-dir" in migration_commands
    assert "--cleanup-legacy" not in migration_commands


@pytest.mark.skipif(os.name != "posix", reason="installer lifecycle requires POSIX Bash")
@pytest.mark.parametrize(
    ("first_install", "fail_restore_restart", "fail_remove_current"),
    [
        (False, False, False),
        (True, False, False),
        (False, True, False),
        (True, False, True),
    ],
)
def test_repair_rolls_back_persisted_interrupted_migration_transaction(
    tmp_path, first_install, fail_restore_restart, fail_remove_current
):
    from installer.config_migrations import create_snapshot

    install_dir = tmp_path / "opt/knx_to_openhab"
    previous_release = install_dir / "releases/1.0.0"
    interrupted_release = install_dir / "releases/1.1.0"
    if not first_install:
        previous_release.mkdir(parents=True)
    (interrupted_release / "installer").mkdir(parents=True)
    (install_dir / "current").symlink_to("releases/1.1.0")
    for relative in (
        "setup.sh",
        "config_migrations.py",
        "knxohui.service",
        "launch_web.sh",
    ):
        source = ROOT / "installer" / relative
        target = interrupted_release / "installer" / relative
        target.write_text(_shell_fixture_text(source), encoding="utf-8", newline="\n")
    (interrupted_release / "VERSION").write_text("1.1.0\n", encoding="ascii")
    (interrupted_release / ".install-incomplete").write_text("1.1.0\n", encoding="ascii")

    config_dir = tmp_path / "etc/knx_to_openhab"
    config_dir.mkdir(parents=True)
    data_dir = tmp_path / "var/lib/knx_to_openhab"
    backup_dir = tmp_path / "var/backups/knx_to_openhab"
    paths_file = config_dir / "paths.env"
    original_paths = (
        f"KNXOH_INSTALL_DIR={install_dir}\n"
        f"KNXOH_CONFIG_DIR={config_dir}\n"
        f"KNXOH_DATA_DIR={data_dir}\n"
        f"KNXOH_BACKUP_DIR={backup_dir}\n"
    ).encode()
    if not first_install:
        paths_file.write_bytes(original_paths)
    config_file = config_dir / "config.json"
    config_file.write_bytes(b'{"original":true}\n')
    state_root = config_dir / ".installer-state"
    snapshot_dir = create_snapshot([config_file, paths_file], state_root)
    config_file.write_bytes(b'{"partially_migrated":true}\n')
    if not first_install:
        paths_file.write_bytes(b"migrated paths\n")
    (interrupted_release / ".migration-snapshot-path").write_text(
        f"{snapshot_dir}\n", encoding="utf-8"
    )
    (interrupted_release / ".installer-transaction-state").write_text(
        f"{'' if first_install else previous_release}\n"
        f"{0 if first_install else 1}\n"
        f"{0 if first_install else 1}\n"
        f"{0 if first_install else 1}\n"
        f"{0 if first_install else 1}\n"
        f"{0 if first_install else 1}\n",
        encoding="utf-8",
    )

    system_state = tmp_path / "systemd-state"
    system_state.mkdir()
    if not first_install:
        for unit in (
            "knxohui.service",
            "knxohui-backup-cleanup.service",
            "knxohui-backup-cleanup.timer",
        ):
            if unit != "knxohui-backup-cleanup.service":
                (system_state / f"{unit}.active").touch()
                (system_state / f"{unit}.enabled").touch()
    command_log = tmp_path / "systemctl.log"
    command_dir = tmp_path / "commands"
    command_dir.mkdir()
    (command_dir / "sudo").write_text(
        "#!/bin/sh\n"
        'if [ "$1" = "systemctl" ]; then\n'
        '  action="$2"; unit="${4:-${3:-}}"\n'
        '  printf \'%s %s\\n\' "$action" "$(readlink -f "$INSTALLER_INSTALL_DIR/current" 2>/dev/null || echo none)" '
        '>> "$INSTALLER_SYSTEMCTL_LOG"\n'
        '  case "$action" in\n'
        '    is-active) [ -f "$INSTALLER_STATE_DIR/$unit.active" ] ;;\n'
        '    is-enabled) [ -f "$INSTALLER_STATE_DIR/$unit.enabled" ] ;;\n'
        '    restart) [ "$INSTALLER_FAIL_RESTORE_RESTART" != 1 ] || exit 1; '
        'touch "$INSTALLER_STATE_DIR/$unit.active" ;;\n'
        '    start) if [ "$unit" = "knxohui-backup-cleanup.service" ]; then :; '
        'else touch "$INSTALLER_STATE_DIR/$unit.active"; fi ;;\n'
        '    stop) rm -f "$INSTALLER_STATE_DIR/$unit.active" ;;\n'
        '    enable) touch "$INSTALLER_STATE_DIR/$unit.enabled" ;;\n'
        '    disable) rm -f "$INSTALLER_STATE_DIR/$unit.enabled" ;;\n'
        "    *) exit 0 ;;\n"
        "  esac\n"
        "  exit $?\n"
        "fi\n"
        'if [ "$1" = "python3" ]; then shift; exec python3 "$@"; fi\n'
        'if [ "$1" = "ln" ]; then shift; exec ln "$@"; fi\n'
        'if [ "$1" = "mv" ]; then shift; exec mv "$@"; fi\n'
        'if [ "$1" = "rm" ]; then\n'
        '  for argument in "$@"; do\n'
        '    if [ "$INSTALLER_FAIL_REMOVE_CURRENT" = 1 ] && '
        '[ "$argument" = "$INSTALLER_INSTALL_DIR/current" ]; then exit 1; fi\n'
        "  done\n"
        '  shift; exec rm "$@"\n'
        "fi\n"
        "exit 0\n",
        encoding="utf-8",
    )
    (command_dir / "sudo").chmod(0o755)
    environment = os.environ.copy()
    environment.update(
        {
            "KNXOH_INSTALL_DIR": str(install_dir),
            "KNXOH_CONFIG_DIR": str(config_dir),
            "KNXOH_DATA_DIR": str(data_dir),
            "KNXOH_BACKUP_DIR": str(backup_dir),
            "KNXOH_PATHS_FILE": str(paths_file),
            "KNXOH_SETUP_ROOT": str(interrupted_release),
            "INSTALLER_INSTALL_DIR": str(install_dir),
            "INSTALLER_STATE_DIR": str(system_state),
            "INSTALLER_SYSTEMCTL_LOG": str(command_log),
            "INSTALLER_FAIL_RESTORE_RESTART": "1" if fail_restore_restart else "0",
            "INSTALLER_FAIL_REMOVE_CURRENT": "1" if fail_remove_current else "0",
            "PATH": f"{command_dir}{os.pathsep}{environment['PATH']}",
        }
    )

    setup_script = interrupted_release / "installer/setup.sh"
    result = subprocess.run(
        ["bash", str(setup_script), "--repair", "--activate-existing"],
        env=environment,
        capture_output=True,
        text=True,
        check=False,
        timeout=20,
    )

    if fail_remove_current:
        assert result.returncode != 0
        current_link = install_dir / "current"
        assert current_link.is_symlink()
        assert current_link.resolve() == interrupted_release
        assert interrupted_release.exists()
        assert (interrupted_release / ".install-incomplete").exists()
        assert "Could not remove the interrupted current release link" in result.stderr
    elif fail_restore_restart:
        assert result.returncode != 0
        assert (install_dir / "current").resolve() == previous_release
        assert interrupted_release.exists()
        assert (interrupted_release / ".install-incomplete").exists()
        assert "Could not restore the pre-install service state" in result.stderr
    elif first_install:
        assert result.returncode != 0
        current_link = install_dir / "current"
        assert not current_link.exists() and not current_link.is_symlink()
        assert not previous_release.exists()
    else:
        assert result.returncode == 0, result.stdout + result.stderr
        assert (install_dir / "current").resolve() == previous_release
    if not fail_restore_restart and not fail_remove_current:
        assert not interrupted_release.exists()
    assert config_file.read_bytes() == b'{"original":true}\n'
    if first_install:
        assert not paths_file.exists()
    else:
        assert paths_file.read_bytes() == original_paths
    restart_targets = [
        line.split(maxsplit=1)[1]
        for line in command_log.read_text(encoding="utf-8").splitlines()
        if line.startswith("restart ")
    ]
    if not first_install:
        assert restart_targets[-1] == str(previous_release)


@pytest.mark.skipif(os.name != "posix", reason="installer lifecycle requires POSIX Bash")
def test_successful_repair_preserves_disabled_and_inactive_existing_units(tmp_path):
    install_dir = tmp_path / "opt/knx_to_openhab"
    release = install_dir / "releases/1.0.0"
    installer_dir = release / "installer"
    installer_dir.mkdir(parents=True)
    for name in (
        "setup.sh",
        "knxohui.service",
        "knxohui-backup-cleanup.service",
        "knxohui-backup-cleanup.timer",
        "launch_web.sh",
        "launch_backup_cleanup.sh",
        "set_ui_password.py",
        "service_update.sh",
        "migrate_sudoers.sh",
    ):
        source = ROOT / "installer" / name
        target = installer_dir / name
        target.write_text(_shell_fixture_text(source), encoding="utf-8", newline="\n")
    (release / "VERSION").write_text("1.0.0\n", encoding="ascii")
    (install_dir / "current").symlink_to("releases/1.0.0")
    config_dir = tmp_path / "etc/knx_to_openhab"
    config_dir.mkdir(parents=True)
    paths_file = config_dir / "paths.env"
    paths_file.write_text(
        f"KNXOH_INSTALL_DIR={install_dir}\n"
        f"KNXOH_CONFIG_DIR={config_dir}\n"
        f"KNXOH_DATA_DIR={tmp_path / 'var/lib/knx_to_openhab'}\n"
        f"KNXOH_BACKUP_DIR={tmp_path / 'var/backups/knx_to_openhab'}\n",
        encoding="utf-8",
    )
    unit_dir = tmp_path / "systemd-units"
    unit_dir.mkdir()
    for name in (
        "knxohui.service",
        "knxohui-backup-cleanup.service",
        "knxohui-backup-cleanup.timer",
    ):
        (unit_dir / name).write_text("# already installed\n", encoding="utf-8")
    setup_script = tmp_path / "setup.sh"
    setup_script.write_text(
        _shell_fixture_text(ROOT / "installer/setup.sh").replace(
            "/etc/systemd/system", str(unit_dir)
        ),
        encoding="utf-8",
        newline="\n",
    )

    command_dir = tmp_path / "commands"
    command_dir.mkdir()
    command_log = tmp_path / "systemctl.log"
    (command_dir / "sudo").write_text(
        "#!/bin/sh\n"
        'if [ "$1" = "systemctl" ]; then\n'
        '  printf \'%s %s\\n\' "$2" "${4:-${3:-}}" >> "$INSTALLER_SYSTEMCTL_LOG"\n'
        '  case "$2" in is-active|is-enabled) exit 1 ;; esac\n'
        "  exit 0\n"
        "fi\n"
        'if [ "$1" = "bash" ]; then exit 0; fi\n'
        "exit 0\n",
        encoding="utf-8",
    )
    (command_dir / "sudo").chmod(0o755)
    for name in ("getent", "id"):
        (command_dir / name).write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        (command_dir / name).chmod(0o755)
    environment = os.environ.copy()
    environment.update(
        {
            "KNXOH_INSTALL_DIR": str(install_dir),
            "KNXOH_CONFIG_DIR": str(config_dir),
            "KNXOH_DATA_DIR": str(tmp_path / "var/lib/knx_to_openhab"),
            "KNXOH_BACKUP_DIR": str(tmp_path / "var/backups/knx_to_openhab"),
            "KNXOH_PATHS_FILE": str(paths_file),
            "KNXOH_SETUP_ROOT": str(release),
            "INSTALLER_SYSTEMCTL_LOG": str(command_log),
            "PATH": f"{command_dir}{os.pathsep}{environment['PATH']}",
        }
    )

    result = subprocess.run(
        ["bash", str(setup_script), "--repair"],
        env=environment,
        capture_output=True,
        text=True,
        check=False,
        timeout=20,
    )

    assert result.returncode == 0, result.stderr
    actions = [line.split()[0] for line in command_log.read_text(encoding="utf-8").splitlines()]
    assert not set(actions) & {"enable", "start", "restart", "stop", "disable"}


@pytest.mark.skipif(os.name != "posix", reason="installer lifecycle requires POSIX Bash")
def test_failed_setup_restores_previously_active_ui_and_backup_cleanup_units(tmp_path):
    install_dir = tmp_path / "opt/knx_to_openhab"
    config_dir = tmp_path / "etc/knx_to_openhab"
    data_dir = tmp_path / "var/lib/knx_to_openhab"
    backup_dir = tmp_path / "var/backups/knx_to_openhab"
    config_dir.mkdir(parents=True)
    paths_file = config_dir / "paths.env"
    paths_file.write_text(
        f"KNXOH_INSTALL_DIR={install_dir}\n"
        f"KNXOH_CONFIG_DIR={config_dir}\n"
        f"KNXOH_DATA_DIR={data_dir}\n"
        f"KNXOH_BACKUP_DIR={backup_dir}\n",
        encoding="utf-8",
    )

    state_dir = tmp_path / "systemd-state"
    state_dir.mkdir()
    initially_active = (
        "knxohui.service",
        "knxohui-backup-cleanup.service",
        "knxohui-backup-cleanup.timer",
    )
    for unit in initially_active:
        (state_dir / f"{unit}.active").touch()
    command_dir = tmp_path / "commands"
    command_dir.mkdir()
    (command_dir / "sudo").write_text(
        "#!/bin/sh\n"
        'if [ "$1" = "systemctl" ]; then\n'
        '  action="$2"; unit="${4:-${3:-}}"\n'
        '  case "$action" in\n'
        '    is-active) [ -f "$INSTALLER_STATE_DIR/$unit.active" ] ;;\n'
        '    is-enabled) [ -f "$INSTALLER_STATE_DIR/$unit.enabled" ] ;;\n'
        '    stop) rm -f "$INSTALLER_STATE_DIR/$unit.active" ;;\n'
        '    disable) rm -f "$INSTALLER_STATE_DIR/$unit.enabled" ;;\n'
        '    start|restart) touch "$INSTALLER_STATE_DIR/$unit.active" ;;\n'
        '    enable) touch "$INSTALLER_STATE_DIR/$unit.enabled" ;;\n'
        "    *) exit 0 ;;\n"
        "  esac\n"
        "  exit $?\n"
        "fi\n"
        'if [ "$1" = "python3" ] && [ "$2" = "-m" ]; then exit 0; fi\n'
        'case "$1" in */pip) [ "$INSTALLER_FAIL_POINT" != "pip" ] || exit 1 ;; esac\n'
        'if [ "$1" = "getent" ]; then exit 0; fi\n'
        'if [ "$1" = "id" ]; then exit 0; fi\n'
        'if [ "$1" = "mkdir" ] || [ "$1" = "rm" ] || [ "$1" = "touch" ]; then exec "$@"; fi\n'
        "exit 0\n",
        encoding="utf-8",
    )
    for command in command_dir.iterdir():
        command.chmod(0o755)
    environment = os.environ.copy()
    environment.update(
        {
            "KNXOH_INSTALL_DIR": str(install_dir),
            "KNXOH_CONFIG_DIR": str(config_dir),
            "KNXOH_DATA_DIR": str(data_dir),
            "KNXOH_BACKUP_DIR": str(backup_dir),
            "KNXOH_PATHS_FILE": str(paths_file),
            "INSTALLER_STATE_DIR": str(state_dir),
            "INSTALLER_FAIL_POINT": "pip",
            "KNXOH_SETUP_ROOT": str(ROOT),
            "PATH": f"{command_dir}{os.pathsep}{environment['PATH']}",
        }
    )

    setup_script = tmp_path / "setup.sh"
    setup_script.write_text(
        _shell_fixture_text(ROOT / "installer/setup.sh"),
        encoding="utf-8",
        newline="\n",
    )
    result = subprocess.run(
        ["bash", str(setup_script)],
        env=environment,
        capture_output=True,
        text=True,
        check=False,
        timeout=20,
    )

    assert result.returncode != 0, result.stderr
    for unit in initially_active:
        assert (state_dir / f"{unit}.active").exists(), unit


@pytest.mark.skipif(os.name != "posix", reason="installer lifecycle requires POSIX Bash")
@pytest.mark.parametrize(
    ("option", "action"),
    [
        ("--update", "update"),
        ("--repair", "repair"),
        ("--reinstall", "reinstall"),
        ("--cancel", "cancel"),
    ],
)
def test_existing_install_plan_honors_explicit_lifecycle_choice(tmp_path, option, action):
    install_dir = tmp_path / "opt/knx_to_openhab"
    release = install_dir / "releases/0.1.0"
    release.mkdir(parents=True)
    (install_dir / "current").symlink_to("releases/0.1.0")
    script = _installer_copy(tmp_path)
    environment, command_log = _sandbox_environment(tmp_path, install_dir)

    result = subprocess.run(
        ["bash", str(script), "--plan", option],
        env=environment,
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )

    assert result.returncode == 0, result.stderr
    plan = json.loads(result.stdout)
    assert plan["action"] == action
    assert plan["channel"] == (None if action in {"repair", "cancel"} else "stable")
    assert plan["install_dir"] == str(install_dir)
    assert not command_log.exists()


@pytest.mark.skipif(os.name != "posix", reason="installer lifecycle requires POSIX Bash")
def test_repair_plan_recognizes_interrupted_release_staging(tmp_path):
    install_dir = tmp_path / "opt/knx_to_openhab"
    script = _installer_copy(tmp_path)
    (install_dir / "releases/.0.2.0.staging.1234").mkdir(parents=True)
    environment, command_log = _sandbox_environment(tmp_path, install_dir)

    result = subprocess.run(
        ["bash", str(script), "--plan", "--repair"],
        env=environment,
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )

    assert result.returncode == 0, result.stderr
    plan = json.loads(result.stdout)
    assert plan["action"] == "repair"
    assert plan["interrupted_install"] is True
    assert plan["channel"] == "stable"
    assert not command_log.exists()


@pytest.mark.skipif(os.name != "posix", reason="installer lifecycle requires POSIX Bash")
def test_existing_install_without_terminal_choice_refuses_before_system_writes(tmp_path):
    install_dir = tmp_path / "opt/knx_to_openhab"
    script = _installer_copy(tmp_path)
    release = install_dir / "releases/0.1.0"
    release.mkdir(parents=True)
    (install_dir / "current").symlink_to("releases/0.1.0")
    environment, command_log = _sandbox_environment(tmp_path, install_dir)
    result = subprocess.run(
        ["bash", str(script)],
        env=environment,
        input="",
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )

    assert result.returncode != 0
    assert "choose --update, --repair, --reinstall, or --cancel" in result.stderr
    assert not command_log.exists()


@pytest.mark.skipif(os.name != "posix", reason="installer lifecycle requires POSIX Bash")
def test_noninteractive_interrupted_install_requires_explicit_repair_before_cleanup(tmp_path):
    install_dir = tmp_path / "opt/knx_to_openhab"
    staging_dir = install_dir / "releases/.1.2.2.staging.1234"
    staging_dir.mkdir(parents=True)
    script = _installer_copy(tmp_path)
    release_env = _release_downloads(tmp_path)
    environment, command_log = _install_artifact_environment(tmp_path, install_dir, release_env)
    environment["KNXOH_NONINTERACTIVE"] = "1"

    result = subprocess.run(
        ["bash", str(script)],
        env=environment,
        input="",
        capture_output=True,
        text=True,
        check=False,
        timeout=15,
    )

    assert result.returncode != 0
    assert "choose --update, --repair, --reinstall, or --cancel" in result.stderr
    assert staging_dir.is_dir()
    assert not command_log.exists()


@pytest.mark.skipif(os.name != "posix", reason="installer lifecycle requires POSIX Bash")
@pytest.mark.parametrize("active_release", [True, False])
def test_setup_repair_preserves_external_data_and_recovers_interrupted_release(
    tmp_path, active_release
):
    install_dir = tmp_path / "opt/knx_to_openhab"
    release_dir = install_dir / "releases/0.1.0"
    (release_dir / "installer").mkdir(parents=True)
    if active_release:
        (install_dir / "current").symlink_to("releases/0.1.0")
    (release_dir / "VERSION").write_text("0.1.0\n", encoding="ascii")
    setup_source = ROOT / "installer/setup.sh"
    setup_path = release_dir / "installer/setup.sh"
    setup_path.write_text(_shell_fixture_text(setup_source), encoding="utf-8", newline="\n")
    for name in (
        "knxohui.service",
        "knxohui-backup-cleanup.service",
        "knxohui-backup-cleanup.timer",
        "launch_web.sh",
        "launch_backup_cleanup.sh",
        "set_ui_password.py",
        "service_update.sh",
        "migrate_sudoers.sh",
    ):
        source = ROOT / "installer" / name
        target = release_dir / "installer" / name
        target.write_text(_shell_fixture_text(source), encoding="utf-8", newline="\n")

    config_dir = tmp_path / "etc/knx_to_openhab"
    data_dir = tmp_path / "var/lib/knx_to_openhab"
    backup_dir = tmp_path / "var/backups/knx_to_openhab"
    config_dir.mkdir(parents=True)
    (data_dir / "jobs").mkdir(parents=True)
    backup_dir.mkdir(parents=True)
    paths_file = config_dir / "paths.env"
    paths_file.write_text(
        f"KNXOH_INSTALL_DIR={install_dir}\n"
        f"KNXOH_CONFIG_DIR={config_dir}\n"
        f"KNXOH_DATA_DIR={data_dir}\n"
        f"KNXOH_BACKUP_DIR={backup_dir}\n",
        encoding="utf-8",
    )
    protected_files = {
        config_dir / "config.json": b'{"port":8123,"custom":"keep"}\n',
        config_dir / "secrets.env": b"PASSWORD_HASH=private\n",
        data_dir / "generator.json": b'{"rules":"keep"}\n',
        data_dir / "jobs/jobs.json": b'{"job-1":{"input":"upload.knxproj"}}\n',
        backup_dir / "job-1.tar.gz": b"preserve backup bytes",
        paths_file: paths_file.read_bytes(),
    }
    for path, contents in protected_files.items():
        if path != paths_file:
            path.write_bytes(contents)

    command_dir = tmp_path / "repair-commands"
    command_dir.mkdir()
    command_log = tmp_path / "repair-commands.log"
    for command, status in (("sudo", 0), ("getent", 1), ("id", 1)):
        stub = command_dir / command
        stub.write_text(
            "#!/bin/sh\n"
            f"printf '%s' '{command} ' >> \"$INSTALLER_COMMAND_LOG\"\n"
            'printf \'%s \' "$@" >> "$INSTALLER_COMMAND_LOG"\n'
            "printf '\\n' >> \"$INSTALLER_COMMAND_LOG\"\n"
            'if [ "$1" = ln ]; then shift; exec ln "$@"; fi\n'
            'if [ "$1" = mv ] && [ "$2" = -Tf ]; then shift 2; exec mv -Tf "$@"; fi\n'
            f"exit {status}\n",
            encoding="utf-8",
        )
        stub.chmod(0o755)
    environment = os.environ.copy()
    environment.update(
        {
            "KNXOH_INSTALL_DIR": str(install_dir),
            "KNXOH_CONFIG_DIR": str(config_dir),
            "KNXOH_DATA_DIR": str(data_dir),
            "KNXOH_BACKUP_DIR": str(backup_dir),
            "KNXOH_PATHS_FILE": str(paths_file),
            "INSTALLER_COMMAND_LOG": str(command_log),
            "PATH": f"{command_dir}{os.pathsep}{environment['PATH']}",
        }
    )

    result = subprocess.run(
        ["bash", str(setup_path), "--repair"],
        env=environment,
        capture_output=True,
        text=True,
        check=False,
        timeout=15,
    )

    assert result.returncode == 0, result.stderr
    assert {path: path.read_bytes() for path in protected_files} == protected_files
    assert (install_dir / "current").resolve() == release_dir
    operations = command_log.read_text(encoding="utf-8")
    assert "systemctl" in operations
    assert "configure_auth.py" not in operations
    assert "migrate_runtime_data.py" not in operations
    assert "rsync" not in operations
    assert "chown -R" not in operations
