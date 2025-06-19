# Verwende ein Python-Image als Basis
FROM python:3.9-slim

# Arbeitsverzeichnis erstellen
WORKDIR /app

# Abhängigkeiten für den Build installieren
RUN apt-get update && apt-get install -y \
    gcc \
    libsasl2-dev \
    libldap2-dev \
    cron \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

# Abhängigkeiten installieren
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Cronjob hinzufügen
COPY crontab /etc/cron.d/sync-cron

# Berechtigungen für den Cronjob setzen
RUN chmod 0644 /etc/cron.d/sync-cron

# Cronjob aktivieren
RUN crontab /etc/cron.d/sync-cron

# Cleanup
RUN rm requirements.txt -rf

# Skript kopieren
COPY sync_script.py .

# Skript ausführbar machen
RUN chmod +x /app/sync_script.py

# Starten von Cron und dem Skript
CMD ["cron", "-f"]

