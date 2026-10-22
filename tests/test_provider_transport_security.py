from __future__ import annotations

import json
from urllib.error import HTTPError

import pytest

from cognitive_world.core import provider_transport as transport
from cognitive_world.decision.autonomous import OpenAICompatibleDecisionProvider, SituationAssessment
from cognitive_world.resolution.providers import OpenAICompatibleCausalProvider


def test_endpoint_policy_accepts_loopback_http_and_remote_https(monkeypatch):
    monkeypatch.setattr(
        transport.socket,
        "getaddrinfo",
        lambda *_args, **_kwargs: [
            (transport.socket.AF_INET, transport.socket.SOCK_STREAM, 6, "", ("127.0.0.1", 0)),
            (transport.socket.AF_INET6, transport.socket.SOCK_STREAM, 6, "", ("::1", 0, 0, 0)),
        ],
    )

    assert transport.validate_provider_endpoint("http://127.0.0.1:8080/v1").connect_host == "127.0.0.1"
    assert transport.validate_provider_endpoint("http://[::1]:8080/v1").connect_host == "::1"
    assert transport.validate_provider_endpoint("http://localhost:8080/v1").connect_host == "127.0.0.1"
    remote = transport.validate_provider_endpoint("https://api.example.test/v1")
    assert remote.scheme == "https"
    assert remote.request_url("/chat/completions") == "https://api.example.test/v1/chat/completions"


@pytest.mark.parametrize("url", [
    "http://203.0.113.7/v1",
    "http://localhost.example.test/v1",
    "http://127.0.0.1.example.test/v1",
    "http://user@127.0.0.1/v1",
    "http://127.0.0.1:99999/v1",
    "ftp://127.0.0.1/v1",
    "http://127.0.0.1/v1?redirect=https://example.test",
    "http://127.0.0.1/v1#fragment",
    "http://127.0.0.1/a/%2e%2e/b",
])
def test_endpoint_policy_rejects_remote_http_and_malformed_urls(url):
    with pytest.raises(transport.ProviderEndpointError):
        transport.validate_provider_endpoint(url)


def test_localhost_http_rejects_any_non_loopback_resolution(monkeypatch):
    monkeypatch.setattr(
        transport.socket,
        "getaddrinfo",
        lambda *_args, **_kwargs: [
            (transport.socket.AF_INET, transport.socket.SOCK_STREAM, 6, "", ("127.0.0.1", 0)),
            (transport.socket.AF_INET, transport.socket.SOCK_STREAM, 6, "", ("192.0.2.5", 0)),
        ],
    )
    with pytest.raises(transport.ProviderEndpointError, match="outside loopback"):
        transport.validate_provider_endpoint("http://localhost:8000/v1")


def test_loopback_http_uses_pinned_address_and_rejects_redirect(monkeypatch):
    calls = []

    class Response:
        status = 302

    class Connection:
        def __init__(self, host, port, *, timeout):
            calls.append(("connect", host, port, timeout))

        def request(self, method, path, *, body, headers):
            calls.append(("request", method, path, headers.get("Host")))

        def getresponse(self):
            return Response()

        def close(self):
            calls.append(("close",))

    monkeypatch.setattr(transport.http.client, "HTTPConnection", Connection)
    with pytest.raises(transport.ProviderRedirectError):
        transport.post_provider_json(
            "http://127.0.0.1:9000/v1", "/chat/completions", b"{}",
            headers={"Content-Type": "application/json"},
            timeout_seconds=1, maximum_bytes=1024,
        )
    assert calls == [
        ("connect", "127.0.0.1", 9000, 1),
        ("request", "POST", "/v1/chat/completions", "127.0.0.1:9000"),
        ("close",),
    ]


@pytest.mark.parametrize("header_name", ["Authorization", "authorization", "Proxy-Authorization"])
def test_authorization_header_is_rejected_before_any_http_connection(monkeypatch, header_name):
    calls = []
    monkeypatch.setattr(
        transport.http.client,
        "HTTPConnection",
        lambda *_args, **_kwargs: calls.append("connected"),
    )
    with pytest.raises(transport.ProviderEndpointError, match="credentials"):
        transport.post_provider_json(
            "http://127.0.0.1:9000/v1", "/chat/completions", b"{}",
            headers={header_name: "Bearer test-only"},
            timeout_seconds=1, maximum_bytes=1024,
        )
    assert calls == []


@pytest.mark.parametrize("provider_factory", [
    lambda: OpenAICompatibleDecisionProvider("http://203.0.113.9/v1", "model", "test-key"),
    lambda: OpenAICompatibleCausalProvider("http://203.0.113.9/v1", "model", "test-key"),
])
def test_remote_http_provider_is_rejected_at_construction(provider_factory):
    with pytest.raises(transport.ProviderEndpointError):
        provider_factory()


def test_decision_provider_sends_bounded_owner_view_only_to_injected_https_endpoint(monkeypatch):
    seen = {}

    def fake_post(base_url, route, body, *, headers, timeout_seconds, maximum_bytes):
        seen.update(url=transport.validate_provider_endpoint(base_url).request_url(route),
                    headers=headers, timeout=timeout_seconds, maximum=maximum_bytes)
        seen["body"] = json.loads(body.decode("utf-8"))
        return json.dumps({"choices": [{"message": {"content": '{"candidates": []}'}}]}).encode("utf-8")

    monkeypatch.setattr(transport, "post_provider_json", fake_post)
    # The adapter imports the helper directly, so patch its binding too.
    monkeypatch.setattr("cognitive_world.decision.autonomous.post_provider_json", fake_post)
    provider = OpenAICompatibleDecisionProvider("https://api.example.test/v1", "model", "test-key")
    situation = SituationAssessment(
        owner_id="agent-a", observed_facts=(), working_memory=(), memories=(), beliefs=(),
        capabilities=(), limitations=(), personality_preferences=(), personality_values=(),
        personality_traits=(), goals=(), emotion_levels=(), motivation_scores=(), goal_conflicts=(),
        attention_bias=(), risk_bias=0.0, impulse_bias=0.0, impulse_ceiling=0.0, review_bias=0.0,
        metacognitive_cues=(), metacognitive_queries=(), uncertainties=(),
    )
    assert provider.generate_candidates(situation, max_candidates=2, max_output_chars=100) == '{"candidates": []}'
    assert seen["url"] == "https://api.example.test/v1/chat/completions"
    assert seen["headers"]["Authorization"] == "Bearer test-key"
    sent = seen["body"]["messages"][0]["content"]
    assert "Situation:" in sent
    assert '"working_memory": []' in sent
    assert seen["timeout"] == 8.0


def test_https_redirect_is_rejected_without_following_or_downgrade(monkeypatch):
    calls = []

    class Opener:
        def open(self, request, *, timeout):
            calls.append((request.full_url, timeout))
            raise HTTPError(
                request.full_url, 302, "redirect", {"Location": "http://203.0.113.9/steal"}, None,
            )

    monkeypatch.setattr(transport, "build_opener", lambda *_handlers: Opener())
    with pytest.raises(transport.ProviderRedirectError):
        transport.post_provider_json(
            "https://api.example.test/v1", "/chat/completions", b"{}",
            headers={"Authorization": "Bearer test-only"},
            timeout_seconds=1, maximum_bytes=1024,
        )
    assert calls == [("https://api.example.test/v1/chat/completions", 1)]
    assert transport._RejectRedirectHandler().redirect_request(
        None, None, 302, "redirect", {"Location": "http://example.test"}, "http://example.test",
    ) is None


def test_http_provider_key_is_never_sent_even_to_loopback(monkeypatch):
    monkeypatch.setattr(transport.http.client, "HTTPConnection", lambda *_args, **_kwargs: pytest.fail("HTTP attempted"))
    provider = OpenAICompatibleCausalProvider("http://127.0.0.1:9000/v1", "model", "test-key")
    with pytest.raises(transport.ProviderEndpointError, match="credentials"):
        provider.complete_structured("instruction", {"brief": "bounded"}, max_output_chars=128)
