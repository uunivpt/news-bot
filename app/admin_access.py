"""Deployment-owned owner identity and bounded database-outage access.

Only password verifiers live in this server module. Environment configuration
can replace or disable the packaged identity. Recovery sessions are deliberately
separate from database-authorized owner sessions and never allow mutations.
"""
import json
import os
import re
from werkzeug.security import check_password_hash

PACKAGED_USERS = {'pushkarthawari': 'scrypt:32768:8:1$IWw9ufyR5buOJJWZ$3ca4377e28498a7c97d39638e8c1420b94c5311da6d23f99024b27ab0c0d49f79d2091c63bdc375b9b9ca9e74eb69bb3ab13bcd4c5646600e0d97e19286d74db'}


def configured_users():
    raw = os.environ.get('ADMIN_USERS_JSON')
    if raw is None:
        return dict(PACKAGED_USERS)
    try:
        value = json.loads(raw)
        return value if isinstance(value, dict) else {}
    except (ValueError, TypeError):
        return {}


def valid_verifier(username, verifier):
    return (bool(re.fullmatch(r'[A-Za-z0-9._-]{3,40}', str(username)))
            and isinstance(verifier, str)
            and verifier.startswith(('scrypt:', 'pbkdf2:'))
            and verifier.count('$') == 2 and 60 <= len(verifier) <= 1000)


def verify_recovery_owner(username, password):
    verifier = configured_users().get(username)
    if not valid_verifier(username, verifier):
        return False
    try:
        return check_password_hash(verifier, password)
    except (ValueError, TypeError):
        return False
