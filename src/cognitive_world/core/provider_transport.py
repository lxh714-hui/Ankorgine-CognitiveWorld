"""Narrow HTTPS/loopback transport boundary for OpenAI-compatible adapters."""

from __future__ import annotations

from dataclasses import dataclass
import http.client
import ipaddress
import socket
from urllib.error import HTTPError, URLError
from urllib.parse import unquote, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener


class ProviderEndpointError(ValueError):
    """The configured provider endpoint violates the transport contract."""


class ProviderRedirectError(URLError):
    """Provider redirects are rejected instead of followed."""


@dataclass(frozen=True)
class ProviderEndpoint:
    scheme: str
    hostname: str
    port: int
    authority: str
    path: str
    connect_host: str | None

    def request_url(self, route: str) -> str:
        suffix = route if route.startswith("/") else f"/{route}"
        path = self.path.rstrip("/")
        if not path.endswith(suffix):
            path += suffix
        return f"{self.scheme}://{self.authority}{path}"


def validate_provider_endpoint(base_url: str) -> ProviderEndpoint:
    """Allow HTTP only for an IP-literal loopback or verified localhost.

    Arbitrary hostnames are treated as remote and therefore require HTTPS.
    Localhost HTTP resolution is checked here and repeated at request time;
    the resulting connection uses the checked numeric address to avoid a
    second hostname lookup between validation and connect.
    """
    if not isinstance(base_url, str) or not base_url or any(ch.isspace() for ch in base_url):
        raise ProviderEndpointError("provider URL must be non-empty and contain no whitespace")
    if "\\" in base_url or any(ord(ch) < 0x20 for ch in base_url):
        raise ProviderEndpointError("provider URL contains an invalid character")
    try:
        parsed = urlsplit(base_url)
        hostname = parsed.hostname
        port = parsed.port
    except ValueError as exc:
        raise ProviderEndpointError("provider URL is malformed") from exc
    scheme = parsed.scheme.casefold()
    if (scheme not in {"http", "https"} or not parsed.netloc or not hostname
            or parsed.username is not None or parsed.password is not None
            or parsed.query or parsed.fragment):
        raise ProviderEndpointError("provider URL must be an HTTP(S) URL without credentials, query, or fragment")
    if "%" in hostname:
        raise ProviderEndpointError("scoped or escaped provider hostnames are not accepted")
    decoded_path = unquote(parsed.path)
    if "\\" in decoded_path or any(part == ".." for part in decoded_path.split("/")):
        raise ProviderEndpointError("provider URL path is invalid")
    if port is None:
        port = 443 if scheme == "https" else 80
    if not 1 <= port <= 65535:
        raise ProviderEndpointError("provider port is invalid")

    canonical_host = hostname.casefold().rstrip(".")
    connect_host: str | None = None
    is_loopback = False
    try:
        address = ipaddress.ip_address(hostname)
    except ValueError:
        address = None
    if address is not None:
        is_loopback = address.is_loopback
        if is_loopback:
            connect_host = str(address)
    elif scheme == "http" and canonical_host == "localhost":
        try:
            results = socket.getaddrinfo(hostname, port, type=socket.SOCK_STREAM)
        except OSError as exc:
            raise ProviderEndpointError("localhost provider address could not be resolved") from exc
        addresses: list[tuple[int, str]] = []
        for family, _socktype, _proto, _canonname, sockaddr in results:
            try:
                resolved = ipaddress.ip_address(sockaddr[0])
            except (ValueError, IndexError, TypeError) as exc:
                raise ProviderEndpointError("localhost resolved to an invalid address") from exc
            if not resolved.is_loopback:
                raise ProviderEndpointError("localhost resolved outside loopback")
            addresses.append((family, str(resolved)))
        if not addresses:
            raise ProviderEndpointError("localhost resolved to no addresses")
        is_loopback = True
        connect_host = addresses[0][1]

    if scheme == "http" and not is_loopback:
        raise ProviderEndpointError("plain HTTP is permitted only for a loopback provider")

    if ":" in hostname:
        host_for_authority = f"[{hostname}]"
    else:
        host_for_authority = hostname
    explicit_port = parsed.port is not None
    authority = f"{host_for_authority}:{port}" if explicit_port else host_for_authority
    return ProviderEndpoint(
        scheme=scheme,
        hostname=hostname,
        port=port,
        authority=authority,
        path=parsed.path.rstrip("/"),
        connect_host=connect_host if scheme == "http" else None,
    )


class _RejectRedirectHandler(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def post_provider_json(
    base_url: str,
    route: str,
    body: bytes,
    *,
    headers: dict[str, str],
    timeout_seconds: float,
    maximum_bytes: int,
) -> bytes:
    """POST bounded JSON without redirects or HTTP downgrade paths."""
    if isinstance(maximum_bytes, bool) or not isinstance(maximum_bytes, int) or maximum_bytes < 1:
        raise ValueError("provider response bound must be a positive integer")
    endpoint = validate_provider_endpoint(base_url)
    target = endpoint.request_url(route)
    if endpoint.scheme == "http":
        if any(name.casefold() in {"authorization", "proxy-authorization"} for name in headers):
            raise ProviderEndpointError("authorization credentials may not be sent over HTTP")
        # HTTP is restricted to a checked loopback address and connects to
        # that numeric address, not a hostname that could resolve differently.
        connection = http.client.HTTPConnection(
            endpoint.connect_host, endpoint.port, timeout=timeout_seconds,
        )
        request_headers = dict(headers)
        request_headers["Host"] = endpoint.authority
        try:
            parsed_target = urlsplit(target)
            connection.request("POST", parsed_target.path, body=body, headers=request_headers)
            response = connection.getresponse()
            if 300 <= response.status < 400:
                raise ProviderRedirectError("provider redirects are not accepted")
            if response.status < 200 or response.status >= 300:
                raise URLError(f"provider returned HTTP {response.status}")
            payload = response.read(maximum_bytes + 1)
            if len(payload) > maximum_bytes:
                raise ValueError("provider transport response exceeds size bound")
            return payload
        finally:
            connection.close()

    request = Request(target, data=body, headers=dict(headers), method="POST")
    opener = build_opener(_RejectRedirectHandler())
    try:
        with opener.open(request, timeout=timeout_seconds) as response:
            payload = response.read(maximum_bytes + 1)
    except HTTPError as exc:
        if 300 <= exc.code < 400:
            raise ProviderRedirectError("provider redirects are not accepted") from None
        raise URLError(f"provider returned HTTP {exc.code}") from None
    if len(payload) > maximum_bytes:
        raise ValueError("provider transport response exceeds size bound")
    return payload
