"""Offline protocol, authorization, and lifecycle checks for local embeddings."""

import json
from concurrent.futures import ThreadPoolExecutor
from threading import Event, get_ident

import pytest

from cognitive_world.agent import Character, CognitionContext
from cognitive_world.cognition import CognitionContainer, Memory, MemoryQuery, MemoryStore
from cognitive_world.cognition.memory_semantic_retrieval import HybridMemoryRetriever
from cognitive_world.cognition.ollama_embedding import OllamaEmbeddingProvider
from cognitive_world.runtime.write_fence import RuntimeWriteFence


def _provider(**kwargs):
    return OllamaEmbeddingProvider("http://127.0.0.1:11434", "local-test-model", **kwargs)


def _response(model, vectors):
    return json.dumps({"model": model, "embeddings": vectors}).encode("utf-8")


def _context():
    store = MemoryStore()
    memories = (
        Memory("lexical", "owner", "experience", "sentry saw lantern", 0.5, "event-1"),
        Memory("semantic", "owner", "experience", "watchman at north gate", 0.5, "event-2"),
        Memory("unlinked", "owner", "experience", "private watchman", 0.5, "event-3"),
        Memory("other", "other-owner", "experience", "private watchman", 0.5, "event-4"),
    )
    for memory in memories:
        store._commit_memory(memory)
    character = Character("character", "owner", "personality", memory_ids=["lexical", "semantic"])
    return CognitionContext.from_character(character, CognitionContainer(), store), store


def test_ollama_embed_uses_bounded_native_batch_protocol_without_internal_metadata(monkeypatch):
    calls = []

    def post(base_url, route, body, **options):
        calls.append((base_url, route, json.loads(body), options))
        return _response("local-test-model", [[1.0, 0.0], [0.0, 1.0]])

    monkeypatch.setattr("cognitive_world.cognition.ollama_embedding.post_provider_json", post)
    provider = _provider(dimensions=2, batch_size=2)
    assert provider.embed_many(("one", "two")) == ((1.0, 0.0), (0.0, 1.0))
    assert len(calls) == 1
    assert calls[0][0:2] == ("http://127.0.0.1:11434", "/api/embed")
    assert calls[0][2] == {
        "model": "local-test-model", "input": ["one", "two"],
        "truncate": False, "dimensions": 2,
    }
    assert calls[0][3]["timeout_seconds"] == 8.0
    assert set(calls[0][3]["headers"]) == {"Content-Type", "Accept"}


@pytest.mark.parametrize("url", [
    "https://example.com", "http://example.com:11434", "http://127.0.0.1:11434/v1",
])
def test_embedding_adapter_rejects_remote_or_wrong_route(url):
    with pytest.raises(ValueError):
        OllamaEmbeddingProvider(url, "model")


@pytest.mark.parametrize("payload", [
    _response("local-test-model", [[]]),
    _response("local-test-model", [[float("nan")]]),
    _response("local-test-model", [[1.0, 0.0, 0.0]]),
    _response("other-model", [[1.0, 0.0]]),
    b"not-json",
])
def test_invalid_response_rejected(monkeypatch, payload):
    monkeypatch.setattr(
        "cognitive_world.cognition.ollama_embedding.post_provider_json",
        lambda *args, **kwargs: payload,
    )
    with pytest.raises(ValueError):
        _provider(dimensions=2).embed("query")


def test_empty_input_is_rejected_before_transport(monkeypatch):
    calls = []
    monkeypatch.setattr(
        "cognitive_world.cognition.ollama_embedding.post_provider_json",
        lambda *args, **kwargs: calls.append(args),
    )
    with pytest.raises(ValueError):
        _provider().embed(" ")
    assert calls == []


def test_batch_count_or_mixed_dimensions_cannot_be_used(monkeypatch):
    for vectors in ([[1.0, 0.0]], [[1.0, 0.0], [1.0, 0.0, 0.0]]):
        monkeypatch.setattr(
            "cognitive_world.cognition.ollama_embedding.post_provider_json",
            lambda *args, **kwargs: _response("local-test-model", vectors),
        )
        with pytest.raises(ValueError):
            _provider().embed_many(("first", "second"))


def test_authorized_batch_and_store_recheck_keep_lexical_results(monkeypatch):
    requests = []

    def post(_base, _route, body, **_options):
        texts = json.loads(body)["input"]
        requests.extend(texts)
        return _response("local-test-model", [
            [1.0, 0.0] if "sentry" in text or "watchman" in text else [0.0, 1.0]
            for text in texts
        ])

    monkeypatch.setattr("cognitive_world.cognition.ollama_embedding.post_provider_json", post)
    context, store = _context()
    context.memory_retriever = HybridMemoryRetriever(store, _provider(batch_size=2), minimum_similarity=0.8)
    before = store.get_all_memories()
    result = context.get_relevant_memories(MemoryQuery("owner", "sentry", 5))
    assert tuple(item.id for item in result) == ("lexical", "semantic")
    assert len(requests) == 3  # two authorized Memory texts, one query
    assert "private" not in " ".join(requests)
    assert store.get_all_memories() == before


@pytest.mark.parametrize("failure", [ConnectionError("offline"), TimeoutError("late")])
def test_network_failure_preserves_lexical(monkeypatch, failure):
    def post(*_args, **_kwargs):
        raise failure

    monkeypatch.setattr("cognitive_world.cognition.ollama_embedding.post_provider_json", post)
    context, store = _context()
    context.memory_retriever = HybridMemoryRetriever(store, _provider())
    assert tuple(item.id for item in context.get_relevant_memories(
        MemoryQuery("owner", "sentry", 5)
    )) == ("lexical",)


def test_background_host_call_returns_immediately_and_stale_result_drops_semantic(monkeypatch):
    entered = Event()
    release = Event()
    worker_ids = []

    def post(_base, _route, body, **_options):
        worker_ids.append(get_ident())
        entered.set()
        assert release.wait(3)
        texts = json.loads(body)["input"]
        return _response("local-test-model", [[1.0, 0.0] for _ in texts])

    monkeypatch.setattr("cognitive_world.cognition.ollama_embedding.post_provider_json", post)
    context, store = _context()
    fence = RuntimeWriteFence("embedding-session")
    context.memory_retriever = HybridMemoryRetriever(store, _provider(), runtime_fence=fence)
    caller_id = get_ident()
    with ThreadPoolExecutor(max_workers=1) as pool:
        task = pool.submit(context.get_relevant_memories, MemoryQuery("owner", "sentry", 5))
        try:
            assert entered.wait(3)
            assert not task.done()
            fence.freeze_and_advance()
        finally:
            release.set()
        result = task.result(timeout=3)
    assert worker_ids and all(worker_id != caller_id for worker_id in worker_ids)
    assert tuple(item.id for item in result) == ("lexical",)
