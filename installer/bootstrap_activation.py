"""Fixed service activation AFTER administrator disk mutation releases its lease.

Recovery acquires the host lease itself. Never wait for a required recovery
oneshot while holding that lease. This module does not mutate installation files.
"""

from __future__ import annotations


def activate_services(outcome, runner):
    systemctl = "/usr/bin/systemctl"
    runner([systemctl, "daemon-reload"])
    runner([systemctl, "start", "knxohui-update-recovery.service"])
    for name, key in (("knxohui.service", "ui"), ("knxohui-backup-cleanup.timer", "cleanup")):
        if outcome[key + "_enable"]:
            runner([systemctl, "enable", name])
        if outcome[key + "_start"]:
            runner([systemctl, "restart" if key == "ui" else "start", name])
            runner([systemctl, "is-active", "--quiet", name])


def restore_services(outcome, runner):
    systemctl = "/usr/bin/systemctl"
    runner([systemctl, "start", "knxohui-update-recovery.service"])
    for name, active, enabled in (
        ("knxohui.service", "ui_was_active", "ui_was_enabled"),
        ("knxohui-backup-cleanup.service", "cleanup_service_was_active", None),
        ("knxohui-backup-cleanup.timer", "cleanup_timer_was_active", "cleanup_timer_was_enabled"),
    ):
        if enabled is not None:
            runner([systemctl, "enable" if outcome[enabled] else "disable", name])
        runner([systemctl, "start" if outcome[active] else "stop", name])
