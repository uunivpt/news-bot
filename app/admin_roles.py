"""Server-enforced newsroom permissions. Only the named principal owns hiring."""
import hashlib
import re

PRIMARY_OWNER = 'pushkarthawari'
READ = {'news.read'}
ROLES = {
    'viewer': ('Viewer', READ),
    'reporter': ('Reporter', READ | {'news.create'}),
    'editor': ('Editor', READ | {'news.create', 'news.edit', 'news.process'}),
    'publisher': ('Publisher / verification desk', READ | {'news.create', 'news.edit', 'news.process', 'news.publish', 'news.reject'}),
    'analyst': ('Analyst', READ | {'reports.read', 'operations.read'}),
    'administrator': ('Administrator', READ | {'news.create', 'news.edit', 'news.process', 'news.publish', 'news.reject', 'reports.read', 'operations.read', 'settings.manage', 'training.manage', 'activity.read'}),
}
ALL = set().union(*(value[1] for value in ROLES.values())) | {'users.manage'}


def effective_role(username, stored_role):
    if stored_role == 'disabled': return 'disabled'
    if username == PRIMARY_OWNER: return 'owner'
    # Existing owner accounts retain operating access, never hiring authority.
    return 'administrator' if stored_role == 'owner' else stored_role if stored_role in ROLES else 'viewer'


def permissions(username, stored_role):
    role = effective_role(username, stored_role)
    return sorted(ALL if role == 'owner' else ROLES.get(role, ('', set()))[1])


def verifier_tag(verifier):
    return hashlib.sha256(str(verifier).encode()).hexdigest()


def required_permission(path, method):
    if path.startswith('/api/admin/editorial/readiness'): return 'reports.read'
    if path.endswith('/assign') and path.startswith('/api/admin/editorial/story/'):return 'users.manage'
    if path.startswith('/api/admin/studio/'):
        return 'news.create' if path.endswith('/prepare') else 'news.edit' if path.endswith('/save') else 'news.read'
    if path.startswith('/api/admin/editorial/'):
        if method in {'GET','HEAD'}:return 'news.read'
        if re.search(r'/updates/\d+/publish$',path):return 'news.publish'
        return 'news.edit'
    if path.startswith('/api/admin/users'): return 'users.manage'
    if path.startswith('/api/admin/diagnostics') or path in {'/api/admin/report', '/api/admin/operations.pdf'}: return 'reports.read'
    if path == '/api/admin/activity': return 'activity.read'
    if path == '/api/admin/settings': return 'settings.manage'
    if path == '/api/admin/training': return 'training.manage'
    if path in {'/api/admin/dashboard','/api/admin/operations','/api/admin/upgrade','/api/admin/history','/api/admin/live'}: return 'operations.read'
    if method not in {'GET','HEAD','OPTIONS'}:
        if path == '/api/admin/news/create': return 'news.create'
        if path == '/api/fact-check' or path.startswith('/api/admin/verification/'): return 'news.publish'
        match = re.fullmatch(r'/api/news/\d+/(approve|publish|reject|edit|process|ai)', path)
        if match:
            return {'approve':'news.publish','publish':'news.publish','reject':'news.reject','edit':'news.edit','process':'news.process','ai':'news.process'}[match[1]]
        return 'settings.manage'  # New privileged mutations fail closed.
    return 'news.read'
