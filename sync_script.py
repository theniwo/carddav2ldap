# sync_script.py

import os
import requests
import xml.etree.ElementTree as ET
import vobject
import ldap3
from ldap3.core.exceptions import LDAPEntryAlreadyExistsResult
from requests.auth import HTTPBasicAuth
import sys
import urllib.parse
import urllib3

# --- Environment variable definitions (renamed for carddav2ldap project) ---
# CardDAV base URL for discovering address books (e.g., "https://your.carddav.server/dav.php/addressbooks/user/")
# This URL should list all your address books as sub-collections.
CARDDAV_BASE_DISCOVERY_URL = os.getenv("CARDDAV_BASE_DISCOVERY_URL")
# CardDAV username
CARDDAV_USERNAME = os.getenv("CARDDAV_USERNAME")
# CardDAV password
CARDDAV_PASSWORD = os.getenv("CARDDAV_PASSWORD")
# CardDAV SSL verification. Set to "true" or "false". (e.g., "true" to verify, "false" to skip)
CARDDAV_SSL_VERIFY = os.getenv("CARDDAV_SSL_VERIFY")


# LDAP server address (e.g., "ldap://localhost:389")
LDAP_SERVER = os.getenv("LDAP_SERVER")
# LDAP base DN for contacts (e.g., "ou=contacts,dc=yourdomain,dc=local")
LDAP_BASE_DN = os.getenv("LDAP_BASE_DN")
# LDAP bind username (e.g., "cn=admin,dc=yourdomain,dc=local")
LDAP_USER = os.getenv("LDAP_USER")
# LDAP bind password
LDAP_PASSWORD = os.getenv("LDAP_PASSWORD")

# --- Helper function to get environment variables or exit ---
def get_env_or_exit(var_name):
    """
    Retrieves an environment variable. Exits if the variable is not set.
    """
    value = os.getenv(var_name)
    if not value:
        print(f"ERROR: Environment variable '{var_name}' is not set. Please set it and retry.")
        sys.exit(1)
    return value

def get_boolean_env(var_name, default=False):
    """
    Retrieves a boolean environment variable. Returns default if not set or invalid.
    Expects "true" or "false" (case-insensitive).
    """
    value = os.getenv(var_name)
    if value is None:
        return default
    return value.lower() == "true"

# --- Fetch environment variables ---
carddav_base_discovery_url = get_env_or_exit("CARDDAV_BASE_DISCOVERY_URL")
carddav_username = get_env_or_exit("CARDDAV_USERNAME")
carddav_password = get_env_or_exit("CARDDAV_PASSWORD")
ssl_verify = get_boolean_env("CARDDAV_SSL_VERIFY", default=True) # Default to True for security

ldap_server_url = get_env_or_exit("LDAP_SERVER")
ldap_user = get_env_or_exit("LDAP_USER")
ldap_password = get_env_or_exit("LDAP_PASSWORD")
ldap_base_dn = get_env_or_exit("LDAP_BASE_DN")

# Suppress InsecureRequestWarning if SSL verification is disabled
if not ssl_verify:
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

print("Starting contact synchronization from CardDAV to LDAP (Project carddav2ldap)...")

# --- 1. Discover all address book URLs from CardDAV server ---
print(f"Discovering address books from: {carddav_base_discovery_url}")
discovery_headers = {
    "Depth": "1",  # Request depth 1 to get direct child collections
    "Content-Type": "application/xml; charset=UTF-8",
}
# XML body for PROPFIND request to discover collections and addressbooks
discovery_body = """<?xml version="1.0" encoding="utf-8" ?>
<D:propfind xmlns:D="DAV:" xmlns:C="urn:ietf:params:xml:ns:carddav">
  <D:prop>
    <D:resourcetype/>
    <D:displayname/>
  </D:prop>
</D:propfind>"""

address_book_urls = []
try:
    discovery_response = requests.request(
        method="PROPFIND",
        url=carddav_base_discovery_url,
        headers=discovery_headers,
        data=discovery_body.encode("utf-8"),
        auth=HTTPBasicAuth(carddav_username, carddav_password),
        verify=ssl_verify # Use the SSL verification setting from environment variable
    )
    discovery_response.raise_for_status()

except requests.exceptions.RequestException as e:
    print(f"ERROR: Failed to connect to CardDAV server for discovery or fetch data: {e}")
    sys.exit(1)

if discovery_response.status_code != 207:
    print(f"ERROR: CardDAV PROPFIND for discovery failed. Expected 207 Multi-Status, got {discovery_response.status_code}.")
    print("Please check your CARDDAV_BASE_DISCOVERY_URL, CARDDAV_USERNAME, and CARDDAV_PASSWORD.")
    sys.exit(1)

discovery_ns = {
    "d": "DAV:",
    "c": "urn:ietf:params:xml:ns:carddav"
}
discovery_root = ET.fromstring(discovery_response.text)

# Find all <D:response> elements and check if they represent an addressbook
for response_elem in discovery_root.findall(".//d:response", discovery_ns):
    href_elem = response_elem.find(".//d:href", discovery_ns)
    resourcetype_elem = response_elem.find(".//d:resourcetype", discovery_ns)

    if href_elem is not None and resourcetype_elem is not None:
        # Check if the resourcetype contains <C:addressbook/>
        if resourcetype_elem.find(".//c:addressbook", discovery_ns) is not None:
            relative_url_path = href_elem.text.strip()

            # Use urljoin with the full CARDDAV_BASE_DISCOVERY_URL as the base
            # This correctly handles trailing slashes and absolute vs relative paths for concatenation.
            full_url = urllib.parse.urljoin(carddav_base_discovery_url, relative_url_path)

            address_book_urls.append(full_url)

if not address_book_urls:
    print("WARNING: No address books found at the specified CARDDAV_BASE_DISCOVERY_URL.")
    # Attempt to use CARDDAV_BASE_DISCOVERY_URL itself as a single address book if no others found.
    # This covers cases where the discovery URL IS the address book.
    print(f"Attempting to use {carddav_base_discovery_url} as a single address book.")
    address_book_urls.append(carddav_base_discovery_url)


print(f"Found {len(address_book_urls)} address book(s) to process.")

# --- 2. Fetch and parse contacts from each discovered address book ---
all_parsed_contacts = []
for book_url in address_book_urls:
    print(f"Fetching contacts from address book: {book_url}")
    contact_headers = {
        "Depth": "1",  # Request depth 1 to get direct child resources (contacts)
        "Content-Type": "application/xml; charset=UTF-8",
    }
    # XML body for PROPFIND request to get address-data (vCard content) for contacts
    contact_body = """<?xml version="1.0" encoding="utf-8" ?>
    <D:propfind xmlns:D="DAV:" xmlns:C="urn:ietf:params:xml:ns:carddav">
      <D:prop>
        <D:href/>
        <C:address-data/>
      </D:prop>
    </D:propfind>"""

    try:
        response = requests.request(
            method="PROPFIND",
            url=book_url,
            headers=contact_headers,
            data=contact_body.encode("utf-8"),
            auth=HTTPBasicAuth(carddav_username, carddav_password),
            verify=ssl_verify # Use the SSL verification setting from environment variable
        )
        response.raise_for_status() # Raise an exception for HTTP errors (4xx or 5xx)

    except requests.exceptions.RequestException as e:
        print(f"ERROR: Failed to fetch contacts from {book_url}: {e}")
        continue # Continue to the next address book

    if response.status_code != 207:
        print(f"ERROR: CardDAV PROPFIND for {book_url} failed. Expected 207 Multi-Status, got {response.status_code}.")
        continue # Continue to the next address book

    contact_ns = {
        "d": "DAV:", # DAV namespace
        "c": "urn:ietf:params:xml:ns:carddav" # CardDAV namespace
    }
    contact_root = ET.fromstring(response.text)

    # Find all <c:address-data> elements containing vCard blobs
    for elem in contact_root.findall(".//c:address-data", contact_ns):
        vcard_blob = elem.text
        if not vcard_blob:
            continue
        try:
            # Parse the vCard string using vobject
            vobj = vobject.readOne(vcard_blob)

            # Extract Full Name (FN)
            fn_obj = getattr(vobj, "fn", None)
            full_name = fn_obj.value if fn_obj else ""

            # Extract Given Name (FIRST NAME from N property) and Surname (LAST NAME from N property)
            given_name = ""
            surname = ""
            n_obj = getattr(vobj, "n", None)
            if n_obj:
                given_name = n_obj.first if hasattr(n_obj, 'first') and n_obj.first else ""
                surname = n_obj.last if hasattr(n_obj, 'last') and n_obj.last else ""

            # Fallback for full_name if FN is missing (existing logic, adjusted for n_obj attributes)
            if not full_name:
                # If FN is empty, try to construct full_name from N (FirstName LastName)
                if given_name and surname:
                    full_name = f"{given_name} {surname}"
                elif given_name:
                    full_name = given_name
                elif surname:
                    full_name = surname

            # Final fallback if still no full name
            if not full_name:
                 full_name = "Unknown Contact"

            # Fallback for surname if not extracted from N (e.g., if only FN was present)
            if not surname and full_name and ' ' in full_name:
                surname = full_name.split()[-1]


            # Extract Email addresses
            emails = [e.value for e in getattr(vobj, "email_list", [])]

            # Extract Telephone numbers
            phones = [t.value for t in getattr(vobj, "tel_list", [])]

            all_parsed_contacts.append({
                "full_name": full_name,
                "surname": surname,
                "given_name": given_name,
                "emails": emails,
                "phones": phones
            })
        except Exception as e:
            print(f"WARNING: Could not parse vCard blob from {book_url}. Blob start: {vcard_blob[:100]}... Error: {e}")
            continue

print(f"Successfully parsed a total of {len(all_parsed_contacts)} contacts from all address books.")

# --- 3. Connect to LDAP Server ---
try:
    server = ldap3.Server(ldap_server_url, port=389, use_ssl=False) # Adjust port and use_ssl if needed
    # Using string literals for client_strategy and authentication
    conn = ldap3.Connection(server, user=ldap_user, password=ldap_password,
                      auto_bind=True, client_strategy='SYNC', # Changed to string literal 'SYNC'
                      authentication='SIMPLE') # Changed to string literal 'SIMPLE'

    if not conn.bind():
        print(f"ERROR: LDAP bind failed: {conn.result}")
        # Added debug print for LDAP bind
        print(f"DEBUG: LDAP User: '{ldap_user}'")
        print(f"DEBUG: LDAP Server URL: '{ldap_server_url}'")
        sys.exit(1)
    print("Successfully connected and bound to LDAP server.")

except Exception as e:
    print(f"ERROR: Failed to connect to LDAP server: {e}")
    sys.exit(1)

# --- 4. Import contacts into LDAP ---
print("Importing contacts into LDAP...")
for contact in all_parsed_contacts:
    # Construct the DN (Distinguished Name) for the LDAP entry
    # Using 'cn' (Common Name) for the RDN (Relative Distinguished Name)
    # Be careful with special characters in full_name for DN. It's good practice to sanitize/escape.
    # For simplicity, we are using it directly here.
    ldap_dn = f"cn={contact['full_name']},{ldap_base_dn}"

    # Define LDAP attributes for the entry
    attributes = {
        'objectClass': ['inetOrgPerson', 'top'], # Required object classes for a person entry
        'cn': contact['full_name'],
        'sn': contact['surname'],
        'givenName': contact['given_name'] # Add givenName, even if empty
    }

    # Add optional attributes if they exist
    if contact['emails']:
        attributes['mail'] = contact['emails'][0] # Take the first email
    if contact['phones']:
        attributes['telephoneNumber'] = contact['phones'][0] # Take the first phone number

    # Debug print for constructed LDAP entry
    print(f"DEBUG: Attempting to add DN: '{ldap_dn}' with attributes: {attributes}")

    try:
        # Attempt to add the entry
        conn.add(ldap_dn, attributes=attributes)
        if conn.result['description'] == 'success':
            print(f"Added contact: {contact['full_name']}")
        elif conn.result['description'] == 'entryAlreadyExists':
            print(f"Contact already exists (skipping update for now): {contact['full_name']}")
            # Implement update logic here if desired (e.g., conn.modify)
        else:
            print(f"WARNING: Failed to add/update contact {contact['full_name']}: {conn.result}")

    except LDAPEntryAlreadyExistsResult: # Catching the specific exception
        print(f"Contact '{contact['full_name']}' already exists in LDAP. Skipping.")
    except Exception as e:
        print(f"ERROR: Failed to add contact '{contact['full_name']}' to LDAP: {e}")

# --- 5. Disconnect from LDAP ---
conn.unbind()
print("Disconnected from LDAP server.")
print("Synchronization process completed.")

