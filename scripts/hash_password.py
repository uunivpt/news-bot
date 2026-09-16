"""Print a Werkzeug password hash for ADMIN_USERS_JSON.
Run locally: python scripts/hash_password.py"""
from getpass import getpass
from werkzeug.security import generate_password_hash
p=getpass("Password: ")
print(generate_password_hash(p))
