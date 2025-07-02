#!/bin/bash
set -e

# Path to the mounted config directory
LDAP_CONFIG_DIR="/etc/ldap/slapd.d"
LDAP_DATA_DIR="/var/lib/ldap"

# Check if the data directory is empty. If so, force clean the config directory.
# This ensures a clean re-initialization when the database is new or reset.
# The -z "$(ls -A ...)" check is robust for empty directories.
if [ -z "$(ls -A "$LDAP_DATA_DIR" 2>/dev/null)" ]; then
    echo "INFO: LDAP data directory is empty. Forcing cleanup of config directory: $LDAP_CONFIG_DIR"
    # Remove all contents of the config directory
    rm -rf "$LDAP_CONFIG_DIR"/*
    # Recreate the directory if rm -rf removed the directory itself (unlikely but safe)
    mkdir -p "$LDAP_CONFIG_DIR"
fi

# Execute the original entrypoint of the osixia/openldap image.
# Pass all arguments received by this script to the original entrypoint.
# The original entrypoint for osixia/openldap is typically /container/tool/run
exec /container/tool/run "$@"

