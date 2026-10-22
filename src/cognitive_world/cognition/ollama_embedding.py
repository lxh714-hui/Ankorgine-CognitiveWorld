"""Optional, local-only Ollama adapter for the existing embedding contract.

The host must explicitly inject this provider into HybridMemoryRetriever. The
adapter carries text only; it has no Memory, Event, Runtime, or write authority.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
import math

from cognitive_world.cognition.memory_semantic_retrieval import (
    MAX_EMBEDDING_BATCH,
    MAX_EMBEDDING_DIMENSIONS,
    MAX_SEMANTIC_TEXT_CHARS,
)
from cognitive_world.core.provider_transport import (
    post_provider_json,
    validate_provider_endpoint,
)


MAX_EMBED_RESPONSE_BYTES = 2_000_000


@dataclass(frozen=True)
class OllamaEmbeddingProvider:
    """Synchronous local transport; hosts must invoke slow retrieval off UI threads."""

    base_url: str
    model: str
    timeout_seconds: float = 8.0
    dimensions: int | None = None
    batch_size: int = MAX_EMBEDDING_BATCH

    def __post_init__(self) -> None:
        endpoint = validate_provider_endpoint(self.base_url)
        if endpoint.scheme != "http" or endpoint.connect_host is None or endpoint.path:
            raise ValueError("embedding endpoint must be an HTTP loopback origin")
        if not isinstance(self.model, str) or not self.model.strip() or len(self.model) > 160:
            raise ValueError("an explicitly configured embedding model is required")
        if (type(self.timeout_seconds) not in (int, float)
                or not math.isfinite(self.timeout_seconds)
                or not 0.1 <= self.timeout_seconds <= 30.0):
            raise ValueError("embedding timeout is outside its bound")
        if self.dimensions is not None and (
            type(self.dimensions) is not int
            or not 1 <= self.dimensions <= MAX_EMBEDDING_DIMENSIONS
        ):
            raise ValueError("embedding dimensions are outside their bound")
        if type(self.batch_size) is not int or not 1 <= self.batch_size <= MAX_EMBEDDING_BATCH:
            raise ValueError("embedding batch size is outside its bound")

    def embed(self, text: str) -> tuple[float, ...]:
        return self.embed_many((text,))[0]

    def embed_many(self, texts: tuple[str, ...]) -> tuple[tuple[float, ...], ...]:
        if not isinstance(texts, tuple) or not 1 <= len(texts) <= self.batch_size:
            raise ValueError("embedding batch must be a bounded nonempty tuple")
        if any(
            not isinstance(text, str) or not text.strip()
            or len(text) > MAX_SEMANTIC_TEXT_CHARS
            for text in texts
        ):
            raise ValueError("embedding input must be bounded nonempty text")
        body: dict[str, object] = {
            "model": self.model,
            "input": list(texts),
            "truncate": False,
        }
        if self.dimensions is not None:
            body["dimensions"] = self.dimensions
        raw = post_provider_json(
            self.base_url, "/api/embed",
            json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode("utf-8"),
            headers={"Content-Type": "application/json", "Accept": "application/json"},
            timeout_seconds=float(self.timeout_seconds),
            maximum_bytes=MAX_EMBED_RESPONSE_BYTES,
        )
        try:
            response = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, ValueError) as exc:
            raise ValueError("embedding response is not valid JSON") from exc
        if not isinstance(response, dict) or response.get("model") != self.model:
            raise ValueError("embedding response model is invalid")
        embeddings = response.get("embeddings")
        if not isinstance(embeddings, list) or len(embeddings) != len(texts):
            raise ValueError("embedding response count is invalid")
        result: list[tuple[float, ...]] = []
        dimension: int | None = self.dimensions
        for vector in embeddings:
            if (not isinstance(vector, list) or not vector
                    or len(vector) > MAX_EMBEDDING_DIMENSIONS
                    or (dimension is not None and len(vector) != dimension)
                    or any(type(value) not in (int, float) or not math.isfinite(value)
                           for value in vector)):
                raise ValueError("embedding vector is invalid")
            if not any(value != 0 for value in vector):
                raise ValueError("embedding vector has no direction")
            dimension = len(vector)
            result.append(tuple(float(value) for value in vector))
        return tuple(result)
