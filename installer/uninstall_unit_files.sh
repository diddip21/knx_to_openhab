#!/usr/bin/env bash

remove_unit_file_preserving_mask() {
    local unit_file="${1:-}"

    if [[ -z "$unit_file" ]]; then
        printf 'ERROR: A systemd unit-file path is required.\n' >&2
        return 2
    fi
    if [[ -L "$unit_file" ]]; then
        printf 'Preserving systemd unit symlink: %s\n' "$unit_file"
        return 0
    fi
    if [[ -e "$unit_file" ]]; then
        if [[ ! -f "$unit_file" ]]; then
            printf 'ERROR: Refusing to remove non-regular unit path: %s\n' "$unit_file" >&2
            return 1
        fi
        sudo rm -f -- "$unit_file"
    fi
}
