"""Bounded LLM-to-GenerationProposal adapter; it has no runtime authority."""
from __future__ import annotations

from dataclasses import dataclass, field
import json
import re
from typing import Mapping, Protocol

from .models import (CharacterTemplate, EventSeed, LocationTemplate,
                     MechanismTemplate, ScenarioTemplate, ObjectTemplate)
from .pipeline import GenerationProposal


SCHEMA_VERSION = 1
MAX_OUTPUT_CHARS = 8_000  # Matches the shared OpenAI-compatible transport cap.
MAX_INPUT_CHARS = 4_000
MAX_DEPTH = 8
MAX_NODES = 300
MAX_TEMPLATES = 8
MAX_MECHANISMS = 8
MAX_SEEDS = 8
MAX_TEXT = 1_000
_IDENTIFIER = re.compile(r"[A-Za-z][A-Za-z0-9_-]{0,79}\Z")


class ContentGenerationError(ValueError):
    """Provider output was unavailable or could not become a safe proposal."""


class ContentGenerationUnavailable(ContentGenerationError):
    """There is no configured provider or the trusted call budget is spent."""


class StructuredContentProvider(Protocol):
    """The existing bounded transport's small, replaceable method surface."""

    def complete_structured(self, instruction: str, payload: Mapping[str, object],
                            *, max_output_chars: int) -> str: ...


@dataclass(frozen=True)
class ContentGenerationRequest:
    """Creative brief only; never a WorldState, Event or cognition snapshot."""
    theme: str
    purpose: str
    constraints: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.constraints, tuple) or len(self.constraints) > 8:
            raise ValueError("generation constraints exceed the bound")
        for value in (self.theme, self.purpose, *self.constraints):
            if not isinstance(value, str) or not value.strip() or len(value) > MAX_TEXT:
                raise ValueError("generation brief text must be bounded and non-empty")
        if len(json.dumps((self.theme, self.purpose, self.constraints), ensure_ascii=False)) > MAX_INPUT_CHARS:
            raise ValueError("generation brief exceeds input bound")


_INSTRUCTION = (
    "Propose reusable CognitiveWorld content definitions as one JSON object. "
    "Use schema_version=1, content_type='generation_proposal' and arrays characters, "
    "locations, scenarios. Supply only template fields shown in the request schema. "
    "Use local references, not runtime instance IDs or world results. "
    "Characters may have goals, locations may have supported door/passage mechanisms, "
    "and scenarios may have optional EventSeed hooks. A seed is potential only. "
    "Do not assert that an event occurred, a character acted, or a world state changed. "
    "No safety override, actor cognition, Event, Resolution or Observation fields."
)


def _pairs(items: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in items:
        if key in result:
            raise ContentGenerationError("duplicate JSON field")
        result[key] = value
    return result


def _bounded_tree(value: object, depth: int = 0) -> int:
    if depth > MAX_DEPTH:
        raise ContentGenerationError("content JSON exceeds depth bound")
    if isinstance(value, dict):
        if len(value) > 16:
            raise ContentGenerationError("content object exceeds field bound")
        count = 1 + sum(1 + _bounded_tree(item, depth + 1) for item in value.values())
    elif isinstance(value, list):
        if len(value) > MAX_NODES:
            raise ContentGenerationError("content array exceeds size bound")
        count = 1 + sum(_bounded_tree(item, depth + 1) for item in value)
    else:
        count = 1
    if count > MAX_NODES:
        raise ContentGenerationError("content JSON exceeds node bound")
    return count


def _object(value: object, required: set[str]) -> dict[str, object]:
    if type(value) is not dict or set(value) != required:
        raise ContentGenerationError("content object has missing or unauthorized fields")
    return value


def _id(value: object) -> str:
    if type(value) is not str or _IDENTIFIER.fullmatch(value) is None:
        raise ContentGenerationError("content identifier is invalid")
    return value


def _text(value: object) -> str:
    if type(value) is not str or not value.strip() or len(value) > MAX_TEXT:
        raise ContentGenerationError("content text is invalid or oversized")
    return value


def _array(value: object, limit: int) -> list:
    if type(value) is not list or len(value) > limit:
        raise ContentGenerationError("content collection exceeds its schema bound")
    return value


def _ids(value: object, limit: int = MAX_TEMPLATES) -> tuple[str, ...]:
    return tuple(_id(item) for item in _array(value, limit))


def _texts(value: object, limit: int = MAX_TEMPLATES) -> tuple[str, ...]:
    return tuple(_text(item) for item in _array(value, limit))


def _boolean(value: object) -> bool:
    if type(value) is not bool:
        raise ContentGenerationError("content flag must be a JSON boolean")
    return value


def _optional_id(value: object) -> str | None:
    return None if value is None else _id(value)


def _mechanism(value: object, version=1) -> MechanismTemplate:
    data = _object(value, {"local_id", "kind", "destination_key", "initially_open", "initially_locked", "operable"} | ({"key_ref"} if version == 2 else set()))
    kind = _id(data["kind"])
    if kind not in {"door", "passage"}:
        raise ContentGenerationError("no installed mechanism adapter")
    return MechanismTemplate(_id(data["local_id"]), kind, _optional_id(data["destination_key"]),
                             _boolean(data["initially_open"]), _boolean(data["initially_locked"]),
                             _boolean(data["operable"]), _optional_id(data["key_ref"]) if version == 2 else None)


def _character(value: object) -> CharacterTemplate:
    data = _object(value, {"template_id", "description", "goal_descriptions", "sensory_capabilities", "physical_capabilities"})
    return CharacterTemplate(_id(data["template_id"]), _text(data["description"]),
                             _texts(data["goal_descriptions"]), _ids(data["sensory_capabilities"]),
                             _ids(data["physical_capabilities"]))


def _location(value: object, version=1) -> LocationTemplate:
    data = _object(value, {"template_id", "description", "mechanisms"})
    return LocationTemplate(_id(data["template_id"]), _text(data["description"]),
                            tuple(_mechanism(item, version) for item in _array(data["mechanisms"], MAX_MECHANISMS)))


def _seed(value: object) -> EventSeed:
    data = _object(value, {"seed_id", "trigger_predicate", "trigger_value", "participant_keys", "possible_effects", "importance", "follow_up_hooks", "constraints"})
    trigger = data["trigger_value"]
    if type(trigger) not in (str, bool):
        raise ContentGenerationError("seed trigger must be a string or boolean")
    if type(trigger) is str:
        trigger = _id(trigger)
    importance = data["importance"]
    if type(importance) not in (int, float):
        raise ContentGenerationError("seed importance must be numeric")
    return EventSeed(_id(data["seed_id"]), _id(data["trigger_predicate"]), trigger,
                     _ids(data["participant_keys"]), _texts(data["possible_effects"]),
                     importance, _ids(data["follow_up_hooks"]), _texts(data["constraints"]))


def _scenario(value: object, version=1) -> ScenarioTemplate:
    data = _object(value, {"template_id", "description", "locations", "characters", "entry_key", "exit_keys", "event_seeds", "side_branch", "value_refs"} | ({"objects"} if version == 2 else set()))
    locations = tuple((_id(item[0]), _id(item[1])) if type(item) is list and len(item) == 2
                      else _invalid_reference() for item in _array(data["locations"], MAX_TEMPLATES))
    characters = tuple((_id(item[0]), _id(item[1]), _id(item[2])) if type(item) is list and len(item) == 3
                       else _invalid_reference() for item in _array(data["characters"], MAX_TEMPLATES))
    return ScenarioTemplate(_id(data["template_id"]), _text(data["description"]),
                            locations, characters, _id(data["entry_key"]),
                            _ids(data["exit_keys"]),
                            tuple(_seed(item) for item in _array(data["event_seeds"], MAX_SEEDS)),
                            _boolean(data["side_branch"]), _ids(data["value_refs"]),
                            tuple(_placement(x) for x in _array(data["objects"], MAX_TEMPLATES)) if version == 2 else ())


def _invalid_reference() -> tuple:
    raise ContentGenerationError("scenario reference must be a bounded tuple shape")


def parse_generation_proposal(raw: str) -> GenerationProposal:
    """Reject every unknown field before constructing Phase 13 template objects."""
    if type(raw) is not str or len(raw) > MAX_OUTPUT_CHARS or not raw:
        raise ContentGenerationError("provider output is missing or oversized")
    try:
        data = json.loads(raw, object_pairs_hook=_pairs,
                          parse_constant=lambda value: (_ for _ in ()).throw(ContentGenerationError("non-finite JSON value")))
    except (json.JSONDecodeError, UnicodeError) as exc:
        raise ContentGenerationError("provider returned malformed JSON") from exc
    _bounded_tree(data)
    version = data.get("schema_version") if type(data) is dict else None
    root = _object(data, {"schema_version", "content_type", "characters", "locations", "scenarios"} | ({"objects"} if version == 2 else set()))
    if type(root["schema_version"]) is not int or root["schema_version"] not in (1, 2) or root["content_type"] != "generation_proposal":
        raise ContentGenerationError("unsupported content schema version or type")
    proposal = GenerationProposal(
        tuple(_character(item) for item in _array(root["characters"], MAX_TEMPLATES)),
        tuple(_location(item, version) for item in _array(root["locations"], MAX_TEMPLATES)),
        tuple(_scenario(item, version) for item in _array(root["scenarios"], MAX_TEMPLATES)),
        tuple(_object_template(x) for x in _array(root["objects"], MAX_TEMPLATES)) if version == 2 else (),
    )
    if not (proposal.characters or proposal.locations or proposal.scenarios):
        raise ContentGenerationError("content proposal contains no reusable definition")
    return proposal


@dataclass
class LLMContentGenerator:
    """One replaceable provider, with a trusted local call budget and no Store."""
    request: ContentGenerationRequest
    provider: StructuredContentProvider | None = None
    max_calls: int = 1
    _calls_used: int = field(default=0, init=False, repr=False)

    def __post_init__(self) -> None:
        if not isinstance(self.request, ContentGenerationRequest):
            raise TypeError("generator requires a bounded creative brief")
        if type(self.max_calls) is not int or not 1 <= self.max_calls <= 4:
            raise ValueError("trusted content model budget must be in [1,4]")

    @classmethod
    def openai_compatible(cls, request: ContentGenerationRequest, *, base_url: str,
                          model: str, api_key: str | None = None,
                          timeout_seconds: float = 8.0, max_calls: int = 1) -> "LLMContentGenerator":
        """Reuse the existing bounded HTTP transport without another LLM stack."""
        from cognitive_world.resolution.providers import OpenAICompatibleCausalProvider
        return cls(request, OpenAICompatibleCausalProvider(base_url, model, api_key, timeout_seconds), max_calls)

    @property
    def calls_remaining(self) -> int:
        return self.max_calls - self._calls_used

    def generate(self) -> GenerationProposal:
        if self.provider is None:
            raise ContentGenerationUnavailable("content provider is not configured")
        if self._calls_used >= self.max_calls:
            raise ContentGenerationUnavailable("content provider call budget is exhausted")
        self._calls_used += 1  # Reserve before calling even if transport fails.
        payload = {
            "theme": self.request.theme,
            "purpose": self.request.purpose,
            "constraints": self.request.constraints,
            "schema_version": SCHEMA_VERSION,
            "content_type": "generation_proposal",
            "template_schema": {
                "character": ["template_id", "description", "goal_descriptions", "sensory_capabilities", "physical_capabilities"],
                "location": ["template_id", "description", "mechanisms"],
                "mechanism": ["local_id", "kind", "destination_key", "initially_open", "initially_locked", "operable"],
                "scenario": ["template_id", "description", "locations", "characters", "entry_key", "exit_keys", "event_seeds", "side_branch", "value_refs"],
                "event_seed": ["seed_id", "trigger_predicate", "trigger_value", "participant_keys", "possible_effects", "importance", "follow_up_hooks", "constraints"],
            },
            "limits": {"templates_per_type": MAX_TEMPLATES, "mechanisms_per_location": MAX_MECHANISMS,
                       "seeds_per_scenario": MAX_SEEDS, "output_chars": MAX_OUTPUT_CHARS},
        }
        try:
            raw = self.provider.complete_structured(_INSTRUCTION, payload, max_output_chars=MAX_OUTPUT_CHARS)
        except Exception as exc:
            raise ContentGenerationUnavailable(f"content provider unavailable: {type(exc).__name__}") from exc
        return parse_generation_proposal(raw)


def _local_ref(value, allowed):
    if not isinstance(value, str) or ":" not in value:
        raise ContentGenerationError("placement needs an explicit local namespace")
    prefix, key = value.split(":", 1)
    if prefix not in allowed:
        raise ContentGenerationError("unsupported placement namespace")
    _id(key)
    return value


def _placement(value):
    if type(value) is not list or len(value) != 4:
        raise ContentGenerationError("object placement needs key, template, location and optional owner")
    return (_id(value[0]), _id(value[1]), _local_ref(value[2], {"location", "actor"}),
            None if value[3] is None else _local_ref(value[3], {"actor"}))


def _object_template(value):
    from cognitive_world.core.object_appearance import ObjectAppearance
    data = _object(value, {"template_id", "description", "kind", "appearance"})
    a = _object(data["appearance"], {"version", "shape", "detail", "visible", "detail_visible"})
    return ObjectTemplate(_id(data["template_id"]), _text(data["description"]), _id(data["kind"]),
        ObjectAppearance(a["version"], _id(a["shape"]), _id(a["detail"]),
                         _boolean(a["visible"]), _boolean(a["detail_visible"])))
