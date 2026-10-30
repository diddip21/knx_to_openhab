"""Privileged fixture effects, executed ONLY after the original inner guest guards.

Not a standalone guest entry point. Global fixture/repair/state/fs/admin bindings
come from the original fully verified harness/source, never from a candidate.
No repair, adoption, cleanup, package configuration or production replacement.
"""

import base64
import hashlib
import io
import json
import os
import socket
import ssl
import stat
import subprocess
import tarfile
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from types import ModuleType

from fixture_operator import HOSTS, AuthenticatedAPI, check_sequence, hosts_bytes, terminal

# Injected by guest_payload only AFTER full original tree/source/origin checks.
# Retain the injected objects, never import replacement production helpers.
fs: ModuleType | None = globals().get("fs")
fixture: ModuleType | None = globals().get("fixture")
repair: ModuleType | None = globals().get("repair")
state: ModuleType | None = globals().get("state")
admin: ModuleType | None = globals().get("admin")

CONTROL = Path("/root/knxoh-release-fixture")
CA = Path("/usr/local/share/ca-certificates/knxoh-release-fixture.crt")
UNIT = Path("/etc/systemd/system/knxoh-release-fixture.service")
JOURNAL = Path("/etc/knxoh acceptance config/.updater-state/journal.json")
SEED = Path("/usr/share/python-wheels/pip-24.0-py3-none-any.whl")
SEED_SHA256 = "e995a37590643450898cfa5bd5113831a547506cd545c335a409339d0c1e87ab"
ORIGINAL_CA_SHA256 = "e05a523d99de77c6b1f2c7b7c3af502c8378f29e6e8484358ec55f96b0972ad6"
STAGES = ("metadata", "download", "extract", "dependencies", "migrate")


def require(condition, message):
    if not condition:
        raise ValueError(message)


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def command(argv, timeout=30):
    return subprocess.run(
        argv,
        check=True,
        capture_output=True,
        text=True,
        timeout=timeout,
        env={"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8"},
    ).stdout


def show(unit):
    properties = "Id,LoadState,ActiveState,SubState,Result,MainPID,ControlPID,ControlGroup,InvocationID,Type,NotifyAccess,PrivateNetwork,ExecMainStatus,NRestarts,ExecStart"
    raw = command(
        [
            "/usr/bin/systemctl",
            "show",
            "--all",
            "--no-pager",
            "--property=" + properties,
            "--",
            unit,
        ]
    )
    return dict(line.split("=", 1) for line in raw.splitlines() if "=" in line)


def emit(event, **values):
    print(json.dumps(dict(event=event, **values), sort_keys=True), flush=True)


def no_outbound():
    require(
        set(p.name for p in Path("/sys/class/net").iterdir()) == {"lo"},
        "Unexpected inner interface",
    )
    require(len(Path("/proc/net/route").read_text().splitlines()) == 1, "Unexpected IPv4 route")
    for line in Path("/proc/net/ipv6_route").read_text().splitlines():
        require(line.split()[-1] == "lo", "Unexpected IPv6 interface/route")
    for name in HOSTS:
        if CONTROL.exists():
            addresses = {
                value[4][0] for value in socket.getaddrinfo(name, 443, type=socket.SOCK_STREAM)
            }
            require(addresses == {"127.0.0.1"}, "Off-loopback fixture resolution")


def private_effect_mounts():
    from scripts.nested_acceptance import _mounts

    mounts = list(_mounts(Path("/proc/self/mountinfo").read_text()))
    roots = [m for m in mounts if m[1] == "/"]
    require(
        len(roots) == 1
        and roots[0][0] == "/var/lib/machines/knxoh-acceptance"
        and roots[0][2] == "ext4",
        "Wrong private guest root mount",
    )
    effects = (CONTROL, CA, UNIT, Path("/etc/hosts"), Path("/etc/ssl/certs"))
    for _, target, *_ in mounts:
        if target != "/":
            require(
                not any(Path(target) == p or Path(target) in p.parents for p in effects),
                "Fixture effect path is a foreign/shared bind mount",
            )


def runtime_identity():
    require(
        digest(fs.read_regular(SEED, 2 * 1024 * 1024)) == SEED_SHA256,
        "Unexpected actual ensurepip seed",
    )
    expected = {
        "python3": "3.12.3-0ubuntu2.1",
        "python3.12": "3.12.3-1ubuntu0.17",
        "python3.12-venv": "3.12.3-1ubuntu0.17",
        "python3-pip-whl": "24.0+dfsg-1ubuntu1.3",
        "ca-certificates": "20260816ubuntu0.24.04.1",
    }
    packages = command(["/usr/bin/dpkg-query", "-W", "-f=${Package} ${Version}\n", *expected])
    require(
        dict(line.split() for line in packages.splitlines()) == expected,
        "Unexpected runtime packages",
    )
    require(
        Path("/proc/sys/kernel/random/boot_id").read_text().strip() == repair.BOOT_ID,
        "Unexpected reboot",
    )


def metadata(info):
    return dict(
        uid=info.st_uid,
        gid=info.st_gid,
        mode=oct(stat.S_IMODE(info.st_mode)),
        kind=(
            "directory"
            if stat.S_ISDIR(info.st_mode)
            else "file" if stat.S_ISREG(info.st_mode) else "other"
        ),
        device=info.st_dev,
        inode=info.st_ino,
        links=info.st_nlink,
        size=info.st_size,
    )


def worker_read(path, uid, gid, limit=65536):
    before = path.lstat()
    require(
        stat.S_ISREG(before.st_mode)
        and before.st_nlink == 1
        and before.st_uid == uid
        and before.st_gid == gid
        and before.st_size <= limit,
        "Unsafe exact worker artifact",
    )
    # Ancestors are checked separately against the exact original path metadata.
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        require(metadata(os.fstat(fd)) == metadata(before), "Worker file changed before read")
        raw = os.read(fd, limit + 1)
        require(
            len(raw) == before.st_size and metadata(os.fstat(fd)) == metadata(before),
            "Worker artifact changed",
        )
    finally:
        os.close(fd)
    require(metadata(path.lstat()) == metadata(before), "Worker path changed")
    return raw


def check_parent_inventory(actual, original, own_directories, own_files=()):
    expected = {
        **original,
        "children": sorted(set(original["children"]) | set(own_directories) | set(own_files)),
        "links": original["links"] + len(set(own_directories) - set(original["children"])),
    }
    require(actual == expected, "Unknown parent entry/identity; no adoption or prefix exemption")


def preserve(baseline, *, before_first=False, own_root=None):
    """Use original scoped evidence; NEVER recurse root collector into worker trees."""
    original = baseline["DIRECT_OBSERVATIONS"]
    initial = repair.snapshot_tree(Path(str(repair.INITIAL)))
    require(
        len(initial) == 3354 and initial == original["initial"],
        "Original 3354-entry release changed",
    )
    installed = Path("/usr/local/libexec/knx_to_openhab")
    require(
        repair.snapshot_tree(installed) == original["selected_strict_snapshots"][str(installed)],
        "Installed bundle identities changed",
    )
    require(
        repair.snapshot_tree(state.OUTPUT)
        == original["selected_strict_snapshots"][str(state.OUTPUT)],
        "Generated sentinels changed",
    )
    for event in ("HISTORICAL_ARTIFACTS", "NEW_PROBE_ARTIFACTS"):
        expected = baseline[event]
        request = expected["request"]
        require(
            request
            in ("5c4f51f8-2bdf-4e2e-ac71-cfb3897397b0", "dd13accd-c549-467c-b26d-4c2c25a797db"),
            "Unknown retained probe identity",
        )
        for name, value in expected["metadata"].items():
            require(metadata(Path(name).lstat()) == value, "Retained exact probe metadata changed")
        prep = state.PREPARATION / ("acceptance-" + request)
        candidate = state.BASE / "releases" / ("acceptance-" + request)
        require(
            digest(fs.read_regular(candidate / "installer/config_migrations.py", 65536))
            == expected["candidate_script_sha256"],
            "Retained probe script changed",
        )
        for name, field in (("heartbeat", "heartbeat_sha256"), ("probe.json", "probe_sha256")):
            raw = worker_read(prep / "migrate/output" / name, 997, 988)
            require(digest(raw) == expected[field], "Retained worker bytes changed")
        for stage in STAGES:
            values = show("knxohupdate-" + request + "-" + stage + ".service")
            require(
                values["MainPID"] == values["ControlPID"] == "0" and values["ControlGroup"] == "",
                "Retained hostile stage live",
            )
    selected = original["selected_strict_snapshots"][str(state.CONFIG)]
    for path in (state.CONFIG / n for n in ("paths.env", "secrets.env", "generator.json")):
        require(
            repair.inventory_entry(path, details=True) == selected[str(path)],
            "Protected setting identity changed",
        )
    config = state.CONFIG / "config.json"
    if before_first:
        require(
            repair.inventory_entry(config, details=True) == selected[str(config)],
            "Original config identity changed",
        )
    else:
        raw = fs.read_regular(CONTROL / "config.original", 1024 * 1024)
        require(digest(raw) == selected[str(config)]["sha256"], "Original config receipt mismatch")
        require(
            json.loads(fs.read_regular(config, 1024 * 1024)) == json.loads(raw),
            "Protected config/sibling schema values changed",
        )
        info = config.lstat()
        require(
            (info.st_uid, info.st_gid, stat.S_IMODE(info.st_mode))
            == (
                selected[str(config)]["uid"],
                selected[str(config)]["gid"],
                selected[str(config)]["mode"],
            ),
            "Protected config owner/mode changed",
        )
    footprint = state.collect_inventory(details=True, entry_reader=repair.inventory_entry)
    expected_entries = original["footprint"]["entries"]
    transactions = []
    for phase in (
        "stable-update",
        "no-update",
        "checksum-rejection",
        "migration-rejection",
        "retry",
    ):
        path = CONTROL / (phase + ".result.json")
        if path.exists():
            record = json.loads(fs.read_regular(path, 2 * 1024 * 1024))
            require(record["phase"] == phase, "Unexpected own phase result")
            transactions.append(record["root"])
    if own_root is not None:
        transactions.append(own_root)
    own_requests = {record["request_id"] for record in transactions}
    own_releases = set()
    for record in transactions:
        require(
            record["phase"] in ("committed", "rolled-back"),
            "Nonterminal own transaction cannot explain parent changes",
        )
        if record["phase"] == "committed":
            require(
                record["candidate"]
                in (str(state.BASE / "releases/0.1.1"), str(state.BASE / "releases/0.1.2")),
                "Unknown own committed candidate",
            )
            own_releases.add(Path(record["candidate"]).name)
    for parent, directories, files in (
        (state.BASE, set(), set()),
        (state.CONFIG, set(), set()),
        (state.BASE / "releases", own_releases, set()),
        (state.PREPARATION, own_requests, set()),
        (
            state.DATA,
            {"update"} if own_requests else set(),
            {"sessions.sqlite3"} if own_requests else set(),
        ),
    ):
        check_parent_inventory(
            footprint["entries"][str(parent)], expected_entries[str(parent)], directories, files
        )
    if own_requests:
        info = (state.DATA / "sessions.sqlite3").lstat()
        require(
            stat.S_ISREG(info.st_mode)
            and info.st_nlink == 1
            and (info.st_uid, info.st_gid, stat.S_IMODE(info.st_mode)) == (999, 989, 0o600),
            "Unsafe actual authentication session store",
        )
    # Exact fixed component/external footprint; do not adopt observed replacements.
    for name, value in expected_entries.items():
        path = Path(name)
        fixed = name.startswith(
            (
                "/etc/systemd/",
                "/usr/lib/systemd/",
                "/etc/sudoers.d/",
                "/etc/tmpfiles.d/",
                "/usr/local/sbin/",
            )
        ) or path in (
            state.DATA / "jobs",
            state.DATA / "staging",
            state.DATA / "generated",
            state.BACKUPS,
            Path("/root/knxoh-acceptance-login.json"),
            state.LOCK,
            Path("/etc/knx_to_openhab/paths.env"),
            Path("/etc/knx_to_openhab"),
        )
        if fixed:
            require(
                footprint["entries"].get(name) == value,
                "Original fixed external/component receipt changed",
            )
    for key in ("accounts", "aliases", "groups", "hostname"):
        require(footprint[key] == original["footprint"][key], "Original identity/alias changed")
    emit(
        "PRESERVED",
        initial_entries=3354,
        installed_files=len(admin.BUNDLE),
        exact_probe_trees=2,
        protected=True,
    )


def exclusive(path, raw, mode=0o600):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, mode)
    with os.fdopen(fd, "wb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())


def save_json(path, value):
    exclusive(path, (json.dumps(value, sort_keys=True, indent=2) + "\n").encode())


def unit_bytes():
    return b"""[Unit]
Description=Own nested release acceptance HTTPS fixture
After=network.target
[Service]
Type=simple
User=root
Group=root
ExecStart=/usr/bin/python3 -I -B /root/knxoh-release-fixture/release_fixture_server.py
WorkingDirectory=/
UMask=0077
NoNewPrivileges=yes
ProtectSystem=strict
ProtectHome=read-only
PrivateTmp=yes
PrivateDevices=yes
RestrictAddressFamilies=AF_INET AF_UNIX
IPAddressDeny=any
IPAddressAllow=127.0.0.1/32
CapabilityBoundingSet=CAP_NET_BIND_SERVICE
AmbientCapabilities=CAP_NET_BIND_SERVICE
LimitCORE=0
TasksMax=64
MemoryMax=1G
Restart=no
"""


def prepare(manifest, files):
    require(
        not any(p.exists() or p.is_symlink() for p in (CONTROL, CA, UNIT)),
        "Unknown existing fixture; no adoption/wipe",
    )
    unit = show("knxoh-release-fixture.service")
    require(unit["LoadState"] == "not-found", "Existing fixture unit")
    with socket.socket() as test:
        test.bind(("127.0.0.1", 443))  # Refuse an occupied listener, never kill it.
    hosts = fs.read_regular(Path("/etc/hosts"), 65536)
    changed = hosts_bytes(hosts)
    original_ca = fs.read_regular(Path("/etc/ssl/certs/ca-certificates.crt"), 2 * 1024 * 1024)
    require(
        digest(original_ca) == ORIGINAL_CA_SHA256, "Original read-only system CA receipt changed"
    )
    require(len(manifest["wheels"]) == 29, "Incomplete wheelhouse")
    require(set(files) == {*manifest["files"], "fixture.json"}, "Incomplete transported files")
    decoded = {name: base64.b64decode(raw, validate=True) for name, raw in files.items()}
    for name, value in manifest["files"].items():
        require(
            value == dict(size=len(decoded[name]), sha256=digest(decoded[name])),
            "Transport fixture mismatch",
        )
    CONTROL.mkdir(mode=0o700)
    exclusive(CONTROL / "hosts.original", hosts)
    exclusive(CONTROL / "hosts.installed", changed)
    exclusive(CONTROL / "ca-bundle.original", original_ca)
    exclusive(
        CONTROL / "config.original", fs.read_regular(state.CONFIG / "config.json", 1024 * 1024)
    )
    before = dict(
        hosts=metadata(Path("/etc/hosts").lstat()),
        ca_bundle_sha256=digest(
            fs.read_regular(Path("/etc/ssl/certs/ca-certificates.crt"), 2 * 1024 * 1024)
        ),
        ca_bundle=metadata(Path("/etc/ssl/certs/ca-certificates.crt").lstat()),
        unit_absent=True,
        ca_absent=True,
    )
    save_json(CONTROL / "before.json", before)
    for name, raw in decoded.items():
        path = Path(name)
        require(
            not path.is_absolute()
            and ".." not in path.parts
            and "\\" not in name
            and ":" not in name,
            "Unsafe transported member",
        )
        target = CONTROL / path
        target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        exclusive(target, raw)
    # Full wheels are separately compared with the ORIGINAL inner wheelhouse.
    for item in manifest["wheels"]:
        original = fs.read_regular(Path("/opt/knxoh-wheelhouse") / item["name"], 64 * 1024 * 1024)
        require(
            digest(original) == item["sha256"] and len(original) == item["size"],
            "Original wheel receipt mismatch",
        )
    exclusive(CONTROL / "phase", b"stable-update\n")
    command(
        [
            "/usr/bin/openssl",
            "req",
            "-x509",
            "-newkey",
            "rsa:2048",
            "-nodes",
            "-days",
            "7",
            "-subj",
            "/CN=KNXOH own inner fixture CA",
            "-addext",
            "basicConstraints=critical,CA:TRUE",
            "-addext",
            "keyUsage=critical,keyCertSign,cRLSign",
            "-keyout",
            str(CONTROL / "ca.key"),
            "-out",
            str(CONTROL / "ca.crt"),
        ]
    )
    command(
        [
            "/usr/bin/openssl",
            "req",
            "-new",
            "-newkey",
            "rsa:2048",
            "-nodes",
            "-subj",
            "/CN=knxoh-release-fixture",
            "-keyout",
            str(CONTROL / "server.key"),
            "-out",
            str(CONTROL / "server.csr"),
        ]
    )
    extensions = (
        "basicConstraints=critical,CA:FALSE\nkeyUsage=critical,digitalSignature,keyEncipherment\nextendedKeyUsage=serverAuth\nsubjectAltName="
        + ",".join("DNS:" + h for h in HOSTS)
        + "\n"
    )
    exclusive(CONTROL / "server.ext", extensions.encode())
    command(
        [
            "/usr/bin/openssl",
            "x509",
            "-req",
            "-in",
            str(CONTROL / "server.csr"),
            "-CA",
            str(CONTROL / "ca.crt"),
            "-CAkey",
            str(CONTROL / "ca.key"),
            "-set_serial",
            "1",
            "-days",
            "7",
            "-extfile",
            str(CONTROL / "server.ext"),
            "-out",
            str(CONTROL / "server.crt"),
        ]
    )
    for path in CONTROL.glob("*.key"):
        path.chmod(0o600)
    # Preserve the original private hosts inode. Mount checks above refuse any
    # host/outer bind at this path, even if its bytes happen to match.
    require(
        fs.read_regular(Path("/etc/hosts"), 65536) == hosts, "Hosts changed before fixture install"
    )
    fd = os.open("/etc/hosts", os.O_WRONLY | os.O_NOFOLLOW)
    with os.fdopen(fd, "wb") as stream:
        require(metadata(os.fstat(stream.fileno())) == before["hosts"], "Hosts identity changed")
        stream.write(changed)
        stream.truncate()
        stream.flush()
        os.fsync(stream.fileno())
    exclusive(CA, fs.read_regular(CONTROL / "ca.crt", 65536), 0o644)
    command(["/usr/sbin/update-ca-certificates"], timeout=60)
    exclusive(UNIT, unit_bytes(), 0o644)
    command(["/usr/bin/systemctl", "daemon-reload"])
    command(["/usr/bin/systemctl", "start", "--", "knxoh-release-fixture.service"])
    require(
        show("knxoh-release-fixture.service")["ActiveState"] == "active", "Fixture did not start"
    )
    verify_fixture(manifest)
    tls_proof()
    tls_files = {
        name: dict(
            metadata=metadata((CONTROL / name).lstat()),
            sha256=digest(fs.read_regular(CONTROL / name, 65536)),
        )
        for name in (
            "ca.key",
            "ca.crt",
            "server.key",
            "server.crt",
            "untrusted.key",
            "untrusted.crt",
        )
    }
    save_json(
        CONTROL / "prepare-fixture.result.json",
        dict(
            phase="prepare-fixture",
            fixture=manifest,
            system_tls=True,
            tls_files=tls_files,
            installed_bundle_sha256=digest(
                fs.read_regular(Path("/etc/ssl/certs/ca-certificates.crt"), 2 * 1024 * 1024)
            ),
        ),
    )
    emit("PREPARED", system_tls=True, wheel_count=29, updater_invoked=False)


def verify_fixture(manifest):
    require(fs.read_regular(UNIT, 65536) == unit_bytes(), "Fixture unit changed")
    require(
        fs.read_regular(Path("/etc/hosts"), 65536)
        == fs.read_regular(CONTROL / "hosts.installed", 65536),
        "Fixture hosts changed",
    )
    require(
        fs.read_regular(CA, 65536) == fs.read_regular(CONTROL / "ca.crt", 65536),
        "Fixture CA changed",
    )
    require(
        json.loads(fs.read_regular(CONTROL / "fixture.json", 1024 * 1024)) == manifest,
        "Installed fixture map changed",
    )
    for name, value in manifest["files"].items():
        raw = fs.read_regular(CONTROL / name, 64 * 1024 * 1024)
        require(
            value == dict(size=len(raw), sha256=digest(raw)),
            "Installed trusted fixture file changed",
        )
    for name in (CONTROL, *CONTROL.parents):
        info = name.lstat()
        require(
            stat.S_ISDIR(info.st_mode) and info.st_uid == 0 and not info.st_mode & 0o022,
            "Worker-writable fixture control",
        )
    no_outbound()
    prepared_path = CONTROL / "prepare-fixture.result.json"
    if prepared_path.exists():
        prepared = json.loads(fs.read_regular(prepared_path, 2 * 1024 * 1024))
        require(
            digest(fs.read_regular(Path("/etc/ssl/certs/ca-certificates.crt"), 2 * 1024 * 1024))
            == prepared["installed_bundle_sha256"],
            "Installed system trust bundle changed",
        )
        for name, value in prepared["tls_files"].items():
            path = CONTROL / name
            require(
                dict(metadata=metadata(path.lstat()), sha256=digest(fs.read_regular(path, 65536)))
                == value,
                "Own fixture TLS file identity/bytes changed",
            )


def tls_proof():
    """Real stdlib + actual seed/default pip session; no certificate override."""
    # Generate a separate UNTRUSTED endpoint with the correct names. Neither
    # client changes verify/CA options: both must reject its chain.
    untrusted_key = CONTROL / "untrusted.key"
    untrusted_cert = CONTROL / "untrusted.crt"
    if not untrusted_key.exists() and not untrusted_cert.exists():
        command(
            [
                "/usr/bin/openssl",
                "req",
                "-x509",
                "-newkey",
                "rsa:2048",
                "-nodes",
                "-days",
                "7",
                "-subj",
                "/CN=untrusted acceptance negative",
                "-addext",
                "subjectAltName=" + ",".join("DNS:" + h for h in HOSTS),
                "-keyout",
                str(untrusted_key),
                "-out",
                str(untrusted_cert),
            ]
        )
        untrusted_key.chmod(0o600)
    # Fixed trusted server module loaded by absolute root path, not candidate.
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "fixture_tls_negative", CONTROL / "release_fixture_server.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    negative = module.make_server({}, untrusted_cert, untrusted_key, port=0)
    thread = threading.Thread(target=negative.serve_forever, daemon=True)
    thread.start()
    query = r"""
import sys,ssl,ensurepip,urllib.request,urllib.error,json,hashlib
from pathlib import Path
wheel=Path(ensurepip._get_packages()['pip'].wheel_path)
assert str(wheel)=='/usr/share/python-wheels/pip-24.0-py3-none-any.whl'
assert hashlib.sha256(wheel.read_bytes()).hexdigest()=='e995a37590643450898cfa5bd5113831a547506cd545c335a409339d0c1e87ab'
sys.path.insert(0,str(wheel))
from pip._internal.commands.install import InstallCommand
from pip._internal.network.session import PipSession
from pip._vendor.requests.exceptions import SSLError
from pip._vendor import certifi
command=InstallCommand(name='install',summary='',isolated=True)
options=command.parser.get_default_values()
assert command.parser.get_option('--index-url').default=='https://pypi.org/simple'
assert options.index_url=='https://pypi.org/simple'
assert not options.trusted_hosts and options.cert is None and options.client_cert is None
assert certifi.where()=='/etc/ssl/certs/ca-certificates.crt'
# The seed's no-argument session is its actual verified default client, without
# a cache directory. This also matches production's existing --no-cache-dir
# policy without changing argv/options or writing an unrelated root pip cache.
session=PipSession()
assert session.verify is True
assert type(session.get_adapter('https://pypi.org/simple/')).__name__=='HTTPAdapter'
opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
urls=['https://api.github.com/repos/diddip21/knx_to_openhab/releases/latest','https://pypi.org/simple/']
for url in urls:
 with opener.open(url,timeout=10) as response:
  assert response.status==200 and response.read(1048576)
 response=session.get(url,timeout=10)
 assert response.status_code==200 and response.content
for url in ['https://127.0.0.1/','https://pypi.org:NEGATIVE_PORT/simple/']:
 try:
  opener.open(url,timeout=10)
 except urllib.error.URLError as error:
  assert isinstance(error.reason,ssl.SSLCertVerificationError)
 else: raise AssertionError('stdlib negative TLS accepted')
 try:
  session.get(url,timeout=10)
 except SSLError: pass
 else: raise AssertionError('actual pip negative TLS accepted')
session.close()
print(json.dumps(dict(stdlib_github_pypi=True,actual_seed_default_session_github_pypi=True,hostname_rejected=True,untrusted_chain_rejected=True)))
""".replace("NEGATIVE_PORT", str(negative.server_port))
    try:
        result = subprocess.run(
            ["/usr/bin/python3", "-I", "-B", "-"],
            input=query,
            check=True,
            capture_output=True,
            text=True,
            timeout=90,
            env={"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8", "HOME": "/root"},
        )
        emit("SYSTEM_TLS", **json.loads(result.stdout))
    finally:
        negative.shutdown()
        thread.join(timeout=5)
        negative.server_close()


def protected_record():
    from installer.update_core.state import _decode_record

    raw = fs.read_regular(JOURNAL, 2 * 1024 * 1024)
    value = json.loads(raw)
    _decode_record(value, fixture.expected_paths())  # Original decoder; no state/store mutation.
    return value


def health(version):
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open("http://127.0.0.1:8085/api/health", timeout=10) as response:
        require(
            response.status == 200
            and json.loads(response.read(4097)) == dict(status="ready", version=version),
            "Actual ready/version health failed",
        )
    ui = show("knxohui.service")
    require(
        ui["Type"] == "notify"
        and ui["NotifyAccess"] == "main"
        and ui["ActiveState"] == "active"
        and ui["SubState"] == "running",
        "Actual notify UI is not running",
    )
    return ui


def read_request():
    from installer.update_core.protocol import parse_request

    parent = state.DATA / "update"
    info = parent.lstat()
    require(
        stat.S_ISDIR(info.st_mode)
        and (info.st_uid, info.st_gid, stat.S_IMODE(info.st_mode)) == (999, 989, 0o700),
        "Unsafe service request root",
    )
    request = parse_request(worker_read(parent / "request.json", 999, 989, 4096))
    require(request.channel == "stable", "Unexpected service request channel")
    return dict(
        format_version=request.format_version,
        request_id=request.request_id,
        channel=request.channel,
    )


def stage_observation(request, samples):
    """Passive observer, never starts/stops a stage or changes a namespace."""
    for stage in STAGES:
        group = Path("/sys/fs/cgroup/system.slice") / (
            "knxohupdate-" + request + "-" + stage + ".service"
        )
        if stage in samples or not group.is_dir():
            continue
        try:
            pids = (group / "cgroup.procs").read_text().split()
            if not pids:
                continue
            pid = pids[0]
            network = os.readlink("/proc/" + pid + "/ns/net")
            mount = os.readlink("/proc/" + pid + "/ns/mnt")
            interfaces = [
                line.split(":", 1)[0].strip()
                for line in Path("/proc/" + pid + "/net/dev").read_text().splitlines()[2:]
            ]
            routes = Path("/proc/" + pid + "/net/route").read_text().splitlines()
            require(
                interfaces == ["lo"] and len(routes) == 1, "Actual stage has non-loopback network"
            )
            same = network == os.readlink("/proc/self/ns/net")
            require(
                same == (stage in ("metadata", "download", "dependencies")),
                "Unexpected actual stage network namespace",
            )
            require(mount != os.readlink("/proc/self/ns/mnt"), "Stage mount namespace not isolated")
            samples[stage] = dict(
                pid=int(pid),
                network=network,
                mount=mount,
                interfaces=interfaces,
                no_ipv4_route=True,
            )
        except FileNotFoundError:
            continue  # Exited between cgroup/proc reads; no inferred successful sample.


def check_current_link(base, version):
    require(
        os.readlink(base / "current") == str(base / "releases" / version),
        "Actual current link not the exact absolute production candidate",
    )


def installed_candidate(version, manifest, ui):
    candidate = state.BASE / "releases" / version
    check_current_link(state.BASE, version)
    pid = ui["MainPID"]
    argv = Path("/proc/" + pid + "/cmdline").read_bytes().split(b"\0")
    require(
        any(str(candidate / "venv").encode() in arg for arg in argv),
        "UI is not from its final candidate venv",
    )
    # Inspect installed top-level distribution metadata; never import candidate code as root.
    from email.parser import BytesParser

    installed = {}
    for path in (candidate / "venv/lib/python3.12/site-packages").glob("*.dist-info/METADATA"):
        value = BytesParser().parsebytes(fs.read_regular(path, 1024 * 1024))
        name = __import__("re").sub(r"[-_.]+", "-", value["Name"]).lower()
        installed[name] = value["Version"]
    for item in manifest["wheels"]:
        if item["project"] != "pytest-timeout":
            require(
                installed.get(item["project"]) == item["version"],
                "Full original requirement closure not installed",
            )
    record = json.loads(fs.read_regular(CONTROL / "artifacts/manifest.json", 1024 * 1024))[
        "releases"
    ]["normal-" + version]
    archive = fs.read_regular(
        CONTROL / "artifacts" / ("normal-" + version) / record["archive"], 64 * 1024 * 1024
    )
    with tarfile.open(fileobj=io.BytesIO(archive), mode="r:gz") as bundle:
        for member in bundle:
            if member.isfile():
                relative = Path(member.name).relative_to("knx_to_openhab-" + version)
                require(
                    fs.read_regular(candidate / relative, 64 * 1024 * 1024)
                    == bundle.extractfile(member).read(),
                    "Installed candidate source differs from real artifact",
                )
    return dict(
        final_path=str(candidate),
        distribution_count=len(installed),
        source_archive=record["sha256"],
        ui_pid=pid,
    )


def check_stage_result(phase, stage, values):
    if phase == "migration-rejection" and stage == "migrate":
        require(
            values["Result"] == "exit-code" and values["ExecMainStatus"] != "0",
            "Migration negative did not exit nonzero",
        )
    else:
        require(
            values["Result"] == "success" and values["ExecMainStatus"] == "0",
            "Required stage did not actually succeed",
        )


def update_phase(phase, manifest, baseline):
    prepared = json.loads(fs.read_regular(CONTROL / "prepare-fixture.result.json", 2 * 1024 * 1024))
    require(
        prepared["system_tls"] is True and prepared["fixture"] == manifest,
        "Original preparation/TLS not complete",
    )
    previous = None
    for name in (
        "stable-update",
        "no-update",
        "checksum-rejection",
        "migration-rejection",
        "retry",
    ):
        if (CONTROL / (name + ".result.json")).exists():
            previous = name
        elif name == phase:
            break
        elif previous is not None:
            break
    current = (state.BASE / "current/VERSION").read_text().strip()
    check_sequence(phase, previous, current)
    require(
        not (CONTROL / (phase + ".started.json")).exists(),
        "Phase already attempted; never automatic resubmit",
    )
    before_ui = health(current)
    before_current = state.entry(state.BASE / "current", details=True)
    before_config = repair.inventory_entry(state.CONFIG / "config.json", details=True)
    before_manager = repair.manager_state()
    before_update = show("knxohui-update.service")
    require(
        before_update["MainPID"] == "0" and before_update["ActiveState"] in ("inactive", "failed"),
        "Unexpected active coordinator",
    )
    if current == "0.1.1":
        installed_candidate(current, manifest, before_ui)
    if previous is None:
        require(not JOURNAL.exists(), "Unexpected existing updater journal")
        require(
            before_ui["MainPID"] == "105534" and before_ui["NRestarts"] == "0",
            "Original ready UI identity changed",
        )
    else:
        prior_result = json.loads(
            fs.read_regular(CONTROL / (previous + ".result.json"), 2 * 1024 * 1024)
        )
        require(
            protected_record()["request_id"] == prior_result["request_id"],
            "Unknown previous root transaction",
        )
    tls_proof()
    # Only the root operator selects a fixed metadata map. HTTP clients cannot.
    phase_file = CONTROL / "phase"
    require(
        fs.read_regular(phase_file, 64).decode().strip()
        in ("stable-update", "no-update", "checksum-rejection", "migration-rejection", "retry"),
        "Unknown fixture phase state",
    )
    temporary = CONTROL / ("phase-" + phase)
    exclusive(temporary, (phase + "\n").encode())
    os.replace(temporary, phase_file)
    credential = json.loads(fs.read_regular(Path("/root/knxoh-acceptance-login.json"), 4096))
    api = AuthenticatedAPI(credential)
    del credential
    before_candidates = sorted(p.name for p in (state.BASE / "releases").iterdir())
    try:
        old_request = read_request()["request_id"]
    except FileNotFoundError:
        old_request = None
    save_json(
        CONTROL / (phase + ".started.json"),
        dict(phase=phase, previous_request=old_request, current=current),
    )
    started_at = str(int(time.time()))
    # Observe from BEFORE POST so quick metadata/download stages aren't inferred
    # merely from sandbox property declarations after the process has exited.
    samples, errors, stop = {}, [], threading.Event()
    known = {}

    def observe():
        while not stop.is_set():
            try:
                request = read_request()
                if request["request_id"] != old_request:
                    known["request_id"] = request["request_id"]
                    stage_observation(request["request_id"], samples)
            except FileNotFoundError:
                pass
            except Exception as error:
                errors.append(type(error).__name__)
                return
            stop.wait(0.01)

    observer = threading.Thread(target=observe, daemon=True)
    observer.start()
    lost_response = False
    try:
        try:
            code, body = api.submit()  # EXACTLY ONE actual no-body POST.
        except (urllib.error.URLError, TimeoutError, ConnectionError):
            lost_response = True
            code, body = None, None
        deadline = time.monotonic() + 1200
        if not lost_response:
            ack = json.loads(body)
            require(
                code == 200 and ack.get("status") == "updating",
                "Real API did not acknowledge update",
            )
            request_id = ack["request_id"]
        else:
            while "request_id" not in known and time.monotonic() < deadline:
                time.sleep(0.05)
            require("request_id" in known, "Lost HTTP response, unknown request; do NOT resubmit")
            request_id = known["request_id"]
        require(request_id != old_request, "New UUID not issued")
        emit("REQUEST_OBSERVED", request_id=request_id, lost_http_response=lost_response)
        busy_checked = False
        while time.monotonic() < deadline:
            require(not errors, "Passive stage observation failed")
            try:
                root = protected_record()
                from installer.update_submit import read_status

                status = read_status(fixture.expected_paths())
            except (FileNotFoundError, fs.EntryChangedError):
                time.sleep(0.02)
                continue  # Legitimate atomic publication, never accept stale bytes.
            if root["request_id"] != request_id or status.get("request_id") != request_id:
                time.sleep(0.02)
                continue  # Waiting for the matching actual claim, not accepting old status.
            if terminal(phase, request_id, root, status):
                break
            if (
                not busy_checked
                and root["phase"] in ("preparing", "quiescing")
                and show("knxohui-update.service")["ActiveState"] in ("active", "activating")
            ):
                # Only assert a concurrent409 while root transaction is confirmed active.
                concurrent, _ = api.submit()
                require(concurrent == 409, "Concurrent actual API did not return409; no retry")
                busy_checked = True
            time.sleep(0.02)
        else:
            raise ValueError("Transaction deadline exceeded; preserve evidence, never repair")
    finally:
        stop.set()
        observer.join(timeout=10)
    # Public terminal acknowledgement can precede the coordinator's durable
    # maintenance-release/finalization. Observe completion; never stop the unit.
    while True:
        running = show("knxohui-update.service")
        if running["MainPID"] == "0" and running["ActiveState"] in ("inactive", "failed"):
            break
        require(time.monotonic() < deadline, "Coordinator finalization deadline exceeded")
        time.sleep(0.02)
    root = protected_record()
    require(root["request_id"] == request_id, "Final protected transaction identity changed")
    require(read_request()["request_id"] == request_id, "API/request/root claim mismatch")
    require(not errors, "Actual stage namespace observation failed")
    expected_stages = (
        ("metadata",)
        if phase == "no-update"
        else ("metadata", "download") if phase == "checksum-rejection" else STAGES
    )
    units = {}
    for stage in STAGES:
        unit = "knxohupdate-" + request_id + "-" + stage + ".service"
        values = show(unit)
        require(
            values["MainPID"] == values["ControlPID"] == "0" and values["ControlGroup"] == "",
            "Own stage/cgroup not stopped",
        )
        journal = command(
            ["/usr/bin/journalctl", "-b", "--no-pager", "--unit=" + unit, "-o", "json", "-n", "200"]
        )
        units[stage] = dict(
            show=values, journal=[json.loads(line) for line in journal.splitlines()]
        )
        if stage in expected_stages:
            require(units[stage]["journal"], "Actual stage start journal missing")
            check_stage_result(phase, stage, values)
        else:
            require(not units[stage]["journal"], "Unexpected stage executed")
        require(
            not (Path("/sys/fs/cgroup/system.slice") / unit).exists(),
            "Own exact stage cgroup remains",
        )
    require(
        set(expected_stages) <= set(samples),
        "Actual stage network namespace sample missing; not acceptance",
    )
    expected_version = "0.1.2" if phase == "retry" else "0.1.1"
    ui = health(expected_version)
    require(
        (state.BASE / "current/VERSION").read_text().strip() == expected_version,
        "Unexpected final current version",
    )
    candidate = None
    if phase in ("stable-update", "retry"):
        candidate = installed_candidate(expected_version, manifest, ui)
        require(
            root["candidate_published"] is True and root["service_states"],
            "No real quiescence/publication provenance",
        )
    elif phase in ("checksum-rejection", "no-update"):
        require(
            sorted(p.name for p in (state.BASE / "releases").iterdir()) == before_candidates,
            "Negative created candidate",
        )
        require(
            ui["MainPID"] == before_ui["MainPID"]
            and ui["InvocationID"] == before_ui["InvocationID"],
            "No-update/checksum restarted UI",
        )
        require(
            state.entry(state.BASE / "current", details=True) == before_current,
            "No-update/checksum replaced current link",
        )
        require(
            repair.inventory_entry(state.CONFIG / "config.json", details=True) == before_config,
            "No-update/checksum changed configuration identity/bytes",
        )
        after_manager = repair.manager_state()
        for unit in state.UNITS:
            if unit != "knxohui-update.service":
                require(
                    after_manager["units"][unit] == before_manager["units"][unit],
                    "No-update/checksum changed an application unit",
                )
    if phase == "no-update":
        require(
            root["candidate"] is None and not root["service_states"],
            "No-update mutated candidate/service state",
        )
        require(
            not (state.CONFIG / ".updater-state" / ("archive-" + request_id + ".tar.gz")).exists(),
            "No-update downloaded archive",
        )
    elif phase in ("checksum-rejection", "migration-rejection"):
        label = "normal-0.1.2" if phase == "checksum-rejection" else "migration-negative"
        release = json.loads(fs.read_regular(CONTROL / "artifacts/manifest.json", 1024 * 1024))[
            "releases"
        ][label]
        protected = fs.read_regular(
            state.CONFIG / ".updater-state" / ("archive-" + request_id + ".tar.gz"),
            64 * 1024 * 1024,
        )
        require(
            digest(protected) == release["sha256"],
            "Negative did not ingest the exact intended archive",
        )
        if phase == "checksum-rejection":
            output = state.PREPARATION / request_id / "download/output"
            for path, uid, gid, mode in (
                (output.parent.parent, 0, 988, 0o750),
                (output.parent, 0, 988, 0o750),
                (output, 997, 988, 0o700),
            ):
                info = path.lstat()
                require(
                    stat.S_ISDIR(info.st_mode)
                    and (info.st_uid, info.st_gid, stat.S_IMODE(info.st_mode)) == (uid, gid, mode),
                    "Unsafe exact negative output ancestry",
                )
            checksum = worker_read(output / "archive.sha256", 997, 988, 1024)
            require(
                checksum == ("0" * 64 + "  " + release["archive"] + "\n").encode(),
                "Checksum rejection did not use the exact wrong sidecar",
            )
    if phase == "migration-rejection":
        require(
            root["phase"] == "rolled-back"
            and root["candidate_created"] is True
            and root["candidate_published"] is False,
            "Migration did not reject before publication",
        )
        require(
            units["migrate"]["show"]["Result"] == "exit-code",
            "Migration negative not actual nonzero exit",
        )
        require(
            not (state.BASE / "releases/0.1.2").exists(),
            "Production rollback retained failed candidate; no manual deletion",
        )
    preserve(baseline, own_root=root)
    update_unit = show("knxohui-update.service")
    require(
        update_unit["MainPID"] == "0" and update_unit["ActiveState"] in ("inactive", "failed"),
        "Coordinator still active after terminal outcome",
    )
    require(
        update_unit["InvocationID"]
        and update_unit["InvocationID"] != before_update["InvocationID"],
        "No fresh actual fixed updater unit invocation",
    )
    require(
        "/usr/local/libexec/knx_to_openhab/update_release.py" in update_unit["ExecStart"]
        and "-I" in update_unit["ExecStart"],
        "Wrong actual updater unit command",
    )
    sudo_raw = command(
        [
            "/usr/bin/journalctl",
            "-b",
            "--no-pager",
            "--since=@" + started_at,
            "_COMM=sudo",
            "-o",
            "json",
            "-n",
            "200",
        ]
    )
    sudo_entries = [json.loads(line) for line in sudo_raw.splitlines()]
    require(
        any(
            "COMMAND=/usr/bin/systemctl start --no-block knxohui-update.service"
            in entry.get("MESSAGE", "")
            for entry in sudo_entries
        ),
        "Actual fixed sudo unit-start receipt missing",
    )
    raw_journal = command(
        [
            "/usr/bin/journalctl",
            "-b",
            "--no-pager",
            "--unit=knxohui-update.service",
            "-o",
            "json",
            "-n",
            "400",
        ]
    )
    result = dict(
        phase=phase,
        request_id=request_id,
        root=root,
        status=status,
        stages=units,
        live_namespaces=samples,
        ui=ui,
        update_unit=update_unit,
        coordinator_journal=[json.loads(line) for line in raw_journal.splitlines()],
        sudo_journal=sudo_entries,
        candidate=candidate,
        concurrent409=busy_checked,
        lost_http_response=lost_response,
    )
    save_json(CONTROL / (phase + ".result.json"), result)
    emit(
        "PHASE_COMPLETE",
        phase=phase,
        request_id=request_id,
        terminal=root["phase"],
        version=expected_version,
        concurrent409=busy_checked,
    )


def run(phase, baseline, manifest, files):
    require(os.name == "posix" and os.geteuid() == 0, "Inner root only")
    require(
        all(isinstance(value, ModuleType) for value in (fs, fixture, repair, state, admin)),
        "Original verified module bindings required",
    )
    if phase == "prepare-fixture":
        require(
            not CONTROL.exists() and not CONTROL.is_symlink(),
            "Existing fixture refuses preparation",
        )
    private_effect_mounts()
    no_outbound()
    runtime_identity()
    before_first = not CONTROL.exists() or not (CONTROL / "stable-update.result.json").exists()
    preserve(baseline, before_first=before_first)
    if before_first:
        require(
            os.readlink(state.BASE / "current") == baseline["INDEPENDENT_STATE"]["current"],
            "Original known current link changed",
        )
    if phase == "prepare-fixture":
        require(not JOURNAL.exists(), "Unexpected existing updater journal")
        health("0.1.0")
        prepare(manifest, files)
        preserve(baseline, before_first=True)
    else:
        verify_fixture(manifest)
        update_phase(phase, manifest, baseline)
