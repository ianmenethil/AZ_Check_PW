import json
from datetime import datetime
from pathlib import Path

import httpx
import pandas as pd
import yaml
from rich.console import Console
from rich.progress import Progress
from rich.traceback import install

OUTPUT_DIR = "output"
CONFIG_FILE = "credentials.yaml"
EMAILS_FILE = "emails.yaml"
ROLES_FILE = "roles.json"
Path(OUTPUT_DIR).mkdir(parents=True, exist_ok=True)

ROLEMEMBERS_FILE = Path("output/rolemembers.json")
PRETTY_ROLEMEMBERS_FILE = Path("output/pretty_rolemembers.csv")

USERDATA_FILE = Path("output/userdata.json")
PRETTY_USERDATA_FILE = Path("output/pretty_userdata.csv")

ROLEMEMBERS_FILE_exist = ROLEMEMBERS_FILE.is_file()
USERDATA_FILE_exist = USERDATA_FILE.is_file()
TODAYSDATE = datetime.today().strftime("%d-%m-%Y")

install()


def get_file_modification_date(file):
    """Get the modification date of the file."""
    return datetime.fromtimestamp(file.stat().st_mtime).strftime("%d-%m-%Y")


def load_yaml(filename):
    """Load YAML file and return its contents."""
    with open(filename, "r", encoding="utf-8") as file:
        return yaml.safe_load(file)


def load_json(filename):
    """Retrieve an access token using the provided credentials."""
    with open(filename, "r", encoding="utf-8") as file:
        return json.load(file)


def get_access_token(credentials, console):
    """Retrieve an access token using the provided credentials."""
    try:
        payload = {
            "grant_type": "client_credentials",
            "client_id": credentials["client_id"],
            "client_secret": credentials["client_secret"],
            "resource": "https://graph.microsoft.com",
        }
        token_endpoint = f'https://login.microsoftonline.com/{credentials["tenant_id"]}/oauth2/token'
        # f'https://login.microsoftonline.com/{credentials["tenant_id"]}/oauth2/v2.0/token'
        response = httpx.post(token_endpoint, data=payload)
        access_token = response.json().get("access_token")
        if access_token:
            console.log("[bold blue]Access token retrieved successfully.")
        else:
            console.log("[bold red]Failed to retrieve access token. Please check your credentials.")
        return access_token
    except Exception as err:
        console.log(f"[bold red]Failed to retrieve access token. Please check your credentials.: {err}")
        console.print_exception()
    return None


def is_account_enabled(user_details):
    """Check if the account is enabled or disabled."""
    return user_details.get("accountEnabled", False)


def get_email_address(user_details, console):
    """Get the email address from the user details.
    Args:   user_details (dict): The dictionary containing user details.
            console: The console object for logging.
    Returns: str: The email address found in the user details, or None if not found."""
    email_fields = [
        "userPrincipalName",
        "mail",
        "otherMails",
        "mailNickname",
        "sipProxyAddress",
        "proxyAddresses",
    ]
    for field in email_fields:
        email = user_details.get(field)
        if email:
            if isinstance(email, list) and email:
                email = email[0]  # Choose the first email if it's a list
            console.log(f"Found email: {email} in field: {field}")
            return email
    console.log("No email found in any of the fields")
    return None


def get_privileged_accounts(access_token, roles, role_data, console):
    """Get privileged accounts from Azure AD based on the provided access token, roles, and role data.
    Args:
        access_token (str): The access token for authentication.
        roles (list): A list of role IDs.
        role_data (dict): A dictionary containing role data.
        console: The console object for logging.
    Returns:
        list: A list of privileged accounts."""
    try:
        privileged_accounts = []
        all_role_members = {}
        for role_id in roles:  # roles is now a list of role IDs
            # console.log(f"Processing role: {role_id} in roles: {roles}")
            role_name = role_data.get(role_id, f"Unknown Role ({role_id})")
            role_endpoint = f"https://graph.microsoft.com/v1.0/directoryRoles/{role_id}/members"
            headers = {"Authorization": f"Bearer {access_token}"}
            response = httpx.get(role_endpoint, headers=headers)
            role_members = response.json().get("value", [])
            all_role_members[role_name] = role_members

            # console.log(f"Processing role: {role_name}")
            if role_members:
                console.log(f"Found {len(role_members)} members in role: {role_name}")
                for member in role_members:
                    # console.log(f"Member:{member}")
                    user_details_endpoint = f"https://graph.microsoft.com/v1.0/users/{member['id']}"
                    # console.log(f"Getting user details for user ID: {member['id']} for member: {member}")
                    user_details_response = httpx.get(user_details_endpoint, headers=headers)
                    # console.log(f"User details response: {user_details_response}")
                    user_details = user_details_response.json()
                    # console.log(json.dumps(user_details, indent=4))
                    # if is_account_enabled(user_details):
                    email = get_email_address(user_details, console)
                    if email:
                        console.log(f"Checking email: {email} for privileged account.")
                        privileged_accounts.append(email)
                    else:
                        console.log(f"No email found for user ID: {member['id']}")
            # else:
            # console.log(f"No members found in role: {role_name}")
        # Save role members data
        save_json(all_role_members, ROLEMEMBERS_FILE)
        read_and_pretty_save(all_role_members, PRETTY_ROLEMEMBERS_FILE)
        return privileged_accounts
    except Exception as e:
        console.log(f"[bold red]An error occurred: {e}")
        console.print_exception()  # Rich formatted traceback


def get_user_details(access_token, user_email, console):
    headers = {"Authorization": f"Bearer {access_token}"}
    console.log(f"Getting user details for: {user_email}")
    # user_endpoint = f"https://graph.microsoft.com/v1.0/users/{user_email}?$count=true&$select=displayName,mail,userPrincipalName,createdDateTime,usageLocation,userType,externalUserState,externalUserStateChangeDateTime,onPremisesSamAccountName,onPremisesSecurityIdentifier,onPremisesSyncEnabled,onPremisesUserPrincipalName,otherMails,passwordPolicies,onPremisesDistinguishedName,onPremisesDomainName,onPremisesLastSyncDateTime,refreshTokensValidFromDateTime,securityIdentifier,signInSessionsValidFromDateTime,id,passwordProfile,identities,signInActivity,accountEnabled{filters}"
    # user_endpoint = f"https://graph.microsoft.com/v1.0/users/{user_email}"
    user_endpoint = f"https://graph.microsoft.com/beta/users/{user_email}"
    # user_endpoint = f"https://graph.microsoft.com/beta/users/{user_email}?$filter=accountEnabled eq true and userType eq 'member'"
    response = httpx.get(user_endpoint, headers=headers)
    return response.json()


def save_json(data, filename):
    file_path = Path(f"{filename}")
    file_content = json.dumps(data, indent=4)
    file_path.write_text(file_content)


def flatten_json(nested_json, exclude=None):
    if exclude is None:
        exclude = [""]
    out = {}

    def flatten(x, name="", exclude=exclude):
        # trunk-ignore(pylint/C0123)
        if type(x) is dict:
            for a in x:
                if a not in exclude:
                    flatten(x[a], name + a + "_")
        # trunk-ignore(pylint/C0123)
        elif type(x) is list:
            i = 0
            for a in x:
                flatten(a, name + str(i) + "_")
                i += 1
        else:
            out[name[:-1]] = x
    flatten(nested_json)
    return out


def read_and_pretty_save(data, output_file_path):
    if isinstance(data, str):
        data = json.loads(data)
    flat_data = [flatten_json(item) for item in data]
    df = pd.DataFrame(flat_data)
    df.to_csv(output_file_path, index=False)


def main():
    console = Console()
    with console.status("[bold green]Starting the script...[/]", spinner="dots"):
        MEMBERS_DATADATE = (get_file_modification_date(ROLEMEMBERS_FILE)if ROLEMEMBERS_FILE_exist else None)
        USER_DATADATE = (get_file_modification_date(USERDATA_FILE) if USERDATA_FILE_exist else None)
        if (ROLEMEMBERS_FILE_exist and USERDATA_FILE_exist and MEMBERS_DATADATE == TODAYSDATE):
            console.log("Role members files exist and are up to date. Skipping API calls.")
            return
        try:
            credentials = load_yaml(CONFIG_FILE)["azure_ad"]
            # access_token = get_access_token(credentials, console)
            # if access_token:
            if access_token := get_access_token(credentials, console):
                role_data = load_json(ROLES_FILE)
                roles = list(role_data.keys())
                if not ROLEMEMBERS_FILE_exist or not MEMBERS_DATADATE:
                    privileged_emails = get_privileged_accounts(access_token, roles, role_data, console)
                    if not privileged_emails:
                        console.log("[bold red]No privileged accounts found.")
                        return
                    console.log(f"[bold yellow]Privileged emails fetched: {len(privileged_emails)}")
                else:
                    privileged_emails = []
                if not USERDATA_FILE_exist or not USER_DATADATE:
                    all_data = []
                    with Progress() as progress:
                        task = progress.add_task("[cyan]Fetching user details...", total=len(privileged_emails),)
                        for email in privileged_emails:
                            user_data = get_user_details(access_token, email, console)
                            all_data.append(user_data)
                            progress.update(task, advance=1)
                    save_json(all_data, USERDATA_FILE)
                    read_and_pretty_save(all_data, PRETTY_USERDATA_FILE)
                    console.log("[bold green]Pretty version saved to: ", PRETTY_USERDATA_FILE)
        except Exception as e:
            console.log(f"[bold red]An error occurred: {e}")
            console.print_exception()


if __name__ == "__main__":
    main()