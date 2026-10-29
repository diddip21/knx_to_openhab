#!/usr/bin/env bash
# Do not execute a candidate's repair/provisioning code with administrator privileges.
set -euo pipefail
echo "Permission repair requires the verified administrator bootstrap." >&2
echo "Download install.sh from the documented project URL and run: bash install.sh --repair" >&2
echo "It holds the lifecycle lock, checks recovery state and preserves protected ownership." >&2
exit 2
