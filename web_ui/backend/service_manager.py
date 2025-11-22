import subprocess


def get_service_status(service_name: str):
    """Get service status (active/inactive/failed/...) and some metadata."""
    try:
        # Get service status
        proc = subprocess.run(['systemctl', 'is-active', service_name], capture_output=True, text=True, timeout=10)
        is_active = proc.returncode == 0
        status = proc.stdout.strip() if proc.stdout else 'unknown'
        
        # Get service info (to extract uptime/since)
        proc_show = subprocess.run(['systemctl', 'show', service_name, '-p', 'ActiveEnterTimestamp,StateChangeTimestamp'], 
                                   capture_output=True, text=True, timeout=10)
        info = proc_show.stdout
        
        return {
            'active': is_active,
            'status': status,
            'info': info
        }
    except Exception as e:
        return {
            'active': False,
            'status': 'error',
            'info': str(e)
        }


def restart_service(service_name: str):
    try:
        # using sudo; setup script will configure sudoers for the service user
        proc = subprocess.run(['sudo', 'systemctl', 'restart', service_name], capture_output=True, text=True, timeout=30)
        ok = proc.returncode == 0
        out = proc.stdout + proc.stderr
        return ok, out
    except Exception as e:
        return False, str(e)
