import subprocess


def get_service_status(service_name: str):
    """Get service status (active/inactive/failed/...) and some metadata."""
    try:
        # Get service status
        # First try without sudo
        proc = subprocess.run(['systemctl', 'is-active', service_name], capture_output=True, text=True, timeout=10)
        status = proc.stdout.strip()
        
        # If output is empty or unknown, try with sudo (in case user needs privs to see status)
        if not status or status == 'unknown':
             proc_sudo = subprocess.run(['sudo', 'systemctl', 'is-active', service_name], capture_output=True, text=True, timeout=10)
             status_sudo = proc_sudo.stdout.strip()
             if status_sudo and status_sudo != 'unknown':
                 status = status_sudo
                 proc = proc_sudo
             else:
                 # If sudo also failed to find it, keep track of errors for debugging
                 if proc_sudo.stderr:
                      print(f"Service check failed (sudo): {proc_sudo.stderr}")
                 if proc.stderr:
                      print(f"Service check failed (non-sudo): {proc.stderr}")
        
        if not status:
            status = 'unknown'

        is_active = (proc.returncode == 0) and (status == 'active')
        
        # Get service info (to extract uptime/since)
        # We need ActiveEnterTimestamp for uptime, and StateChangeTimestamp/InactiveEnterTimestamp for last run
        proc_show = subprocess.run(
            ['systemctl', 'show', service_name, '-p', 'ActiveEnterTimestamp,StateChangeTimestamp,InactiveEnterTimestamp'], 
            capture_output=True, text=True, timeout=10
        )
        
        # If output is empty or failed, try with sudo (in case user needs privs to see properties)
        if proc_show.returncode != 0 or not proc_show.stdout.strip():
             proc_show = subprocess.run(
                ['sudo', 'systemctl', 'show', service_name, '-p', 'ActiveEnterTimestamp,StateChangeTimestamp,InactiveEnterTimestamp'], 
                capture_output=True, text=True, timeout=10
            )
        # Output is like:
        # ActiveEnterTimestamp=Mon 2023-10-23 10:00:00 CEST
        # InactiveEnterTimestamp=...
        info_lines = proc_show.stdout.splitlines()
        info_dict = {}
        for line in info_lines:
            if '=' in line:
                k, v = line.split('=', 1)
                info_dict[k.strip()] = v.strip()
        
        uptime_str = None
        last_run_str = None
        
        from datetime import datetime, timedelta
        import time
        
        # Helper to parse systemd timestamp (simplified)
        # Systemd format: "Day YYYY-MM-DD HH:MM:SS TZ" or "Mon 2023-..."
        # We'll try to parse commonly used formats
        def parse_systemd_time(ts_str):
            if not ts_str: return None
            # remove day name if present
            parts = ts_str.split(' ', 1)
            if len(parts) > 1 and parts[0] in ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']:
                ts_str = parts[1]
            
            # Simple approach: try to parse fixed format
            # Or simplified: just return the string if it looks like a date
            return ts_str

        def get_duration_str(start_ts_str):
            if not start_ts_str: return None
            # This is hard to do accurately without proper timezone handling in python < 3.9 w/o third party libs
            # We'll return the timestamp string itself as "Starts at ..." or calculate rough diff if possible
            # For now, let's just return the raw timestamp string as it is informative enough
            return start_ts_str

        # Calculate uptime if active
        if is_active:
            ts = info_dict.get('ActiveEnterTimestamp')
            if ts:
                uptime_str = ts
        else:
            # If inactive, show when it stopped or changed state
            ts = info_dict.get('InactiveEnterTimestamp') or info_dict.get('StateChangeTimestamp')
            if ts:
                last_run_str = ts

        # Refine uptime calculation if possible (to show "2 days, 3 hours")
        # For this MVP, showing the exact timestamp is reliable and sufficient.
        # "since Mon 2023-..." is good.

        return {
            'active': is_active,
            'status': status,
            'info': proc_show.stdout,
            'uptime_str': uptime_str,
            'last_run_str': last_run_str
        }
    except Exception as e:
        return {
            'active': False,
            'status': 'error',
            'info': str(e),
            'uptime_str': None,
            'last_run_str': None
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
