#!/bin/bash
# docker-entrypoint.sh

# Aktiviert Debugging (set -eux) nur, wenn DEBUG auf "true" gesetzt ist (case-insensitive)
if [[ "${DEBUG,,}" == "true" ]]; then
    set -eux # Exit immediately if a command exits with a non-zero status. Print commands and their arguments as they are executed.
fi

# This script captures all environment variables that Docker Compose provided to the container
# and writes them to a file, which cron jobs can then source.

ENV_FILE="/etc/container_environment.sh"

# Ensure the directory exists
mkdir -p "$(dirname "$ENV_FILE")"

# Output all current environment variables into the file
# The format "export VAR=VALUE" is crucial for sourcing.
# We ensure values with spaces are properly quoted.
printenv | awk -F'=' '{ print "export " $1 "=\"" $2 "\"" }' > "$ENV_FILE"

# Debugging-Ausgabe der generierten Umgebungsvariablen-Datei
# Diese Ausgabe wird nur angezeigt, wenn DEBUG=true gesetzt ist.
if [[ "${DEBUG,,}" == "true" ]]; then
    echo "DEBUG: Contents of $ENV_FILE created by entrypoint:"
    cat "$ENV_FILE"
    echo "DEBUG: End of $ENV_FILE contents."
fi

# Make the environment file executable (though 'source' doesn't strictly require it)
chmod +x "$ENV_FILE"

# Execute the original CMD (which is "cron -f")
exec "$@"

