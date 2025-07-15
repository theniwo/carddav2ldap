#!/bin/bash
set -e

# Get CENSOR_SECRETS_IN_LOGS setting early
CENSOR_SECRETS_IN_LOGS_ENABLED=true
if [[ -n "${CENSOR_SECRETS_IN_LOGS}" && "${CENSOR_SECRETS_IN_LOGS,,}" == "false" ]]; then
    CENSOR_SECRETS_IN_LOGS_ENABLED=false
fi

# Get WARNING_TIMEOUT_SECONDS setting (default to 30 seconds)
WARNING_TIMEOUT_SECONDS_DEFAULT=30
WARNING_TIMEOUT_SECONDS=${WARNING_TIMEOUT_SECONDS:-$WARNING_TIMEOUT_SECONDS_DEFAULT}

# IMPORTANT WARNING: Display a prominent warning if password logging is not censored
if [[ "$CENSOR_SECRETS_IN_LOGS_ENABLED" == "false" ]]; then
    echo "========================================================================" >&2
    echo "WARNING: CENSOR_SECRETS_IN_LOGS is set to 'false'!" >&2
    echo "         LDAP and CARDDAV passwords WILL be visible in Docker logs and" >&2
    echo "         file logs (if enabled). This is a SECURITY RISK!" >&2
    echo "         Set CENSOR_SECRETS_IN_LOGS=true to redact passwords!" >&2
    echo "         This warning will pause execution for ${WARNING_TIMEOUT_SECONDS} seconds." >&2 # Added timeout info
    echo "========================================================================" >&2
    sleep "$WARNING_TIMEOUT_SECONDS" # Pause execution for visibility
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
# The 'awk' command is adjusted to handle '=' signs within variable values correctly.
printenv | awk 'BEGIN {FS="="} {
    if (NF > 1) {
        # Print "export VAR_NAME=\"FULL_VALUE\""
        # Full value is everything after the first '='
        printf "export %s=\"%s\"\n", $1, substr($0, index($0,"=")+1)
    } else {
        # Handle cases where there is no '=' in the variable (e.g., just a flag)
        printf "export %s=\"\"\n", $1
    }
}' > "$ENV_FILE"

# Debugging-Ausgabe der generierten Umgebungsvariablen-Datei
# Diese Ausgabe wird nur angezeigt, wenn DEBUG=true gesetzt ist.
if [[ "${DEBUG,,}" == "true" ]]; then
    echo "DEBUG: Contents of $ENV_FILE created by entrypoint:"
    # Apply redaction ONLY when displaying the output here, if enabled
    if [[ "$CENSOR_SECRETS_IN_LOGS_ENABLED" == "true" ]]; then
        cat "$ENV_FILE" | sed -E 's/^(LDAP_PASSWORD|CARDDAV_PASSWORD))=".*/\1="[REDACTED]"/g'
    else
        cat "$ENV_FILE"
    fi
    echo "DEBUG: End of $ENV_FILE contents."
fi

# Check if CRON_SCHEDULE is set, otherwise use default value
CRON_SCHEDULE=${CRON_SCHEDULE:-0 0 * * *}

echo "CRON_SCHEDULE is set to: $CRON_SCHEDULE"

# Create a temporary file for the crontab entries
CRON_FILE=$(mktemp)

# Command to run the sync script
COMMAND="/bin/bash -c /app/sync_script.sh >> /proc/1/fd/1 2>&1"

# Add the @reboot job to run the script once on container start/reboot
echo "@reboot $COMMAND" >> "$CRON_FILE"

# Add the regularly scheduled cron job
echo "$CRON_SCHEDULE $COMMAND" >> "$CRON_FILE"

# Load the combined cron jobs into crontab
crontab "$CRON_FILE"

# Remove the temporary file
rm "$CRON_FILE"

# Make the environment file executable (though 'source' doesn't strictly require it)
chmod +x "$ENV_FILE"

# --- NEW: Explicitly start cron and keep container alive ---
echo "$(date): Starting cron daemon in foreground..."
# Start cron in the background. This ensures the entrypoint script continues to tail the log.
cron -f

