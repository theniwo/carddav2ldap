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

**web** is used for external provisioning templates. You can delete it if you don't need provisioning, but it helps to configure your phone with necessary information to fetch from ldap

**phpldapadmin** is used for checking and altering the ldap directory via a webeinterface. (NOTICE: Since the sync process is unidirectional i.e. from carddav to ldap, changes will be overwritten! 💥 )

## ✅ Prerequisits
---
Enter credentials and URLs in `.env`.

Variable names should be self explanatory.

Required variables are:

```
LDAP_ORGANISATION
LDAP_DOMAIN
LDAP_BASE_DN ( LDAP base DN for contacts (e.g., "ou=contacts,dc=yourdomain,dc=local") )
LDAP_USER ( LDAP bind username (e.g., "cn=admin,dc=yourdomain,dc=local") )
LDAP_PASSWORD
LDAP_SERVER
CARDDAV_BASE_DISCOVERY_URL
CARDDAV_USERNAME
CARDDAV_PASSWORD
```
(if a variable is not set, defaults are used or an error is logged!)

Additional (optional) variables are
```
CARDDAV_SSL_VERIFY (enabled by default, can be disabled for debugging purposes.)
LOG_FILE (defaults to /var/log/carddav2ldap/sync_output.log, can be set to a path or to false to disable logging to files. Setting LOG_FILE to false is recommended when the project is running flawlessly, to save hard disk space. There is currently no logrotate implemented.)
DEBUG (Turns on debug logging.)
CENSOR_SECRETS_IN_LOGS (Defaults to true, set to false to spill out senistive secrets like LDAP_PASSWORD and CARDDAV_PASSWORD and sensitive ldap fields like telephoneNumber etc to stdout AND LOG_FILE (if enabled!))
WARNING_TIMEOUT_SECONDS (Timeout in seconds for warning screen that is displayed, when CENSOR_SECRETS_IN_LOGS is set to false. Default is 30 seconds.)
```

## 🏗️ Build and start Containers
---
```
docker compose build
docker compose up -d
```

## 👷 Fill ldap with structure
---
At first the ldap directory is empty and only contains your base

```
docker exec -it carddav2ldap-ldap-1 ldapsearch -H ldapi:/// -Y EXTERNAL -b "dc=niwo,dc=home" -LLL "(objectClass=*)"
```
```
SASL/EXTERNAL authentication started
SASL username: gidNumber=0+uidNumber=0,cn=peercred,cn=external,cn=auth
SASL SSF: 0
No such object (32)
Matched DN: dc=niwo,dc=home
```

### 🦧 First we create our admin user

```
cat admin.ldif
# Set up admin user
dn: cn=admin,dc=niwo,dc=home
objectClass: inetOrgPerson
cn: admin
sn: admin
userPassword:
```

Next we need to create two OUs

```
cat base.ldif
# Create OU config
dn: ou=config,dc=niwo,dc=home
objectClass: organizationalUnit
ou: contacts

# Create OU contacts
dn: ou=contacts,dc=niwo,dc=home
objectClass: organizationalUnit
ou: contacts

```

edit base.ldif to your needs and copy it to your "carddav2ldap_ldap_config" docker volume (usually `/var/lib/docker/volumes/carddav2ldap_ldap_config/_data`)

and run

```
docker exec -it carddav2ldap-ldap-1 ldapadd -H ldapi:/// -Y EXTERNAL -f /etc/ldap/slapd.d/admin.ldif
docker exec -it carddav2ldap-ldap-1 ldapadd -H ldapi:/// -Y EXTERNAL -f /etc/ldap/slapd.d/base.ldif
```

now you should have

```
docker exec -it carddav2ldap-ldap-1 ldapsearch -H ldapi:/// -Y EXTERNAL -b "dc=niwo,dc=home" -LLL "(objectClass=*)"
SASL/EXTERNAL authentication started
SASL username: gidNumber=0+uidNumber=0,cn=peercred,cn=external,cn=auth
SASL SSF: 0
dn: dc=niwo,dc=home
objectClass: top
objectClass: dcObject
objectClass: organization
o: niwo
dc: niwo

dn: ou=config,dc=niwo,dc=home
objectClass: organizationalUnit
ou: contacts
ou: config

dn: ou=contacts,dc=niwo,dc=home
objectClass: organizationalUnit
ou: contacts
```

Additionally you can test if the login credentials are working

```
docker exec -it carddav2ldap-ldap-1 ldapsearch -H ldapi:/// -x -D "cn=admin,dc=niwo,dc=home" -w [LDAP_PASSWORD] -b "ou=contacts,dc=niwo,dc=home" -LLL "(objectClass=*)"
```

### 👶 Add user
---
Next we add users to read your ldap directory

```
cat users.ldif
# Set up Phone user
dn: cn=phone,ou=contacts,dc=niwo,dc=home
objectClass: inetOrgPerson
cn: phone
sn: phone
userPassword:

# Set up Printer user
dn: cn=printer,ou=contacts,dc=niwo,dc=home
objectClass: inetOrgPerson
cn: printer
sn: printer
userPassword:
```


```
cp users.ldif /var/lib/docker/volumes/carddav2ldap_ldap_config/_data
```
```
docker exec -it carddav2ldap_ldap_1 ldapadd -H ldapi:/// -Y EXTERNAL -f /etc/ldap/slapd.d/users.ldif
```
```
SASL/EXTERNAL authentication started
SASL username: gidNumber=0+uidNumber=0,cn=peercred,cn=external,cn=auth
SASL SSF: 0
adding new entry "cn=phone,ou=contacts,dc=niwo,dc=home"

adding new entry "cn=printer,ou=contacts,dc=niwo,dc=home"
```

With this you are already setup to read the ldap with your phone and printer:

```
root@host:# docker logs -f carddav2ldap_ldap_1
...
68540d8b conn=1011 fd=12 ACCEPT from IP=192.168.1.104:2097 (IP=0.0.0.0:389)
68540d8b conn=1011 op=0 BIND dn="cn=phone,ou=contacts,dc=niwo,dc=home" method=128
68540d8b conn=1011 op=0 BIND dn="cn=phone,ou=contacts,dc=niwo,dc=home" mech=SIMPLE ssf=0
68540d8b conn=1011 op=0 RESULT tag=97 err=0 text=
68540d8b conn=1011 op=1 SRCH base="dc=niwo.home" scope=2 deref=0 filter="(|(cn=*)(sn=*))"
68540d8b conn=1011 op=1 SRCH attr=cn telephoneNumber
68540d8b conn=1011 op=1 SEARCH RESULT tag=101 err=32 nentries=0 text=
68540d8c conn=1011 op=2 SRCH base="dc=niwo.home" scope=2 deref=0 filter="(|(cn=*)(sn=*))"
68540d8c conn=1011 op=2 SRCH attr=cn telephoneNumber
68540d8c conn=1011 op=2 SEARCH RESULT tag=101 err=32 nentries=0 text=
68540e05 conn=1011 op=3 UNBIND
68540e05 conn=1011 fd=12 closed
```

Of course the phonebook should still be empty by now.


#### ❤️‍🔥 Let users edit the directory (optional)
If you want to have your users write to the directory, use the following acl.ldif
```
root@host:# cat acl.ldif
dn: olcDatabase={1}mdb,cn=config
changetype: modify
replace: olcAccess
olcAccess: to * by dn.base="cn=phone,ou=contacts,dc=niwo,dc=home" write by * read

dn: olcDatabase={1}mdb,cn=config
changetype: modify
replace: olcAccess
olcAccess: to * by dn.base="cn=printer,ou=contacts,dc=niwo,dc=home" write by * read
```

```
docker exec -it carddav2ldap-ldap-1 ldapmodify -H ldapi:/// -Y EXTERNAL -f /etc/ldap/slapd.d/acl.ldif
```

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
- [ ] test  UTF-8 encoding
- [ ] test image handling
- [ ] fetch all phone and fax numbers
- [X] fetch adress data and other fields like company etc
- [ ] add check if script is already running and mitigate stacking
- [ ] provide env_example
- [ ] make cron string as a variable
- [ ] Add snom xml setup
- [ ] shrink docker image
- [ ] make setting up ldap structure automatic with variables
- [ ] TZ
- [ ] translate german comments to english
- [ ] reformat readme and describe variables more clearly
