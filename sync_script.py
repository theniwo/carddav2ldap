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
import binascii # Import for Base64 decoding errors
import base64   # Import for Base64 encoding/dekoding if needed for PHOTO field
import re       # Import for regular expressions to clean phone numbers

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
# Set to "true" to import photos from vCards into LDAP (jpegPhoto attribute). Default is "false".
CARDDAV_IMPORT_PHOTOS = os.getenv("CARDDAV_IMPORT_PHOTOS")

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
    Includes debug print to show value before exiting.
    """
    value = os.getenv(var_name)
    if not value:
        # Print to stderr so it's always visible in logs, even if stdout is buffered
        print(f"ERROR: Environment variable '{var_name}' is not set. Current value received: '{value}'. Please set it and retry.", file=sys.stderr)
        sys.stderr.flush() # Ensure it's flushed immediately
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
carddav_password = os.getenv("CARDDAV_PASSWORD") # Get password value as is for requests auth
ssl_verify = get_boolean_env("CARDDAV_SSL_VERIFY", default=True) # Default to True for security
import_photos = get_boolean_env("CARDDAV_IMPORT_PHOTOS", default=False) # Default to False for photo import
# Use the global 'DEBUG' variable to control Python debug output
debug_python_enabled = get_boolean_env("DEBUG", default=False)

# Get CENSOR_SECRETS_IN_LOGS setting from environment for Python script
censor_secrets_in_logs_enabled = get_boolean_env("CENSOR_SECRETS_IN_LOGS", default=True)


ldap_server_url = get_env_or_exit("LDAP_SERVER")
ldap_user = get_env_or_exit("LDAP_USER")
ldap_password = os.getenv("LDAP_PASSWORD") # Get password value as is for ldap3 bind
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
    # This covers cases where the discovery URL IS the the address book.
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
            full_name = str(fn_obj.value).strip() if fn_obj and fn_obj.value else ""

            # Extract Given Name (FIRST NAME from N property) and Surname (LAST NAME from N property)
            given_name = ""
            surname = ""
            n_obj = getattr(vobj, "n", None)
            if n_obj:
                # Ensure attributes exist before accessing and normalize to str
                given_name = str(getattr(n_obj, 'first', '')).strip()
                surname = str(getattr(n_obj, 'last', '')).strip()

            # Fallback for full_name if FN is missing (existing logic, adjusted for n_obj attributes)
            if not full_name:
                # If FN is empty, try to construct full_name from N (FirstName LastName)
                if given_name and surname:
                    full_name = f"{given_name} {surname}".strip()
                elif given_name:
                    full_name = given_name.strip()
                elif surname:
                    full_name = surname.strip()

            # Final fallback if still no full name
            if not full_name:
                 full_name = "Unknown Contact"

            # Fallback for surname: Ensure it's never empty if full_name exists, to satisfy LDAP schema requirements.
            # This is specifically to address objectClassViolation for 'sn' in inetOrgPerson.
            if not surname and full_name:
                # If the full_name is a multi-word string, take the last word as surname.
                if ' ' in full_name and full_name != "Unknown Contact":
                    surname = full_name.split()[-1].strip()
                else:
                    # If full_name is a single word or no clear surname can be extracted,
                    # use the full_name itself as surname. This satisfies 'sn' requirement.
                    surname = full_name.strip()

            # Final check: If surname is STILL empty after all fallbacks, set a placeholder.
            # This handles cases where full_name might also be empty or derived as empty.
            if not surname:
                surname = "N/A" # Placeholder for required 'sn' attribute


            # Extract Email addresses
            emails = [str(e.value).strip() for e in getattr(vobj, "email_list", []) if e.value]

            # --- Extract and categorize Telephone numbers ---
            # Store all cleaned phone numbers in separate lists based on type
            all_cleaned_phones = [] # For the general 'telephoneNumber' attribute
            home_phones = []
            mobile_phones = []
            fax_numbers = []

            for tel_obj in getattr(vobj, "tel_list", []):
                raw_phone = str(tel_obj.value).strip()
                cleaned_phone = re.sub(r'[^0-9+]', '', raw_phone).strip()
                if cleaned_phone == '+': # Handle case where only '+' remains after cleaning
                    cleaned_phone = ''

                if cleaned_phone: # Only process non-empty cleaned numbers
                    all_cleaned_phones.append(cleaned_phone) # Add to general list

                    types = [t.upper() for t in getattr(tel_obj, 'type_param', [])]

                    if 'FAX' in types:
                        fax_numbers.append(cleaned_phone)
                    if 'CELL' in types or 'MOBILE' in types:
                        mobile_phones.append(cleaned_phone)
                    if 'HOME' in types:
                        home_phones.append(cleaned_phone)

            # --- Extract Address Information (Street, City, Postal Code) ---
            # The ADR property can have multiple parts. We'll take the first one found.
            # vCard ADR format: Post Office Box;Extended Address;Street Address;Locality;Region;Postal Code;Country Name
            street_address = ""
            locality = ""
            postal_code = ""

            adr_obj_list = getattr(vobj, 'adr_list', [])
            if adr_obj_list:
                first_adr = adr_obj_list[0] # Take the first address
                street_address = str(getattr(first_adr, 'street', '')).strip()
                locality = str(getattr(first_adr, 'city', '')).strip() # 'city' maps to Locality
                postal_code = str(getattr(first_adr, 'code', '')).strip() # 'code' maps to Postal Code

            # --- Extract Organization (Company Name) and Organizational Unit (Department) ---
            organization = ""
            organizational_unit = ""
            org_obj = getattr(vobj, 'org', None)
            if org_obj and org_obj.value:
                if isinstance(org_obj.value, list):
                    if len(org_obj.value) > 0:
                        organization = str(org_obj.value[0]).strip()
                    if len(org_obj.value) > 1:
                        organizational_unit = str(org_obj.value[1]).strip()
                elif isinstance(org_obj.value, str):
                    # Handle single string ORG value, assume it's the organization
                    organization = str(org_obj.value).strip()

            # --- Extract Job Title ---
            job_title = ""
            title_obj = getattr(vobj, 'title', None)
            if title_obj and title_obj.value:
                job_title = str(title_obj.value).strip()

            # --- Extract Categories ---
            categories = []
            categories_obj = getattr(vobj, 'categories', None)
            if categories_obj and categories_obj.value:
                # CATEGORIES value can be a comma-separated string or a list
                if isinstance(categories_obj.value, str):
                    categories = [str(cat).strip() for cat in categories_obj.value.split(',') if str(cat).strip()]
                elif isinstance(categories_obj.value, list):
                    categories = [str(cat).strip() for cat in categories_obj.value if str(cat).strip()]

            # Handle photo data if CARDDAV_IMPORT_PHOTOS is enabled
            jpeg_photo_data = None
            if import_photos:
                photo_obj = getattr(vobj, 'photo', None)
                if photo_obj and hasattr(photo_obj, 'value') and photo_obj.value:
                    if isinstance(photo_obj.value, bytes):
                        # If vobject already decoded it to bytes, use directly
                        jpeg_photo_data = photo_obj.value
                    elif isinstance(photo_obj.value, str):
                        # If for some reason it's a string, try base64 decoding it
                        try:
                            jpeg_photo_data = base64.b64decode(photo_obj.value)
                        except binascii.Error as decode_err:
                            print(f"WARNING: Photo data for '{full_name}' from '{book_url}' is string but invalid Base64. Error: {decode_err}. Skipping photo.")
                            jpeg_photo_data = None
                        except Exception as decode_err:
                            print(f"WARNING: Unexpected error decoding photo data for '{full_name}' from '{book_url}'. Error: {decode_err}. Skipping photo.")
                            jpeg_photo_data = None
                    else:
                        print(f"WARNING: Unexpected photo data type for '{full_name}' from '{book_url}': {type(photo_obj.value)}. Skipping photo.")
                        jpeg_photo_data = None


            all_parsed_contacts.append({
                "full_name": full_name,
                "surname": surname,
                "given_name": given_name,
                "emails": emails,
                "all_phones": all_cleaned_phones, # General list of all phones
                "home_phones": home_phones,
                "mobile_phones": mobile_phones,
                "fax_numbers": fax_numbers,
                "street_address": street_address, # New address field
                "locality": locality,             # New address field
                "postal_code": postal_code,       # New address field
                "organization": organization,     # New organization field
                "organizational_unit": organizational_unit, # New organizational unit field
                "job_title": job_title,           # New job title field
                "categories": categories,         # New categories field
                "jpeg_photo": jpeg_photo_data # Add photo data here
            })
        except binascii.Error as e:
            # Catch specific Base64 decoding errors during initial vCard parsing
            print(f"ERROR: Base64 decoding failed for vCard from {book_url}. Error: {e}. Problematic vCard blob starts: {vcard_blob[:200]}...")
            continue # Skip this problematic vCard and continue with others
        except Exception as e:
            # General error for other parsing issues
            print(f"WARNING: Could not parse vCard blob from {book_url}. Error: {e}. Blob start: {vcard_blob[:200]}...")
            continue

print(f"Successfully parsed a total of {len(all_parsed_contacts)} contacts from all address books.")

# --- 3. Connect to LDAP Server ---
try:
    server = ldap3.Server(ldap_server_url, port=389, use_ssl=False) # Adjust port and use_ssl if needed
    # client_encoding was removed as it caused 'unexpected keyword argument' error on some ldap3 versions.
    # Python 3 strings are Unicode, and ldap3 should handle UTF-8 encoding by default.
    conn = ldap3.Connection(server, user=ldap_user, password=ldap_password,
                      auto_bind=True, client_strategy='SYNC', # Changed to string literal 'SYNC'
                      authentication='SIMPLE') # Changed to string literal 'SIMPLE'

    if not conn.bind():
        print(f"ERROR: LDAP bind failed: {conn.result}")
        # Added debug print for LDAP bind values for invalidDNSyntax diagnosis
        if debug_python_enabled: # Only print if debug_python_enabled
            print(f"DEBUG: LDAP User (bind_dn): '{ldap_user}'")
            sys.stdout.flush() # Flush print statement immediately
            # Censor password if required by CENSOR_SECRETS_IN_LOGS
            if censor_secrets_in_logs_enabled:
                print(f"DEBUG: LDAP Password: [REDACTED]")
            else:
                print(f"DEBUG: LDAP Password length: {len(ldap_password) if ldap_password else 0} (not printed for security)")
            sys.stdout.flush() # Flush print statement immediately
            print(f"DEBUG: LDAP Server URL: '{ldap_server_url}'")
            sys.stdout.flush() # Flush print statement immediately
            print(f"DEBUG: LDAP Base DN: '{ldap_base_dn}'") # Crucial for DN syntax
            sys.stdout.flush() # Flush print statement immediately
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
    # Ensure CN is properly encoded for the DN string itself
    ldap_dn = f"cn={contact['full_name']},{ldap_base_dn}"

    # Define LDAP attributes for the entry
    # All values are now expected to be Python unicode strings from parsing.
    # We will explicitly encode them to bytes before sending to LDAP, to enforce UTF-8.
    attributes = {
        'objectClass': ['inetOrgPerson', 'organizationalPerson', 'person', 'top'], # Added organizationalPerson and person
        'cn': contact['full_name'].encode('utf-8'), # Explicitly encode
        'sn': contact['surname'].encode('utf-8') # Explicitly encode
    }

    # Add givenName attribute ONLY if it has a non-empty value
    if contact['given_name']:
        attributes['givenName'] = contact['given_name'].encode('utf-8') # Explicitly encode

    # Add various phone number attributes
    # telephoneNumber (general) should take only the first available number if multi-valued is not supported.
    if contact['all_phones']:
        # If 'telephoneNumber' in your LDAP schema is single-valued, take only the first.
        attributes['telephoneNumber'] = contact['all_phones'][0].encode('utf-8') # Explicitly encode
    if contact['home_phones']:
        attributes['homePhone'] = [p.encode('utf-8') for p in contact['home_phones']] # Explicitly encode list elements
    if contact['mobile_phones']:
        attributes['mobile'] = [p.encode('utf-8') for p in contact['mobile_phones']] # Explicitly encode list elements
    if contact['fax_numbers']:
        attributes['facsimileTelephoneNumber'] = [p.encode('utf-8') for p in contact['fax_numbers']] # Explicitly encode list elements

    # Add optional attributes if they exist
    if contact['emails']:
        raw_email = contact['emails'][0] # Already stripped during parsing
        # A very basic email regex, can be expanded if needed
        if re.match(r"[^@]+@[^@]+\.[^@]+", raw_email):
            attributes['mail'] = raw_email.encode('utf-8') # Explicitly encode
        else:
            print(f"WARNING: Email for '{contact['full_name']}' is malformed: '{raw_email}'. Skipping email attribute.")

    # Add address attributes only if they have non-empty values
    if contact['street_address']:
        attributes['streetAddress'] = contact['street_address'].encode('utf-8') # Explicitly encode
    if contact['locality']:
        attributes['l'] = contact['locality'].encode('utf-8') # Explicitly encode
    if contact['postal_code']:
        attributes['postalCode'] = contact['postal_code'].encode('utf-8') # Explicitly encode

    # Add Organization (Company Name)
    if contact['organization']:
        attributes['o'] = contact['organization'].encode('utf-8') # Explicitly encode

    # Add Organizational Unit (Department)
    if contact['organizational_unit']:
        attributes['ou'] = contact['organizational_unit'].encode('utf-8') # Explicitly encode

    # Add Job Title
    if contact['job_title']:
        attributes['title'] = contact['job_title'].encode('utf-8') # Explicitly encode

    # Add Categories
    if contact['categories']:
        attributes['businessCategory'] = [c.encode('utf-8') for c in contact['categories']] # Explicitly encode list elements

    # Add jpegPhoto attribute if photo data is available
    if contact['jpeg_photo']:
        attributes['jpegPhoto'] = contact['jpeg_photo'] # Already bytes or None

    # Debug print for constructed LDAP entry
    if debug_python_enabled: # Only print if debug_python_enabled
        # Create a copy of attributes to censor for printing
        # For display, values should be strings. Decode bytes if they were explicitly encoded.
        display_attributes = {}
        for key, value in attributes.items():
            if key == 'jpegPhoto': # Handle binary photo data separately
                # Do not attempt to decode binary photo data as UTF-8
                display_attributes[key] = '[REDACTED_PHOTO_DATA]' if censor_secrets_in_logs_enabled else 'Bytes (not displayed)'
            elif isinstance(value, list):
                # Ensure all elements in lists are strings for display
                # Only decode if the item is bytes, otherwise keep as is (already string or other type)
                display_attributes[key] = [v.decode('utf-8') if isinstance(v, bytes) else v for v in value]
            elif isinstance(value, bytes):
                # Decode bytes to string for display (for other string attributes that were encoded)
                display_attributes[key] = value.decode('utf-8')
            else:
                # Use value as is (already string or other type)
                display_attributes[key] = value

        if censor_secrets_in_logs_enabled:
            # Censor email and phone
            if 'mail' in display_attributes:
                display_attributes['mail'] = '[REDACTED_EMAIL]'
            # Censor all phone list attributes
            if 'telephoneNumber' in display_attributes:
                if isinstance(display_attributes['telephoneNumber'], str):
                    display_attributes['telephoneNumber'] = '[REDACTED_PHONE]'
                elif isinstance(display_attributes['telephoneNumber'], list):
                    display_attributes['telephoneNumber'] = ['[REDACTED_PHONE]' for _ in display_attributes['telephoneNumber']]

            if 'homePhone' in display_attributes:
                display_attributes['homePhone'] = ['[REDACTED_PHONE]' for _ in display_attributes['homePhone']]
            if 'mobile' in display_attributes:
                display_attributes['mobile'] = ['[REDACTED_PHONE]' for _ in display_attributes['mobile']]
            if 'facsimileTelephoneNumber' in display_attributes:
                display_attributes['facsimileTelephoneNumber'] = ['[REDACTED_FAX]' for _ in display_attributes['facsimileTelephoneNumber']]
            # Censor address fields
            if 'streetAddress' in display_attributes:
                display_attributes['streetAddress'] = '[REDACTED_STREET]'
            if 'l' in display_attributes:
                display_attributes['l'] = '[REDACTED_LOCALITY]'
            if 'postalCode' in display_attributes:
                display_attributes['postalCode'] = '[REDACTED_POSTAL_CODE]'
            # Censor organization and categories
            if 'o' in display_attributes:
                display_attributes['o'] = '[REDACTED_ORG]'
            if 'ou' in display_attributes:
                display_attributes['ou'] = '[REDACTED_OU]'
            if 'title' in display_attributes:
                display_attributes['title'] = '[REDACTED_TITLE]'
            if 'businessCategory' in display_attributes:
                display_attributes['businessCategory'] = ['[REDACTED_CATEGORY]' for _ in display_attributes['businessCategory']]

        print(f"DEBUG: Parsed contact data (before LDAP operation): {contact}") # Added for troubleshooting
        print(f"DEBUG: Attempting to add DN: '{ldap_dn}' with attributes: {display_attributes}")
        sys.stdout.flush() # Flush print statement immediately

    try:
        # Attempt to add the entry
        conn.add(ldap_dn, attributes=attributes)
        if conn.result['description'] == 'success':
            print(f"Added contact: {contact['full_name']}")
        elif conn.result['description'] == 'entryAlreadyExists':
            print(f"Contact '{contact['full_name']}' already exists. Attempting to update.")
            # Prepare changes for modify operation
            changes = {}
            for attr_name, attr_value in attributes.items():
                if isinstance(attr_value, list):
                    # For multi-valued attributes, use the list directly for replacement
                    changes[attr_name] = [(ldap3.MODIFY_REPLACE, attr_value)]
                else:
                    # For single-valued attributes, wrap in a list for replacement
                    changes[attr_name] = [(ldap3.MODIFY_REPLACE, [attr_value])]

            # Perform the modify operation
            conn.modify(ldap_dn, changes)
            if conn.result['description'] == 'success':
                print(f"Updated contact: {contact['full_name']}")
            else:
                print(f"WARNING: Failed to update contact {contact['full_name']}: {conn.result}")
        else:
            print(f"WARNING: Failed to add/update contact {contact['full_name']}: {conn.result}")

    except LDAPEntryAlreadyExistsResult: # This specific exception is now handled within the try block
        pass # The logic for update is now within the 'elif' condition for 'entryAlreadyExists'
    except Exception as e:
        print(f"ERROR: Failed to add/update contact '{contact['full_name']}' to LDAP: {e}")

# --- 5. Disconnect from LDAP ---
conn.unbind()
print("Disconnected from LDAP server.")
print("Synchronization process completed.")

