import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
INSTALLER = ROOT / "install.sh"
pytestmark = pytest.mark.skipif(shutil.which("bash") is None, reason="Bash is required")


def _source_environment(tmp_path):
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    environment = os.environ.copy()
    environment.update(
        {
            "INSTALLER_PATH": str(INSTALLER),
            "KNXOH_INSTALL_DIR": str(tmp_path / "install"),
            "KNXOH_CONFIG_DIR": str(tmp_path / "config"),
            "PATH": f"{fake_bin}{os.pathsep}{environment.get('PATH', '')}",
        }
    )
    return fake_bin, environment


def _run_sourced_installer(environment, command, *args):
    return subprocess.run(
        ["bash", "-c", 'source "$INSTALLER_PATH"; ' + command, "knxoh-test", *args],
        env=environment,
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )


def _write_executable(path, content):
    path.write_text(content, encoding="utf-8")
    path.chmod(0o755)


def _fake_curl(fake_bin, environment, release, *, exit_code=0):
    arguments_file = fake_bin / "curl-arguments.txt"
    environment.update(
        {
            "CURL_ARGUMENTS_FILE": str(arguments_file),
            "FAKE_RELEASE_JSON": json.dumps(release),
            "FAKE_CURL_EXIT": str(exit_code),
        }
    )
    _write_executable(
        fake_bin / "curl",
        '#!/bin/sh\nprintf \'%s\\n\' "$@" > "$CURL_ARGUMENTS_FILE"\n'
        'if [ "$FAKE_CURL_EXIT" -ne 0 ]; then exit "$FAKE_CURL_EXIT"; fi\n'
        'printf \'%s\' "$FAKE_RELEASE_JSON"\n',
    )
    return arguments_file


def _release(tag, *, prerelease=False, draft=False):
    return {"tag_name": tag, "prerelease": prerelease, "draft": draft}



def test_help_works_when_installer_is_piped_to_bash(tmp_path):
    _, environment = _source_environment(tmp_path)
    result = subprocess.run(
        ["bash", "-s", "--", "--help"],
        input=INSTALLER.read_text(encoding="utf-8"),
        env=environment,
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )

    assert result.returncode == 0, result.stderr
    assert "--version X.Y.Z" in result.stdout


def test_default_version_uses_latest_stable_release_endpoint(tmp_path):
    fake_bin, environment = _source_environment(tmp_path)
    arguments_file = _fake_curl(fake_bin, environment, _release("v1.4.0"))

    result = _run_sourced_installer(environment, 'resolve_release_version ""')

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "1.4.0"
    assert "/releases/latest" in arguments_file.read_text(encoding="utf-8")


def test_exact_prerelease_can_be_selected_explicitly(tmp_path):
    fake_bin, environment = _source_environment(tmp_path)
    arguments_file = _fake_curl(
        fake_bin,
        environment,
        _release("v1.4.0-rc.2", prerelease=True),
    )

    result = _run_sourced_installer(
        environment,
        'resolve_release_version "$1"',
        "1.4.0-rc.2",
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "1.4.0-rc.2"
    assert "/releases/tags/v1.4.0-rc.2" in arguments_file.read_text(encoding="utf-8")


def test_stable_build_metadata_is_not_misclassified_as_prerelease(tmp_path):
    fake_bin, environment = _source_environment(tmp_path)
    _fake_curl(fake_bin, environment, _release("v1.4.0+build-7"))

    result = _run_sourced_installer(
        environment,
        'resolve_release_version "1.4.0+build-7"',
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "1.4.0+build-7"


def test_latest_stable_endpoint_rejects_prerelease_metadata(tmp_path):
    fake_bin, environment = _source_environment(tmp_path)
    _fake_curl(fake_bin, environment, _release("v1.4.0-rc.2", prerelease=True))

    result = _run_sourced_installer(environment, 'resolve_release_version ""')

    assert result.returncode != 0
    assert "latest stable endpoint returned a prerelease" in result.stderr


@pytest.mark.parametrize(
    "release",
    [
        _release("v1.4.0", draft=True),
        _release("v1.4.0-rc.2", prerelease=False),
        _release("v1.4.0-rc.2", prerelease=True),
        _release("v01.4.0"),
    ],
)
def test_rejects_release_metadata_that_does_not_match_the_request(tmp_path, release):
    fake_bin, environment = _source_environment(tmp_path)
    _fake_curl(fake_bin, environment, release)

    result = _run_sourced_installer(
        environment,
        'resolve_release_version "$1"',
        "1.4.0",
    )

    assert result.returncode != 0


def test_exact_release_response_must_match_requested_version(tmp_path):
    fake_bin, environment = _source_environment(tmp_path)
    _fake_curl(fake_bin, environment, _release("v1.4.1"))

    result = _run_sourced_installer(environment, 'resolve_release_version "$1"', "1.4.0")

    assert result.returncode != 0
    assert "exact request" in result.stderr


def test_missing_release_fails_without_falling_back_to_main(tmp_path):
    fake_bin, environment = _source_environment(tmp_path)
    _fake_curl(fake_bin, environment, {}, exit_code=22)

    result = _run_sourced_installer(environment, 'resolve_release_version ""')

    assert result.returncode != 0
    assert "latest stable GitHub release" in result.stderr


@pytest.mark.parametrize(
    "args",
    [
        ("--version", "01.2.3"),
        ("--version", "1.2.3-01"),
        ("--version", "١.2.3"),
        ("--version", "1.2.3/evil"),
        ("--version",),
        ("--repair", "--version", "1.2.3"),
        ("--install", "--version", "1.2.3", "--version", "1.2.4"),
    ],
)
def test_invalid_or_unsupported_version_arguments_fail_in_parser(tmp_path, args):
    _, environment = _source_environment(tmp_path)

    result = _run_sourced_installer(environment, 'parse_install_mode "$@"', *args)

    assert result.returncode == 2


def test_valid_version_argument_is_available_to_install_and_update_modes(tmp_path):
    _, environment = _source_environment(tmp_path)

    result = _run_sourced_installer(
        environment,
        'parse_install_mode "$@"; printf "%s|%s" "$INSTALL_MODE" "$REQUESTED_VERSION"',
        "--update",
        "--version=1.2.3-rc.1",
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout == "update|1.2.3-rc.1"


def test_fresh_install_clones_the_selected_tag(tmp_path):
    fake_bin, environment = _source_environment(tmp_path)
    git_arguments = tmp_path / "git-arguments.txt"
    environment.update(
        {
            "REQUESTED_TAG": "v1.2.3",
            "GIT_ARGUMENTS_FILE": str(git_arguments),
        }
    )
    _write_executable(
        fake_bin / "git",
        '#!/bin/sh\nprintf \'%s\\n\' "$@" > "$GIT_ARGUMENTS_FILE"\n'
        'for target do :; done\n'
        'mkdir -p "$target"\n',
    )
    _write_executable(fake_bin / "sudo", "#!/bin/sh\nexit 0\n")

    result = _run_sourced_installer(
        environment,
        'INSTALL_MODE=install; RELEASE_TAG="$REQUESTED_TAG"; clone_repository',
    )

    assert result.returncode == 0, result.stderr
    arguments = git_arguments.read_text(encoding="utf-8")
    assert "--branch\nv1.2.3" in arguments
    assert "https://github.com/diddip21/knx_to_openhab.git" in arguments


def _fake_update_commands(fake_bin, environment, *, worktree_dirty=0, index_dirty=0):
    git_log = fake_bin.parent / "git-update.log"
    environment.update(
        {
            "GIT_UPDATE_LOG": str(git_log),
            "FAKE_WORKTREE_DIRTY": str(worktree_dirty),
            "FAKE_INDEX_DIRTY": str(index_dirty),
        }
    )
    _write_executable(fake_bin / "id", "#!/bin/sh\nexit 1\n")
    _write_executable(
        fake_bin / "git",
        '#!/bin/sh\nprintf \'%s\\n\' "$*" >> "$GIT_UPDATE_LOG"\n'
        'case "$*" in\n'
        '  *"diff --quiet HEAD --") exit "$FAKE_WORKTREE_DIRTY" ;;\n'
        '  *"diff --cached --quiet") exit "$FAKE_INDEX_DIRTY" ;;\n'
        '  *"fetch --depth 1 origin refs/tags/v1.2.3:refs/tags/v1.2.3") exit 0 ;;\n'
        '  *"rev-parse HEAD") printf \'%s\\n\' "${FAKE_CURRENT_COMMIT:-current}" ;;\n'
        '  *"rev-parse v1.2.3^{commit}") printf \'%s\\n\' "${FAKE_TARGET_COMMIT:-target}" ;;\n'
        '  *"checkout --detach v1.2.3") exit 0 ;;\n'
        '  *) exit 90 ;;\n'
        'esac\n',
    )
    return git_log


def test_update_fetches_and_checks_out_the_selected_tag(tmp_path):
    fake_bin, environment = _source_environment(tmp_path)
    git_log = _fake_update_commands(fake_bin, environment)

    result = _run_sourced_installer(
        environment,
        'INSTALL_MODE=update; RELEASE_TAG=v1.2.3; update_repository',
    )

    assert result.returncode == 0, result.stderr
    commands = git_log.read_text(encoding="utf-8")
    assert "fetch --depth 1 origin refs/tags/v1.2.3:refs/tags/v1.2.3" in commands
    assert "checkout --detach v1.2.3" in commands
    assert "pull" not in commands
    assert "main" not in commands


def test_update_stops_before_fetch_when_tracked_files_are_dirty(tmp_path):
    fake_bin, environment = _source_environment(tmp_path)
    git_log = _fake_update_commands(fake_bin, environment, worktree_dirty=1)

    result = _run_sourced_installer(
        environment,
        'INSTALL_MODE=update; RELEASE_TAG=v1.2.3; update_repository',
    )

    assert result.returncode == 1
    commands = git_log.read_text(encoding="utf-8")
    assert "diff --quiet HEAD --" in commands
    assert " fetch " not in commands
    assert "checkout" not in commands


def test_update_without_a_new_release_does_not_checkout_again(tmp_path):
    fake_bin, environment = _source_environment(tmp_path)
    git_log = _fake_update_commands(
        fake_bin,
        environment,
    )
    environment["FAKE_TARGET_COMMIT"] = "current"

    result = _run_sourced_installer(
        environment,
        'INSTALL_MODE=update; RELEASE_TAG=v1.2.3; update_repository',
    )

    assert result.returncode == 0, result.stderr
    commands = git_log.read_text(encoding="utf-8")
    assert "Release v1.2.3 is already installed." in result.stdout
    assert "checkout" not in commands
