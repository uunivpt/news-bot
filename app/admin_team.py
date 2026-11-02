"""Main-owner account lifecycle; credentials are disclosed only on creation/reset."""
from datetime import datetime, timezone
import re
import secrets
from flask import jsonify, request, session
from werkzeug.security import generate_password_hash
from .admin_roles import PRIMARY_OWNER, ROLES, effective_role, permissions


def register_team_routes(app, database_factory, require_admin, require_csrf):
    @app.get('/api/admin/users')
    def team_directory():
        error = require_admin()
        if error: return error
        database = database_factory()
        try:
            rows = database.conn.execute('SELECT username,role,created_at FROM admin_users ORDER BY username').fetchall()
            return jsonify({'primary_owner': PRIMARY_OWNER,
                'roles': [{'id': key, 'name': value[0], 'permissions': sorted(value[1])} for key, value in ROLES.items()],
                'users': [{'username': row['username'], 'role': effective_role(row['username'], row['role']),
                           'permissions': permissions(row['username'], row['role']), 'created_at': row['created_at'],
                           'enabled': row['role'] != 'disabled', 'protected': row['username'] == PRIMARY_OWNER} for row in rows]})
        finally: database.close()

    @app.post('/api/admin/users')
    def team_create():
        error = require_admin() or require_csrf()
        if error: return error
        body = request.get_json(silent=True) or {}
        username = str(body.get('username') or 'staff_' + secrets.token_hex(4)).strip()
        role = str(body.get('role') or '')
        if not re.fullmatch(r'[A-Za-z0-9._-]{3,40}', username) or username.casefold() == PRIMARY_OWNER.casefold():
            return jsonify({'error': 'Choose a valid, non-reserved username (3–40 characters).'}), 400
        if role not in ROLES: return jsonify({'error': 'Select a staff role.'}), 400
        password = secrets.token_urlsafe(18)
        verifier = generate_password_hash(password)
        database = database_factory()
        try:
            p = '%s' if database._postgres else '?'
            transaction = database.conn.transaction() if database._postgres else database.conn
            with transaction:
                cursor = database.conn.execute(f'INSERT INTO admin_users(username,password_hash,role,created_at) VALUES ({p},{p},{p},{p}) ON CONFLICT(username) DO NOTHING',
                    (username, verifier, role, datetime.now(timezone.utc).isoformat()))
                if cursor.rowcount != 1: return jsonify({'error': 'That username already exists.'}), 409
                database.log_activity(session['admin_user'], 'staff_created', details=f'{username}: {role}')
            return jsonify({'ok': True, 'username': username, 'role': role, 'password': password,
                            'permissions': permissions(username, role), 'one_time_credentials': True}), 201
        finally: database.close()

    @app.post('/api/admin/users/<username>')
    def team_update(username):
        error = require_admin() or require_csrf()
        if error: return error
        if username.casefold() == PRIMARY_OWNER.casefold(): return jsonify({'error': 'The primary owner account is protected.'}), 403
        body = request.get_json(silent=True) or {}
        operation = body.get('operation')
        role = str(body.get('role') or '')
        if operation not in {'role', 'disable', 'reset_password'}: return jsonify({'error': 'Invalid staff action.'}), 400
        if operation == 'role' and role not in ROLES: return jsonify({'error': 'Select a staff role.'}), 400
        database = database_factory()
        try:
            p = '%s' if database._postgres else '?'
            password = secrets.token_urlsafe(18) if operation == 'reset_password' else None
            transaction = database.conn.transaction() if database._postgres else database.conn
            with transaction:
                if operation == 'reset_password':
                    cursor = database.conn.execute(f'UPDATE admin_users SET password_hash={p} WHERE username={p}', (generate_password_hash(password), username))
                else:
                    cursor = database.conn.execute(f'UPDATE admin_users SET role={p} WHERE username={p}', ('disabled' if operation == 'disable' else role, username))
                if cursor.rowcount != 1: return jsonify({'error': 'Staff account not found.'}), 404
                database.log_activity(session['admin_user'], 'staff_' + operation, details=f'{username}' + (f': {role}' if operation == 'role' else ''))
            result = {'ok': True, 'username': username}
            if password: result.update(password=password, one_time_credentials=True)
            return jsonify(result)
        finally: database.close()
