"""Browser boundaries for the local application and authenticated proxies."""
from urllib.parse import urlsplit

from fastapi.responses import JSONResponse


CONTENT_POLICY = chr(59).join((
    "default-src 'self'", "script-src 'self'", "style-src 'self' 'unsafe-inline'",
    "img-src 'self' data: blob:", "connect-src 'self'", "object-src 'none'",
    "base-uri 'none'", "frame-ancestors 'none'", "form-action 'self'",
))


def public_origin(value):
    """Require one unambiguous browser origin before opening application data."""
    if not isinstance(value, str) or any(ord(character) <= 32 for character in value):
        raise ValueError('PUBLIC_URL must be an HTTP or HTTPS origin')
    try:
        parsed = urlsplit(value)
        port = parsed.port
        if (parsed.scheme not in {'http', 'https'} or not parsed.hostname
                or parsed.username is not None or parsed.password is not None
                or parsed.path not in {'', '/'} or parsed.query or parsed.fragment
                or any(character in value for character in '\\?#')
                or port == 0):
            raise ValueError
    except ValueError as error:
        raise ValueError('PUBLIC_URL must be an HTTP or HTTPS origin without credentials or a path') from error
    return f'{parsed.scheme}://{parsed.netloc}'


def protect_response(response):
    response.headers['Content-Security-Policy'] = CONTENT_POLICY
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['Referrer-Policy'] = 'no-referrer'
    response.headers['X-Frame-Options'] = 'DENY'
    response.headers['Cross-Origin-Resource-Policy'] = 'same-origin'
    response.headers['Permissions-Policy'] = 'camera=(), microphone=(), geolocation=()'
    return response


def install_browser_boundary(app, origin):
    origin = public_origin(origin)
    host = urlsplit(origin).netloc

    @app.middleware('http')
    async def browser_boundary(request, call_next):
        if (request.headers.get('host') != host
                or request.headers.get('origin', origin) != origin
                or request.headers.get('sec-fetch-site') == 'cross-site'):
            response = JSONResponse({'detail': 'Use the configured PokeSim address'}, status_code=403)
        else:
            response = await call_next(request)
        response.headers['Cache-Control'] = 'no-store'
        return protect_response(response)
