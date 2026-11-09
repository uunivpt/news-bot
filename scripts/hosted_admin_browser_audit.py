"""Verify hosted Admin Room sessions and private diagnostics using local fixtures.

No production credentials, phone gateway, cloud database or external service is
used. Run: python scripts/hosted_admin_browser_audit.py --output artifacts/hosted-admin
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
import time
from unittest.mock import patch
from urllib.parse import urlsplit

from playwright.sync_api import sync_playwright

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from api import index as api
from scripts.browser_audit import fixture_server


def run(base: str, output: Path) -> None:
    output.mkdir(parents=True, exist_ok=True)
    checks, errors = [], []
    environment = {
        'POLITICSHUB_ADMIN_BACKEND': 'hosted',
        'POLITICSHUB_ADMIN_BRIDGE_URL': 'https://retired-phone.fixture.ts.net',
        'POLITICSHUB_ADMIN_BRIDGE_SECRET': 'obsolete-fixture-bridge-secret-1234567890',
        'POLITICSHUB_LOCAL_ADMIN': '', 'POLITICSHUB_GITHUB_FEED_ONLY': '1',
    }
    with patch.dict(os.environ, environment), fixture_server(base), \
         patch.dict(os.environ, {'VERCEL': '1'}), \
         patch('app.remote_admin_bridge.build_opener', side_effect=AssertionError('Hosted fixture must never open the phone gateway')) as bridge, \
         sync_playwright() as playwright:
        fixture_connect = api.db.side_effect

        def connect_local_fixture():
            # Hosted routing runs with VERCEL=1. Only the temporary fixture's
            # connector runs as local SQLite; production keeps its cloud-URL
            # requirement and never receives this test-only substitution.
            with patch.dict(os.environ, {'VERCEL': ''}):
                return fixture_connect()

        api.db.side_effect = connect_local_fixture
        api._ADMIN_LOGIN_RATE.clear()
        api._PUBLIC_RATE.clear()
        browser = playwright.chromium.launch(headless=True, args=['--no-sandbox'])
        context = browser.new_context(viewport={'width': 1440, 'height': 1000}, reduced_motion='reduce', service_workers='block')
        context.route('**/*', lambda route: route.continue_() if route.request.url.startswith(base + '/') else route.abort())
        page = context.new_page()
        page.on('pageerror', lambda error: errors.append(str(error)))

        def require(condition, message):
            if not condition:
                raise AssertionError(message)

        def check(name, callback):
            started = time.monotonic()
            try:
                callback()
            except Exception as error:
                page.screenshot(path=str(output / 'failure.png'), animations='disabled')
                (output / 'failure.json').write_text(json.dumps({'check': name, 'error': str(error), 'browser_errors': errors}, indent=2))
                raise
            checks.append({'check': name, 'status': 'passed', 'seconds': round(time.monotonic() - started, 2)})
            print('PASS ' + name, flush=True)

        def anonymous():
            identity = context.request.get(base + '/api/admin/me')
            require(identity.status == 200 and identity.json()['authenticated'] is False, 'Anonymous session check failed before sign-in')
            require('no-store' in identity.headers.get('cache-control', ''), 'Identity response can enter a shared cache')
            workspace = context.request.get(base + '/api/admin/workspace')
            require(workspace.status == 401, 'Anonymous visitor can read the private workspace')
            page.goto(base + '/admin/', wait_until='networkidle')
            page.wait_for_selector('#loginForm')
            require(not page.locator('#loginErr').inner_text().strip(), 'Normal unsigned session displays an error')
            visible_copy = page.locator('.login-help').inner_text()
            require('phone' not in visible_copy.lower() and 'termux' not in visible_copy.lower(), 'Sign-in still requires a phone workflow')
            page.screenshot(path=str(output / 'hosted-login-desktop.png'), animations='disabled')
        check('anonymous identity and sign-in work with obsolete phone bridge settings', anonymous)

        def login():
            page.locator('#username').fill('audit_owner')
            page.locator('#password').fill('wrong-hosted-fixture-password')
            page.locator('#loginForm [type="submit"]').click()
            page.wait_for_function("() => document.querySelector('#loginErr').textContent.toLowerCase().includes('invalid')")
            require(page.locator('#shell').is_hidden(), 'Wrong credentials exposed the workspace')
            page.locator('#password').fill('temporary-fixture-password')
            page.locator('#loginForm [type="submit"]').click()
            page.wait_for_selector('#overviewMetrics .metric')
            page.wait_for_function("() => document.querySelector('#connectionBadge').textContent === 'Live workspace'")
            require(page.locator('#overviewMetrics .metric').count() == 4, 'Hosted overview failed to load real metrics')
            identity = context.request.get(base + '/api/admin/me').json()
            require(identity['authenticated'] and identity['scope'] == 'owner' and not identity['read_only'], 'Hosted login fell back to a recovery session')
            response = context.request.get(base + '/api/admin/workspace')
            data = response.json()
            require(data['data_origin'] == 'hosted_database', 'Workspace reports the wrong data origin')
            require(data['health']['database'] == 'connected' and data['capabilities']['publish'], 'Hosted workspace is not writable')
            require('private' in response.headers.get('cache-control', '') and 'no-store' in response.headers.get('cache-control', ''), 'Authenticated workspace can enter shared cache')
            copy = page.locator('#heroDescription').inner_text() + page.locator('#workspaceBanner').inner_text()
            require('phone' not in copy.lower() and 'termux' not in copy.lower(), 'Hosted workspace shows obsolete phone instructions')
            page.screenshot(path=str(output / 'hosted-overview-desktop.png'), animations='disabled')
        check('real hosted owner login rejects a wrong password and opens a writable workspace', login)

        def persistence():
            page.reload(wait_until='networkidle')
            page.wait_for_selector('#overviewMetrics .metric')
            require(page.locator('#login').is_hidden(), 'Reload lost the hosted session')
            denied = context.request.post(base + '/api/admin/logout', data={})
            require(denied.status == 403, 'Session mutation bypasses CSRF')
            require(context.request.get(base + '/api/admin/me').json()['authenticated'], 'Rejected logout cleared a valid session')
        check('session survives reload and rejects a logout without CSRF', persistence)

        def private_diagnostics():
            if page.locator('#menuToggle').is_visible():
                page.locator('#menuToggle').click()
            page.locator('.nav [data-view="system"]').click()
            page.wait_for_selector('#system.active')
            require(page.locator('#systemChecks').inner_text().strip(), 'Authenticated system checks are missing')
            page.screenshot(path=str(output / 'hosted-private-system.png'), animations='disabled')
        check('operational diagnostics remain accessible inside the signed-in Admin Room', private_diagnostics)

        def responsive():
            for width in (320, 390, 768, 1440):
                page.set_viewport_size({'width': width, 'height': 900})
                require(page.evaluate('document.documentElement.scrollWidth <= innerWidth'), f'Admin Room overflows at {width}px')
                if width == 390:
                    page.screenshot(path=str(output / 'hosted-admin-mobile.png'), animations='disabled')
            page.set_viewport_size({'width': 1440, 'height': 1000})
        check('hosted workspace fits phones, tablets and desktop screens', responsive)

        def logout():
            page.locator('#logout').click()
            page.wait_for_selector('#loginForm:visible')
            require(context.request.get(base + '/api/admin/me').json()['authenticated'] is False, 'Sign out kept the hosted session')
            require(context.request.get(base + '/api/admin/workspace').status == 401, 'Signed-out browser can still read the private workspace')
            require(page.locator('#overviewMetrics .metric').count() == 0, 'Sign out left private metrics in the DOM')
        check('sign out clears the session and private workspace content', logout)

        def public_pages():
            for path in ('/', '/settings.html', '/#/settings/status'):
                page.goto(base + path, wait_until='networkidle')
                require(page.get_by_role('link', name='System Status', exact=False).count() == 0, path + ' exposes a public operational-status link')
                require(page.get_by_role('heading', name='System status', exact=False).count() == 0, path + ' exposes operational diagnostics')
            health = context.request.get(base + '/api/health')
            require(health.status == 200 and set(health.json()) == {'ok'}, 'Public health endpoint reveals operational details')
            page.goto(base + '/debug.html', wait_until='domcontentloaded')
            page.wait_for_url(base + '/admin/')
            page.wait_for_selector('#loginForm:visible')
            status = context.request.get(base + '/status', max_redirects=0)
            require(status.status in (301, 302, 303, 307, 308) and status.headers.get('location', '').startswith('/admin/'), 'Legacy status route does not enter the private workspace')
        check('public pages hide system status and legacy diagnostics enter private sign-in', public_pages)

        bridge.assert_not_called()
        require(not errors, 'Browser errors: ' + '; '.join(errors))
        context.close()
        browser.close()
    (output / 'report.json').write_text(json.dumps({
        'base_url': base, 'checks': checks, 'browser_errors': errors,
        'scope': 'Temporary SQLite and synthetic owner credentials. Hosted mode with stale phone settings; phone transport forbidden and external browser requests blocked.'
    }, indent=2))
    print(f'{len(checks)} hosted Admin Room browser checks passed; report: {output / "report.json"}', flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base-url', default='http://127.0.0.1:8048')
    parser.add_argument('--output', type=Path, default=Path('artifacts/hosted-admin'))
    args = parser.parse_args()
    if urlsplit(args.base_url).hostname not in {'127.0.0.1', 'localhost'}:
        raise SystemExit('Run this audit only against its isolated local fixture server.')
    run(args.base_url.rstrip('/'), args.output)
