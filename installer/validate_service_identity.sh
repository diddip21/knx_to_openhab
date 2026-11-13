#!/usr/bin/env bash
set -euo pipefail

service_user="${1:-knxohui}"
if passwd_entry="$(getent passwd "$service_user")"; then
    :
else
    lookup_status=$?
    if (( lookup_status == 2 )); then
        # A missing account is created by setup after this check.
        exit 0
    fi
    echo "ERROR: Could not look up the $service_user service account." >&2
    exit 2
fi
if ! group_entry="$(getent group "$service_user")"; then
    echo "ERROR: Existing $service_user user has no matching service group." >&2
    exit 2
fi

IFS=: read -r account_name _ user_id primary_group_id _ _ login_shell <<<"$passwd_entry"
IFS=: read -r group_name _ service_group_id _ <<<"$group_entry"
if [[ "$account_name" != "$service_user" || "$group_name" != "$service_user" ||
      ! "$user_id" =~ ^[0-9]+$ || ! "$primary_group_id" =~ ^[0-9]+$ ||
      ! "$service_group_id" =~ ^[0-9]+$ || "$primary_group_id" != "$service_group_id" ]]; then
    echo "ERROR: Existing $service_user user does not use the matching service group." >&2
    exit 2
fi
case "$login_shell" in
    /usr/sbin/nologin|/sbin/nologin|/bin/false) ;;
    *)
        echo "ERROR: Existing $service_user user has an interactive or unknown login shell." >&2
        exit 2
        ;;
esac
