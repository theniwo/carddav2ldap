# Verwende ein Python-Image als Basis
FROM python:3.9-slim

# Arbeitsverzeichnis erstellen
WORKDIR /app

# Setze Standardwerte für Umgebungsvariablen
ENV \
    LDAP_SERVER="ldap://ldap:389" \
    CARDDAV_SSL_VERIFY="true" \
    LOG_FILE="/var/log/carddav2ldap/sync_output.log"

# Abhängigkeiten für den Build installieren
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libsasl2-dev \
    libldap2-dev \
    cron \
    tini \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

# Abhängigkeiten installieren
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Cron
# Cronjob hinzufügen
COPY crontab /etc/cron.d/ldap-sync-cron

# Berechtigungen für den Cronjob setzen
RUN chmod 0644 /etc/cron.d/ldap-sync-cron \
    && touch /etc/cron.d/ldap-sync-cron

# Cronjob aktivieren
RUN crontab /etc/cron.d/ldap-sync-cron

# Erstellen Sie das Log-Verzeichnis und stellen Sie sicher, dass es beschreibbar ist
RUN mkdir -p /var/log/carddav2ldap && chmod -R 777 /var/log/carddav2ldap

# Cleanup
RUN rm requirements.txt -rf
#RUN rm requirements.txt -rf && apt-get remove -y $(dpkg -l | grep ^ii| awk '{print $2 " "}' | cut -d: -f1 | grep -e gcc -e dev$ | grep -ve libgcc -e base | awk '{printf $1 " "}') && apt-get autoremove -y

# Skripte kopieren
COPY sync_script.sh .
COPY sync_script.py .
COPY docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh

# Skript ausführbar machen
RUN chmod +x /app/sync_script.sh
RUN chmod +x /app/sync_script.py
RUN chmod +x /usr/local/bin/docker-entrypoint.sh

# Tini als Init-System verwenden, um Zombie-Prozesse zu vermeiden und Signale korrekt zu handhaben
ENTRYPOINT ["/usr/bin/tini", "--", "/usr/local/bin/docker-entrypoint.sh"]
# Starten von Cron und dem Skript
CMD ["cron", "-f"]

