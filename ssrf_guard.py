"""Opt-in public media fetches with per-hop destination validation.

Direct connections pin the validated IP. Operator proxies retain their own
DNS/transport; local DNS preflight cannot pin the proxy's origin connection.
Internal callers outside public_scope retain their existing proxy/source policy.
"""
import ipaddress
import re
import socket
from copy import copy
from contextlib import contextmanager
from contextvars import ContextVar
from urllib.parse import urljoin, urlsplit, urlunsplit, parse_qs

_PUBLIC = ContextVar('public_media_fetch', default=False)
MAX_IMAGE_BYTES = 32 * 1024 * 1024


def current_image_proxies(plugin):
    """Registered stable site keys -> current enabled operator URL or None.

    Read settings per call, never site.config snapshots. This registry selects
    operator proxy transport; it does not pin proxy-side origin DNS.
    """
    pairs = {}
    if plugin is None:
        return pairs
    for name in ('jav_censored', 'jav_uncensored', 'western'):
        module = plugin.get_module(name)
        if module is None:
            continue
        if name == 'western':
            pairs[name] = ('western_use_proxy', 'western_proxy_url')
            continue
        for site in getattr(module, 'site_map', {}):
            prefix = f'{name}_{site}'
            pairs[prefix] = (f'{prefix}_use_proxy', f'{prefix}_proxy_url')
        if name == 'jav_uncensored' and 'fc2com' in getattr(module, 'site_map', {}):
            pairs['jav_uncensored_fc2com_javten'] = (
                'jav_uncensored_fc2com_use_javten_proxy',
                'jav_uncensored_fc2com_javten_proxy_url')
    current = {}
    for site, (enabled_key, url_key) in pairs.items():
        value = plugin.ModelSetting.get(url_key) if plugin.ModelSetting.get_bool(enabled_key) else None
        current[site] = value if isinstance(value, str) and value else None
    return current


def image_proxy_site(proxy_url, plugin):
    """Generation only: map an active configured URL to a stable site key.

    Shared URLs have no unique site identity; choose the lexically first key.
    No configured address or address-derived hash is emitted to clients.
    """
    if not proxy_url:
        return None
    return next((site for site, value in sorted(current_image_proxies(plugin).items())
                 if value == proxy_url), None)


class SSRFRejected(ValueError):
    def __init__(self):
        super().__init__('Remote media request denied')
        state = _PUBLIC.get()
        if isinstance(state, dict):
            state['rejected'] = True


@contextmanager
def public_scope():
    state = {'rejected': False}
    token = _PUBLIC.set(state)
    try:
        yield
    finally:
        _PUBLIC.reset(token)
        # Legacy image helpers catch broad exceptions. A rejection must still
        # reach the public route even if an inner helper swallowed it.
        if state['rejected']:
            raise SSRFRejected()


def is_public_scope():
    return bool(_PUBLIC.get())


def reject_proxy(proxy=None):
    if proxy and (not isinstance(proxy, dict) or any(proxy.values())):
        raise SSRFRejected()


def _public_ip(value):
    try:
        ip = ipaddress.ip_address(value)
        if (not ip.is_global or ip.is_multicast or ip.is_reserved or
                getattr(ip, 'ipv4_mapped', None) is not None or
                getattr(ip, 'sixtofour', None) is not None or
                getattr(ip, 'teredo', None) is not None):
            raise SSRFRejected()
        return ip
    except ValueError:
        raise SSRFRejected() from None


def destination(url):
    """Canonical authority only; preserve path/query escapes and plus signs."""
    try:
        if (not isinstance(url, str) or not 1 <= len(url) <= 16384 or
                any(ord(c) <= 32 or ord(c) == 127 for c in url) or '\\' in url):
            raise SSRFRejected()
        parts = urlsplit(url)
        if (parts.scheme not in ('http', 'https') or not parts.hostname or
                parts.username is not None or parts.password is not None or
                '%' in parts.netloc or parts.netloc.endswith(':')):
            raise SSRFRejected()
        host = parts.hostname
        port = parts.port if parts.port is not None else (443 if parts.scheme == 'https' else 80)
        if not 1 <= port <= 65535:
            raise SSRFRejected()
        try:
            literal = ipaddress.ip_address(host)
        except ValueError:
            literal = None
        if literal is not None:
            host = str(_public_ip(host))
            ips = [host]
        else:
            host = host.encode('idna').decode('ascii').lower()
            # Reject ambiguous numeric IPv4, empty labels, intranet names and
            # legacy inet_aton forms, before invoking any resolver.
            labels = host.split('.')
            if (len(host) > 253 or len(labels) < 2 or
                    any(not re.fullmatch(r'[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?', x) for x in labels) or
                    re.fullmatch(r'[0-9.]+', host) or
                    all(re.fullmatch(r'(?:0x[0-9a-f]+|[0-9]+)', x) for x in labels) or
                    labels[-1] in ('localhost', 'local', 'internal', 'home', 'lan')):
                raise SSRFRejected()
            answers = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
            ips = []
            for family, _, _, _, addr in answers:
                if family not in (socket.AF_INET, socket.AF_INET6):
                    raise SSRFRejected()
                ip = str(_public_ip(addr[0]))
                if ip not in ips:
                    ips.append(ip)
            if not ips:
                raise SSRFRejected()
        authority = '[' + host + ']' if ':' in host else host
        if parts.port is not None:
            authority += ':' + str(port)
        return urlunsplit((parts.scheme, authority, parts.path, parts.query, '')), host, port, ips[0]
    except (ValueError, UnicodeError, OSError):
        raise SSRFRejected() from None


def validate(url, proxy=None):
    reject_proxy(proxy)
    destination(url)


def unwrap_image_url(url):
    """Decode each recognized FF wrapper once, leaving source query bytes alone."""
    paths = {'/metadata/normal/jav_image', '/metadata/normal/jav_image_un',
             '/metadata/normal/image_proxy', '/metadata/api/image_proxy',
             '/metadata/normal/image_process.jpg'}
    seen = set()
    for _ in range(6):
        if not isinstance(url, str) or not url.startswith(('http://', 'https://')):
            return url
        parts = urlsplit(url)
        if parts.path not in paths:
            return url
        inner = (parse_qs(parts.query).get('url') or [None])[0]
        if not inner or url in seen:
            raise SSRFRejected()
        seen.add(url)
        url = inner
    raise SSRFRejected()


def _requests_session(ip):
    import requests
    from requests.adapters import HTTPAdapter
    from urllib3.connection import HTTPConnection, HTTPSConnection
    from urllib3.connectionpool import HTTPConnectionPool, HTTPSConnectionPool
    from urllib3.exceptions import NewConnectionError

    def new_conn(conn):
        # No hostname reaches the socket API. urllib3 retains the original host
        # for Host, TLS SNI and certificate matching. No global DNS monkeypatch.
        sock = None
        try:
            family = socket.AF_INET6 if ':' in ip else socket.AF_INET
            sock = socket.socket(family, socket.SOCK_STREAM)
            sock.settimeout(conn.timeout)
            for option in conn.socket_options or ():
                sock.setsockopt(*option)
            sock.connect((ip, conn.port))
            return sock
        except OSError as exc:
            if sock is not None:
                sock.close()
            raise NewConnectionError(conn, 'Media connection failed') from exc

    class PinnedHTTP(HTTPConnection):
        _new_conn = new_conn

    class PinnedHTTPS(HTTPSConnection):
        _new_conn = new_conn

    class HTTPPool(HTTPConnectionPool):
        ConnectionCls = PinnedHTTP

    class HTTPSPool(HTTPSConnectionPool):
        ConnectionCls = PinnedHTTPS

    class Adapter(HTTPAdapter):
        def init_poolmanager(self, *args, **kwargs):
            super().init_poolmanager(*args, **kwargs)
            self.poolmanager.pool_classes_by_scheme = {'http': HTTPPool, 'https': HTTPSPool}

    session = requests.Session()
    session.trust_env = False
    session.mount('http://', Adapter(max_retries=0))
    session.mount('https://', Adapter(max_retries=0))
    return session


def _own_response(response, session):
    close = response.close
    closed = False

    def finish():
        nonlocal closed
        if not closed:
            closed = True
            try:
                close()
            finally:
                session.close()
    response.close = finish
    return response


def _redirect_cookies(url, headers, *sources):
    """Request-local jar; explicit Cookie seeds only the initial origin.

    Response cookies are subsequently accepted/expired by the HTTP client's
    cookie engine. Never merge a response's name/value mapping into this jar:
    that loses Domain, Path, Secure and deletion semantics.
    """
    from http.cookiejar import CookieJar
    from http.cookies import SimpleCookie
    from requests.cookies import create_cookie

    jar = CookieJar()
    host = urlsplit(url).hostname

    def seed(name, value):
        cookie = create_cookie(name, value, domain=host, path='/')
        cookie.domain_specified = False
        jar.set_cookie(cookie)

    for source in sources:
        source = getattr(source, 'jar', source)
        if isinstance(source, CookieJar):
            for cookie in source:
                jar.set_cookie(copy(cookie))
        elif source:
            for name, value in dict(source).items():
                seed(name, value)
    raw = next((value for key, value in headers.items() if key.lower() == 'cookie'), None)
    if raw:
        parsed = SimpleCookie()
        parsed.load(raw)
        for name, morsel in parsed.items():
            seed(name, morsel.value)
    return jar


def _proxy_fetch(url, *, transport, client, proxy, headers, cookies, verify,
                 timeout, stream, impersonate):
    """Validate each GET while retaining operator HTTP/SOCKS transport.

    Borrow the caller's transport with request-local headers/cookies until an
    origin boundary, then use a clean session. Borrowed adapters/curl handles
    remain caller-owned; never close them or mutate the crawler's cookie jar.
    """
    if transport is None or client not in ('requests', 'curl_cffi'):
        raise SSRFRejected()
    effective_headers = dict(getattr(transport, 'headers', {}) or {})
    effective_headers.update(headers or {})
    headers = {k: v for k, v in effective_headers.items()
               if k.lower() not in ('host', 'proxy-authorization')}
    session = copy(transport)
    session.headers = transport.headers.copy()
    for key in list(session.headers):
        if key.lower() == 'cookie':
            del session.headers[key]
    owned = False
    seen = set()
    previous_origin = None
    cookie_jar = None
    try:
        for hop in range(6):
            current, host, port, _ = destination(url)
            if current in seen:
                raise SSRFRejected()
            seen.add(current)
            origin = (urlsplit(current).scheme, host, port)
            if previous_origin is None:
                cookie_jar = _redirect_cookies(current, headers, transport.cookies, cookies)
            if previous_origin is not None and origin != previous_origin:
                headers = {k: v for k, v in headers.items()
                           if k.lower() not in ('authorization', 'cookie')}
                cookie_jar = _redirect_cookies(current, {})
                if owned:
                    session.close()
                    owned = False
                if client == 'requests':
                    import requests
                    session = requests.Session()
                else:
                    from curl_cffi import requests as curl_requests
                    session = curl_requests.Session(
                        impersonate=getattr(transport, 'impersonate', impersonate))
                owned = True
                session.trust_env = False
                # Preserve the original TLS policy if the caller did not override it.
                session.verify = getattr(transport, 'verify', True)
            previous_origin = origin
            session.cookies = cookie_jar
            options = dict(headers=headers, proxies=proxy,
                           timeout=timeout, allow_redirects=False)
            if verify is not None:
                options['verify'] = verify
            if client == 'requests':
                options['stream'] = True
            else:
                # Signed path/query escapes must not be re-quoted by curl_cffi.
                options['quote'] = False
            response = None
            try:
                response = session.get(current, **options)
                if response.status_code in (301, 302, 303, 307, 308):
                    location = response.headers.get('Location')
                    if (not isinstance(location, str) or not location or hop == 5 or
                            any(ord(c) <= 32 or ord(c) == 127 for c in location) or
                            '\\' in location):
                        raise SSRFRejected()
                    try:
                        url = urljoin(current, location)
                    except ValueError:
                        raise SSRFRejected() from None
                    # Let the jar build the next Cookie header, including any
                    # newly accepted response cookies and deletions.
                    headers = {k: v for k, v in headers.items() if k.lower() != 'cookie'}
                    continue
                if stream:
                    result = _own_response(response, session) if owned else response
                    response = None
                    owned = False
                    return result
                if client == 'requests':
                    body = bytearray()
                    for chunk in response.iter_content(65536):
                        if len(body) + len(chunk) > MAX_IMAGE_BYTES:
                            raise SSRFRejected()
                        body.extend(chunk)
                    response._content = bytes(body)
                    response._content_consumed = True
                elif len(response.content) > MAX_IMAGE_BYTES:
                    raise SSRFRejected()
                return response
            finally:
                if response is not None:
                    response.close()
    finally:
        if owned:
            session.close()
    raise SSRFRejected()


def fetch(url, *, client='requests', proxy=None, headers=None, cookies=None,
          verify=None, timeout=(10, 30), stream=False, impersonate=None, transport=None):
    """GET with validated redirects; pin direct IPs, preflight operator proxies."""
    if proxy and (not isinstance(proxy, dict) or any(proxy.values())):
        return _proxy_fetch(url, transport=transport, client=client, proxy=proxy,
                            headers=headers, cookies=cookies, verify=verify,
                            timeout=timeout, stream=stream, impersonate=impersonate)
    headers = dict(headers or {})
    # Caller headers may carry site credentials but cannot override authority.
    headers = {k: v for k, v in headers.items() if k.lower() not in ('host', 'proxy-authorization')}
    seen = set()
    previous_origin = None
    cookie_jar = None
    for hop in range(6):
        current, host, port, ip = destination(url)
        if current in seen:
            raise SSRFRejected()
        seen.add(current)
        origin = (urlsplit(current).scheme, host, port)
        if previous_origin is None:
            cookie_jar = _redirect_cookies(current, headers, cookies)
        if previous_origin is not None and origin != previous_origin:
            headers = {k: v for k, v in headers.items() if k.lower() not in ('authorization', 'cookie')}
            cookie_jar = _redirect_cookies(current, {})
        previous_origin = origin
        session = None
        response = None
        try:
            if client == 'requests':
                session = _requests_session(ip)
                session.cookies = cookie_jar
                response = session.get(current, headers=headers,
                                       verify=True if verify is None else verify,
                                       timeout=timeout, stream=True, allow_redirects=False,
                                       proxies={})
            elif client == 'curl_cffi' and not stream:
                from curl_cffi import CurlOpt
                from curl_cffi import requests as curl_requests
                address = '[' + ip + ']' if ':' in ip else ip
                options = {CurlOpt.PROXY: '', CurlOpt.FOLLOWLOCATION: 0,
                           CurlOpt.FRESH_CONNECT: 1, CurlOpt.FORBID_REUSE: 1}
                # Numeric URL authorities already dial the literal IP. IPv6
                # literals must not be formatted as a RESOLVE hostname.
                if host != ip:
                    options[CurlOpt.RESOLVE] = [f'{host}:{port}:{address}']
                session = curl_requests.Session(trust_env=False, curl_options=options,
                                                impersonate=impersonate)
                session.cookies = cookie_jar
                body = bytearray()

                def receive(chunk):
                    if len(body) + len(chunk) > MAX_IMAGE_BYTES:
                        raise SSRFRejected()
                    body.extend(chunk)
                    return len(chunk)

                response = session.get(current, headers=headers,
                                       verify=True if verify is None else verify,
                                       timeout=timeout, allow_redirects=False,
                                       content_callback=receive, quote=False)
                response.content = bytes(body)
            else:
                raise SSRFRejected()
            if response.status_code in (301, 302, 303, 307, 308):
                location = response.headers.get('Location')
                if not location or hop == 5:
                    raise SSRFRejected()
                # Validate raw Location before urljoin can discard control bytes.
                if any(ord(c) <= 32 or ord(c) == 127 for c in location) or '\\' in location:
                    raise SSRFRejected()
                url = urljoin(current, location)
                headers = {k: v for k, v in headers.items() if k.lower() != 'cookie'}
                continue
            if stream:
                result = _own_response(response, session)
                response = session = None
                return result
            if client == 'requests':
                body = bytearray()
                for chunk in response.iter_content(65536):
                    if len(body) + len(chunk) > MAX_IMAGE_BYTES:
                        raise SSRFRejected()
                    body.extend(chunk)
                response._content = bytes(body)
                response._content_consumed = True
            return response
        finally:
            try:
                if response is not None:
                    response.close()
            finally:
                if session is not None:
                    session.close()
    raise SSRFRejected()
