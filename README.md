# carddav2ldap 🐳 🚀
---
Fetch contact information via CardDav and present as ldap to phones like snom

# 📦 Features
---
* Import data from carddav servers like baikal (tested) and nextcloud (untested)
* Multiple adressbooks are supported
* Automatically sync your contacts
* Web-based interface for LDAP management (phpldapadmin).
* Web-based provisioning for snom phones etc.

# 🛠️ Getting Started
---

There are 3 containers:
* ldap
* sync
* web
* phpldapadmin

**ldap** is your ldap directory server.

**sync** runs a script periodically to fetch carddav data and spill it into the ldap directory.

**web** (optional) is used for external provisioning templates. You can delete it if you don't need provisioning, but it helps to configure your phone with necessary information to fetch from ldap

**phpldapadmin** (optional) is used for checking and altering the ldap directory via a webeinterface. (NOTICE: Since the sync process is unidirectional i.e. from carddav to ldap, changes will be overwritten! 💥 )

## ✅ Prerequisits
---
Copy env_example to `.env` and enter data.

Variable names should be self explanatory.

Required variables are:

```
# LDAP
# Required for ldap server
LDAP_CONFIG_PASSWORD (for the user "cn=admin,cn=config")
LDAP_ORGANISATION=example
LDAP_DOMAIN=example.com

# sync
LDAP_BASE_DN ( LDAP base DN for contacts (e.g., "ou=contacts,dc=yourdomain,dc=local") )
LDAP_USER ( LDAP bind username (e.g., "cn=admin,dc=yourdomain,dc=local") )
LDAP_USER="cn=admin,dc=example,dc=com"
LDAP_PASSWORD
CRON_SCHEDULE=*/5 * * * *

# CARDDAV
CARDDAV_USERNAME=
CARDDAV_PASSWORD=
CARDDAV_BASE_DISCOVERY_URL=https://calendar.example.com/dav.php/addressbooks/${CARDDAV_USERNAME}/

# phpLDAPadmin Configuration
LDAP_HOST=ldap (your ldap container name)
HTTPS=false (not needed if running locally or behind a reverse proxy, refer to [osixia/phpldapadmin](https://github.com/osixia/docker-phpLDAPadmin) for details.)
ADMIN_PORT=8081

```
(if a variable is not set, defaults are used or an error is logged!)

Additional (optional) variables are
```
CARDDAV_SSL_VERIFY (enabled by default, can be disabled for debugging purposes.)
LOG_FILE (defaults to /var/log/carddav2ldap/sync_output.log, can be set to a path or to false to disable logging to files. Setting LOG_FILE to false is recommended when the project is running flawlessly, to save hard disk space. There is currently no logrotate implemented.)
DEBUG (Turns on debug logging.)
CENSOR_SECRETS_IN_LOGS (Defaults to true, set to false to spill out senistive secrets like LDAP_PASSWORD and CARDDAV_PASSWORD and sensitive ldap fields like telephoneNumber etc to stdout AND LOG_FILE (if enabled!))
WARNING_TIMEOUT_SECONDS (Timeout in seconds for warning screen that is displayed, when CENSOR_SECRETS_IN_LOGS is set to false. Default is 30 seconds.)
CARDDAV_IMPORT_PHOTOS
CARDDAV_EMAIL_WHITELIST_DOMAINS
CARDDAV_EMAIL_BLACKLIST_DOMAINS
CARDDAV_CATEGORY_WHITELIST
CARDDAV_CATEGORY_BLACKLIST
CARDDAV_ADDRESSBOOK_WHITELIST
CARDDAV_ADDRESSBOOK_BLACKLIST

```

## 👷 Fill ldap with structure
---
Configure ldifs in the  
`ldap_init_config/data`  
directory depending on your needs

## 🏗️ Build and start Containers
---
```
docker compose build
docker compose up -d
```

---



# TODO
- [X] throw out some default variables from Dockerfile and test missing/unset variables
- [X] fix: CAT... Error: decoding with 'base64' codec failed (Error: Incorrect padding)
- [X] Import Photos
- [X] LOG_FILE=true
- [X] Test Logging
- [X] Added feature to control secret censoring
- [X] fix: ERROR: Failed to connect to LDAP server: automatic bind not successful - invalidDNSyntax
- [X] fix: invalidAttributeSyntax-Fehler for givenName
- [X] fix: DEBUG messages appear in python script only when DEBUG=true
- [X] fix: invalidAttributeSyntax for sn
- [X] fix: invalidAttributeSyntax for telephoneNumber
- [X] fix: invalidAttributeSyntax for mail and others
- [X] feat: add and censor contact information in log files
- [X] feat: saftey timeout to display warning message
- [X] fetch all phone and fax numbers
- [X] Blacklist for Adressbooks and/or contacts
- [ ] test  UTF-8 encoding
- [ ] test image handling
- [X] fetch adress data and other fields like company etc
- [ ] add check if script is already running and mitigate stacking
- [X] provide env_example
- [X] make cron string as a variable
- [ ] Add snom xml setup
- [ ] shrink docker image
- [ ] make setting up ldap structure automatic with variables
- [ ] TZ
- [X] translate german comments to english
- [ ] reformat readme and describe variables more clearly as well as seperate variables for services
- [ ] seperate email types
