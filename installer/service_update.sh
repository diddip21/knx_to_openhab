#!/usr/bin/env bash
# Installed as a root-owned file outside the writable application directory.
set -euo pipefail
export LC_ALL=C

if [[ $# -ne 1 ]]; then
  exit 2
fi

case "$1" in
  refresh)
    /usr/bin/apt-get update
    ;;
  openhab|evcc)
    /usr/bin/dpkg-query -W -f='${Status}' -- "$1" | /bin/grep -qx 'install ok installed'
    IFS= read -r expected_version
    [[ "$expected_version" =~ ^[0-9A-Za-z.+:~_-]+$ ]] || exit 2
    candidate=$(/usr/bin/apt-cache policy "$1" | /usr/bin/awk '/^[[:space:]]*Candidate:/ {print $2; exit}')
    [[ "$candidate" == "$expected_version" ]] || {
      echo "APT candidate changed. Refresh package lists and confirm again." >&2
      exit 3
    }
    /usr/bin/apt-get install --only-upgrade -y -- "$1=$expected_version"
    ;;
  *)
    exit 2
    ;;
esac
