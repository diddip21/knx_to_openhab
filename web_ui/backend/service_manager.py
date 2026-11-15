import subprocess

ALLOWED_SERVICES = {"openhab.service", "knxohui.service", "evcc.service"}


def get_service_status(service_name: str):
    """Get service status (active/inactive/failed/...) and some metadata."""
    if service_name not in ALLOWED_SERVICES:
        return {
            "active": False,
            "status": "unsupported",
            "info": "Unsupported service",
            "uptime_str": None,
            "last_run_str": None,
        }
    try:
        # Read the state and timestamps together in one request.
        proc_show = subprocess.run(
            [
                "systemctl",
                "show",
                service_name,
                "--property=LoadState,ActiveState,ActiveEnterTimestamp,"
                "StateChangeTimestamp,InactiveEnterTimestamp",
            ],
            capture_output=True,
            text=True,
            timeout=10,
        )

        # Output is like:
        # ActiveEnterTimestamp=Mon 2023-10-23 10:00:00 CEST
        # InactiveEnterTimestamp=...
        info_dict = {}
        for line in proc_show.stdout.splitlines():
            key, separator, value = line.partition("=")
            if separator:
                info_dict[key.strip()] = value.strip()

        status = info_dict.get("ActiveState") or "unknown"
        if info_dict.get("LoadState") == "not-found":
            status = "not-found"
        is_active = proc_show.returncode == 0 and status == "active"

        uptime_str = None
        last_run_str = None

        # Calculate uptime if active
        if is_active:
            ts = info_dict.get("ActiveEnterTimestamp")
            if ts:
                uptime_str = ts
        else:
            # If inactive, show when it stopped or changed state
            ts = info_dict.get("InactiveEnterTimestamp") or info_dict.get("StateChangeTimestamp")
            if ts:
                last_run_str = ts

        # Refine uptime calculation if possible (to show "2 days, 3 hours")
        # For this MVP, showing the exact timestamp is reliable and sufficient.
        # "since Mon 2023-..." is good.

        return {
            "active": is_active,
            "status": status,
            "info": proc_show.stdout or proc_show.stderr,
            "uptime_str": uptime_str,
            "last_run_str": last_run_str,
        }
    except Exception as e:
        return {
            "active": False,
            "status": "error",
            "info": str(e),
            "uptime_str": None,
            "last_run_str": None,
        }


def restart_service(service_name: str):
    if service_name not in ALLOWED_SERVICES:
        return False, "Unsupported service"
    try:
        # using sudo; setup script will configure sudoers for the service user
        proc = subprocess.run(
            ["sudo", "systemctl", "restart", service_name],
            capture_output=True,
            text=True,
            timeout=30,
        )
        ok = proc.returncode == 0
        out = proc.stdout + proc.stderr
        return ok, out
    except Exception as e:
        return False, str(e)
