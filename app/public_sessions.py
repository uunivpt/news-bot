"""Keep anonymous, invariant public responses eligible for the CDN cache."""
from flask.sessions import SecureCookieSessionInterface


class PublicSessionInterface(SecureCookieSessionInterface):
    def save_session(self, app, session, response):
        super().save_session(app, session, response)
        # Flask adds Vary: Cookie even when code merely reads an empty session.
        # Vercel intentionally never caches that high-cardinality variation.
        # Only anonymous, unchanged sessions with explicitly public responses
        # are invariant. Authenticated or changed sessions keep normal behavior.
        if (not session and not session.modified and response.cache_control.public
                and not response.cache_control.private and not response.cache_control.no_store
                and 'Set-Cookie' not in response.headers):
            response.vary.discard('Cookie')
            if not response.vary:
                response.headers.pop('Vary',None)
