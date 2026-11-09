"""Explicit deployment backend selection; credentials stay server-side.

Hosted Admin Room uses the deployment's existing PostgreSQL connection. The
legacy phone gateway is retained only for deployments which opt into that
workflow, never as a fallback from a configured hosted workspace.
"""
import os


def hosted_enabled():
    return os.getenv('POLITICSHUB_ADMIN_BACKEND', '').strip().lower() == 'hosted'
