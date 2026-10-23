"""One bounded synthetic inference per local provider/model; no Runtime access."""

from concurrent.futures import Future
from dataclasses import dataclass
import json
import os
from threading import RLock, Thread

from cognitive_world.dialogue.ollama import _post_loopback_json
from cognitive_world.player.input_understanding import OllamaPlayerInputUnderstandingProvider


@dataclass(frozen=True)
class ModelWarmupStatus:
    state: str
    error_code: str | None = None


class ModelNotReady(RuntimeError):
    def __init__(self, state: str):
        super().__init__(state)
        self.state = state


_LOCK = RLock()
_JOBS: dict[tuple[str, str, str], Future[ModelWarmupStatus]] = {}
_SETTINGS = ("COGNITIVEWORLD_INPUT_UNDERSTANDING_PROVIDER", "COGNITIVEWORLD_OLLAMA_MODEL",
             "COGNITIVEWORLD_OLLAMA_BASE_URL", "COGNITIVEWORLD_INPUT_UNDERSTANDING_TIMEOUT")


def _infer(factory, future):
    if not future.set_running_or_notify_cancel():
        return
    try:
        provider = factory()
        body = json.dumps({
            "model": provider.model,
            "messages": [{"role": "user", "content": "Reply with OK."}],
            "temperature": 0, "max_tokens": 8, "stream": False,
        }).encode("utf-8")
        payload = _post_loopback_json(provider.base_url, body,
                                     timeout_seconds=provider.timeout_seconds, maximum_bytes=8000)
        message = json.loads(payload.decode("utf-8"))["choices"][0]
        if (not isinstance(message["message"]["content"], str)
                or not message["message"]["content"].strip()
                or message.get("finish_reason") not in {"stop", "length"}):
            raise ValueError("inference did not complete")
        # Neither content nor the response envelope leaves this worker.
        result = ModelWarmupStatus("ready")
    except TimeoutError:
        result = ModelWarmupStatus("failed", "timeout")
    except (ConnectionError, OSError):
        result = ModelWarmupStatus("failed", "unreachable")
    except Exception:
        result = ModelWarmupStatus("failed", "configuration_or_response_invalid")
    future.set_result(result)


class LocalModelWarmup:
    """A disposable host view of shared inference, never a world-task capability.

    Closing detaches this view. An in-flight HTTP call has the configured timeout
    and can finish without a window; it holds no UI/Runtime reference. Daemon
    workers cannot hold application shutdown open. Failed jobs retry only on an
    explicit request, not on polling or world switching.
    """

    def __init__(self):
        self._job = None
        self._key = None
        self._status = ModelWarmupStatus("not_started")
        self._closed = False

    def start(self, provider=None, *, retry=False):
        if self._closed:
            return
        if provider is not None and not isinstance(provider, OllamaPlayerInputUnderstandingProvider):
            self._job = None
            self._key = None
            self._status = ModelWarmupStatus("not_required")
            return
        if provider is None:
            settings = {key: os.environ[key] for key in _SETTINGS if key in os.environ}
            selection = settings.get(_SETTINGS[0], "").strip().casefold()
            if not selection:
                self._job = None
                self._key = None
                self._status = ModelWarmupStatus("not_configured")
                return
            key = (selection, settings.get(_SETTINGS[2], "http://127.0.0.1:11434/v1").rstrip("/"),
                   settings.get(_SETTINGS[1], "").strip())
            factory = lambda: OllamaPlayerInputUnderstandingProvider.from_environment(settings)
        else:
            key = ("ollama", provider.base_url.rstrip("/"), provider.model)
            factory = lambda: provider
        with _LOCK:
            job = _JOBS.get(key)
            if job is None or (retry and job.done() and job.result().state == "failed"):
                job = Future()
                _JOBS[key] = job
                Thread(target=_infer, args=(factory, job), name="anchor-model-warmup", daemon=True).start()
            self._job = job
            self._key = key

    def status(self):
        if self._closed:
            return ModelWarmupStatus("closed")
        if self._job is None:
            return self._status
        with _LOCK:
            job = _JOBS.get(self._key, self._job)
        return job.result() if job.done() else ModelWarmupStatus("warming")

    def detach(self):
        self._job = None
        self._key = None
        self._status = ModelWarmupStatus("not_started")

    def close(self):
        self.detach()
        self._closed = True
