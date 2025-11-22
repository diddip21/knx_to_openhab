import subprocess


def restart_service(service_name: str):
    try:
        # using sudo; setup script will configure sudoers for the service user
        proc = subprocess.run(['sudo', 'systemctl', 'restart', service_name], capture_output=True, text=True, timeout=30)
        ok = proc.returncode == 0
        out = proc.stdout + proc.stderr
        return ok, out
    except Exception as e:
        return False, str(e)
