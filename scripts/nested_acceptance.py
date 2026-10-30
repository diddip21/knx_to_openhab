"""Read-only, explicitly named WSL/nspawn acceptance preflight.

This is NOT a guest provisioner or evidence that namespaces work. A root-owned
receipt records the administrator's fresh-import decision; live identity/mount
checks supplement it. Actual sandbox probes and offline boot evidence are separate.
No default distribution, host command, account, unit or application is modified.
"""

from __future__ import annotations

import argparse
import configparser
import json
import re
import subprocess
from pathlib import Path

DISTRIBUTION = "KNXOH-Acceptance-20261030"
MACHINE = "knxoh-acceptance"
LOCATION = "C:/Users/Username/AppData/Local/Temp/opencode/knxoh-wsl-acceptance-20261030"
FIELDS = {
    "format",
    "provider",
    "distribution",
    "install_location",
    "outer_machine_id",
    "inner_machine_id",
    "machine",
    "nonce",
}


def decode_receipt(raw):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("Duplicate receipt key")
            result[key] = value
        return result

    if len(raw.encode()) > 4096:
        raise ValueError("Oversized receipt")
    return json.loads(raw, object_pairs_hook=unique)


def validate_receipt(receipt):
    if type(receipt) is not dict or set(receipt) != FIELDS:
        raise ValueError("Unexpected provider receipt schema")
    expected = {
        "provider": "fresh-wsl2-nspawn",
        "distribution": DISTRIBUTION,
        "install_location": LOCATION,
        "machine": MACHINE,
    }
    if type(receipt["format"]) is not int or receipt["format"] != 1:
        raise ValueError("Unsupported provider format")
    if any(receipt[k] != v for k, v in expected.items()):
        raise ValueError("Unapproved provider/distribution/location/machine")
    for key, length in (("nonce", 64), ("outer_machine_id", 32), ("inner_machine_id", 32)):
        value = receipt[key]
        if not isinstance(value, str) or not re.fullmatch(f"[0-9a-f]{{{length}}}", value):
            raise ValueError("Malformed provider identity")
        if not int(value, 16):
            raise ValueError("Zero provider identity")
    if receipt["outer_machine_id"] == receipt["inner_machine_id"]:
        raise ValueError("Outer and inner identities must differ")


def validate_registration(records):
    matches = [r for r in records if r.get("DistributionName") == DISTRIBUTION]
    if len(matches) != 1 or matches[0].get("Version") != 2:
        raise ValueError("Expected exactly one explicitly registered WSL2 guest")
    if str(matches[0].get("BasePath", "")).replace("\\", "/") != LOCATION:
        raise ValueError("WSL import location differs from approved fresh guest")


def registration():
    import winreg

    records = []
    with winreg.OpenKey(
        winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Lxss"
    ) as key:
        for index in range(winreg.QueryInfoKey(key)[0]):
            with winreg.OpenKey(key, winreg.EnumKey(key, index)) as sub:
                if winreg.QueryValueEx(sub, "DistributionName")[0] == DISTRIBUTION:
                    records.append(
                        {
                            name: winreg.QueryValueEx(sub, name)[0]
                            for name in ("DistributionName", "BasePath", "Version")
                        }
                    )
    return records


def _host_integration(observed):
    mounts = observed["mounts"]
    if not mounts or any(len(line.split(" - ")) != 2 for line in mounts.splitlines()):
        raise ValueError("Missing/malformed mount evidence")
    if any(line.split(" - ", 1)[1].split()[0] in ("9p", "drvfs") for line in mounts.splitlines()):
        raise ValueError("Windows filesystem is mounted")
    if observed["interop"] is not False:
        raise ValueError("Windows interoperability is enabled")


def validate_outer(receipt, observed):
    validate_receipt(receipt)
    if observed["machine_id"] != receipt["outer_machine_id"]:
        raise ValueError("Wrong outer guest")
    _host_integration(observed)
    config = configparser.ConfigParser()
    config.read_string(observed["wsl_conf"])
    for section, option in (
        ("automount", "enabled"),
        ("interop", "enabled"),
        ("interop", "appendWindowsPath"),
    ):
        if config.getboolean(section, option, fallback=True):
            raise ValueError("Host integration not explicitly disabled")


def validate_inner(receipt, observed):
    validate_receipt(receipt)
    if observed["machine_id"] != receipt["inner_machine_id"]:
        raise ValueError("Wrong inner guest")
    if any(
        observed[k] != v
        for k, v in {
            "pid1": "systemd",
            "container": "systemd-nspawn",
            "pid1_container": "systemd-nspawn",
        }.items()
    ):
        raise ValueError("Not the nested nspawn PID-1 manager")
    _host_integration(observed)


# Run only through explicit wsl.exe -d and systemd-run --machine. stdin avoids
# nested PowerShell/WSL quoting and never reads a mounted Windows source path.
OBSERVE = """import json
from pathlib import Path
def text(p):
    return Path(p).read_text().strip()
value = dict(machine_id=text('/etc/machine-id'),
             mounts=text('/proc/self/mountinfo'),
             interop=Path('/proc/sys/fs/binfmt_misc/WSLInterop').exists())
if INNER:
    value.update(pid1=text('/proc/1/comm'), container=text('/run/systemd/container'),
                 pid1_container=next((v.split('=',1)[1] for v in
                 Path('/proc/1/environ').read_bytes().decode().split('\\0')
                 if v.startswith('container=')), ''))
else:
    value['wsl_conf']=text('/etc/wsl.conf')
print(json.dumps(value))
"""


def preflight(receipt, *, run=subprocess.run):
    validate_receipt(receipt)  # BEFORE even a read-only WSL invocation
    base = ["wsl.exe", "-d", DISTRIBUTION, "--"]
    options = dict(text=True, capture_output=True, check=True, timeout=60)
    outer = json.loads(
        run([*base, "/usr/bin/python3", "-"], input="INNER=False\n" + OBSERVE, **options).stdout
    )
    validate_outer(receipt, outer)
    inner = json.loads(
        run(
            [
                *base,
                "/usr/bin/systemd-run",
                "--machine=" + MACHINE,
                "--wait",
                "--pipe",
                "--collect",
                "/usr/bin/python3",
                "-",
            ],
            input="INNER=True\n" + OBSERVE,
            **options,
        ).stdout
    )
    validate_inner(receipt, inner)
    return {"outer": outer, "inner": inner}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--receipt", required=True, type=Path)
    args = parser.parse_args()
    validate_registration(registration())
    print(json.dumps(preflight(decode_receipt(args.receipt.read_text())), indent=2))


if __name__ == "__main__":
    main()
