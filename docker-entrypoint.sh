#!/bin/bash
# docker-entrypoint.sh

# Get CENSOR_SECRETS_IN_LOGS setting early
CENSOR_SECRETS_IN_LOGS_ENABLED=true
if [[ -n "${CENSOR_SECRETS_IN_LOGS}" && "${CENSOR_SECRETS_IN_LOGS,,}" == "false" ]]; then
    CENSOR_SECRETS_IN_LOGS_ENABLED=false
fi

# IMPORTANT WARNING: Display a prominent warning if password logging is not censored
if [[ "$CENSOR_SECRETS_IN_LOGS_ENABLED" == "false" ]]; then
    echo "========================================================================" >&2
    echo "WARNING: CENSOR_SECRETS_IN_LOGS is set to 'false'!" >&2
    echo "         LDAP and CARDDAV passwords WILL be visible in Docker logs and" >&2
    echo "         file logs (if enabled). This is a SECURITY RISK!" >&2
    echo "         Set CENSOR_SECRETS_IN_LOGS=true to redact passwords!" >&2
    echo "========================================================================" >&2
fi

# Activate debugging (set -eux) only if DEBUG is set to "true" (case-insensitive)
if [[ "${DEBUG,,}" == "true" ]]; then
    set -eux # Exit immediately if a command exits with a non-zero status. Print commands and their arguments as they are executed.
fi

# This script captures all environment variables that Docker Compose provided to the container
# and writes them to a file, which cron jobs can then source.

ENV_FILE="/etc/container_environment.sh"

# Ensure the directory exists
mkdir -p "$(dirname "$ENV_FILE")"

# Output all current environment variables into the file.
# IMPORTANT: Passwords are NOT redacted at this stage, so the original values are preserved.
# The format "export VAR=VALUE" is crucial for sourcing.
# We ensure values with spaces are properly quoted.
printenv | awk -F'=' '{ print "export " $1 "=\"" $2 "\"" }' > "$ENV_FILE"

# Debugging-Ausgabe der generierten Umgebungsvariablen-Datei
# Diese Ausgabe wird nur angezeigt, wenn DEBUG=true gesetzt ist.
if [[ "${DEBUG,,}" == "true" ]]; then
    echo "DEBUG: Contents of $ENV_FILE created by entrypoint:"
    # Apply redaction ONLY when displaying the output here, if enabled
    if [[ "$CENSOR_SECRETS_IN_LOGS_ENABLED" == "true" ]]; then
        cat "$ENV_FILE" | sed -E 's/^(export (LDAP_PASSWORD|CARDDAV_PASSWORD))=".*/\1="[REDACTED]"/g'
    else
        cat "$ENV_FILE"
    fi
    echo "DEBUG: End of $ENV_FILE contents."
fi

# Make the environment file executable (though 'source' doesn't strictly require it)
chmod +x "$ENV_FILE"

# Execute the original CMD (which is "cron -f")
exec "$@"

