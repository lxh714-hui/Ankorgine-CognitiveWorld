"""A fresh package enters the real Core without a scene-specific Core branch."""

from pathlib import Path
import json
from threading import Event
from time import monotonic, sleep

import pytest

from anchor_desktop.host import start_new_world, resume_saved_world
from cognitive_world.content.persistence import scenario_snapshot_codec
from anchor_desktop.product_gateway import DesktopProductGateway
from anchor_desktop.world_packages import WorldPackageCatalog
from cognitive_world.core.persistence import HmacPersistenceTrust, sha256_hex
from cognitive_world.core.world_state import WorldState
from cognitive_world.player.async_coordinator import PlayerTaskExecutionState
from cognitive_world.player.service import PlayerActionRequest
from cognitive_world.player.input_understanding import (
    InputUnderstandingStatus, PlayerInputAssessment, PlayerInputRequest,
)
from cognitive_world.runtime.save_manager import SaveManager


PACKAGES = Path(__file__).parents[1] / "src" / "anchor_desktop" / "worlds"


@pytest.mark.parametrize("world_id", ("clockwork-library", "rain-harbor"))
def test_old_clarification_cannot_rebind_after_formal_travel(world_id):
    """Audit reproduction: the new room also offers candidate-1, a different entity."""
    from dataclasses import replace
    from cognitive_world.content.models import MechanismTemplate
    from cognitive_world.event.factory import SystemEventFactory

    package = WorldPackageCatalog(PACKAGES).package(world_id)
    locations = list(package.proposal.locations)
    locations[0] = replace(locations[0], mechanisms=locations[0].mechanisms + (
        MechanismTemplate("aux-door", "door"),
    ))
    locations[1] = replace(locations[1], mechanisms=(
        MechanismTemplate("replacement-door", "door"),
    ))
    package = replace(package, proposal=replace(package.proposal, locations=tuple(locations)))
    session = start_new_world(package, trust=HmacPersistenceTrust(b"rebind-test-key" * 4),
                              input_understanding_provider=CandidateInteractionInterpreter(clarify=True))
    try:
        service = session.player_service
        context = session.runtime.context
        binding = context.player_session
        original_pairs = service._request_candidates()
        original_target = original_pairs[0][1]
        first = session.player_tasks.submit_input(PlayerInputRequest(
            "old-choice", binding.session_id, world_id, "Operate the selected object.",
        ))
        assert session.player_tasks.completion(first).result(timeout=5).outcome_status == "clarification_required"
        passage = next(ref for candidate, ref in original_pairs if candidate.kind == "passage")
        old_location = context.world_state.locations[binding.controlled_agent_id]
        with session.runtime.write_fence.operation():
            service.submit(PlayerActionRequest(
                "formal-travel", binding.session_id, world_id, "travel",
                "walk through the passage", passage,
            ))
        new_location = context.world_state.locations[binding.controlled_agent_id]
        assert new_location != old_location
        assert any(event.has_trusted_source("resolution") for event in
                   context.event_history.get_events())
        target = next(ref for ref, value in context.world_state.environment.items()
                      if getattr(value, "interaction_location_id", None) == new_location)
        session.runtime.event_processor.dispatch_with_evidence(SystemEventFactory().create(
            event_id="observe-after-travel", event_type="environment_state_observed",
            timestamp="0", simulation_tick=context.clock.current_time,
            changes=[{"environment_id": target}],
        ))
        assert service._request_candidates()[0][1] != original_target
        before_events = context.event_history.get_events()
        before_state = dict(context.world_state.environment)
        answer = session.player_tasks.submit_input(PlayerInputRequest(
            "old-choice-answer", binding.session_id, world_id, "1",
            clarification_id="old-choice",
        ))
        assert session.player_tasks.completion(answer).result(timeout=5).outcome_status == "clarification_expired"
        assert context.event_history.get_events() == before_events
        assert context.world_state.environment == before_state
        assert not context.world_state.environment[original_target].is_open
        assert not context.world_state.environment[target].is_open
    finally:
        session.close()


def test_clarification_keeps_original_identity_when_candidate_order_and_handles_change(monkeypatch):
    from dataclasses import replace

    session = start_new_world(WorldPackageCatalog(PACKAGES).package("rain-harbor"),
                              trust=HmacPersistenceTrust(b"ordered-choice-key" * 4),
                              input_understanding_provider=CandidateInteractionInterpreter(clarify=True))
    try:
        service = session.player_service
        binding = session.runtime.context.player_session
        original = service._request_candidates
        selected = original()[0][1]
        first = session.player_tasks.submit_input(PlayerInputRequest(
            "ordered-choice", binding.session_id, "rain-harbor", "Operate this object.",
        ))
        assert session.player_tasks.completion(first).result(timeout=5).outcome_status == "clarification_required"
        monkeypatch.setattr(service, "_request_candidates", lambda: tuple(
            (replace(candidate, handle=f"candidate-{index}"), reference)
            for index, (candidate, reference) in enumerate(reversed(original()), 1)
        ))
        before = len(session.runtime.context.event_history.get_events())
        second = session.player_tasks.submit_input(PlayerInputRequest(
            "ordered-answer", binding.session_id, "rain-harbor", "1",
            clarification_id="ordered-choice",
        ))
        assert session.player_tasks.completion(second).result(timeout=5).outcome_status == "resolved"
        assert session.runtime.context.world_state.environment[selected].is_open
        assert len(session.runtime.context.event_history.get_events()) == before + 1
    finally:
        session.close()


def test_clarification_survives_unrelated_formal_world_change():
    from cognitive_world.core.update import WorldUpdate
    from cognitive_world.event.factory import SystemEventFactory
    from cognitive_world.event.handler import EventHandler

    session = start_new_world(WorldPackageCatalog(PACKAGES).package("rain-harbor"),
                              trust=HmacPersistenceTrust(b"unrelated-choice-key" * 4),
                              input_understanding_provider=CandidateInteractionInterpreter(clarify=True))
    try:
        context = session.runtime.context
        binding = context.player_session
        target = session.player_service._request_candidates()[0][1]
        first = session.player_tasks.submit_input(PlayerInputRequest(
            "unrelated-choice", binding.session_id, "rain-harbor", "Operate this object.",
        ))
        assert session.player_tasks.completion(first).result(timeout=5).outcome_status == "clarification_required"

        class RecordUnrelatedFact(EventHandler):
            def handle(self, event):
                return WorldUpdate("facts", "update", {"unrelated-audit-fact": True})

        session.runtime.event_processor.register_handler("test_unrelated_fact", RecordUnrelatedFact())
        session.runtime.event_processor.dispatch_with_evidence(SystemEventFactory().create(
            event_id="unrelated-formal-change", event_type="test_unrelated_fact", timestamp="0",
        ))
        assert context.world_state.facts["unrelated-audit-fact"] is True
        before = len(context.event_history.get_events())
        second = session.player_tasks.submit_input(PlayerInputRequest(
            "unrelated-answer", binding.session_id, "rain-harbor", "1",
            clarification_id="unrelated-choice",
        ))
        assert session.player_tasks.completion(second).result(timeout=5).outcome_status == "resolved"
        assert context.world_state.environment[target].is_open
        assert len(context.event_history.get_events()) == before + 1
    finally:
        session.close()


@pytest.mark.parametrize("wrong_selection", ("unlisted", "wrong_ordinal"))
def test_choice_rejects_authorized_candidate_outside_displayed_options(wrong_selection):
    from dataclasses import replace
    from cognitive_world.content.models import MechanismTemplate

    class WrongChoice(CandidateInteractionInterpreter):
        def understand_candidates(self, request, *, candidates):
            doors = tuple(item for item in candidates if item.kind == "door")
            assert len(doors) == 2
            return PlayerInputAssessment(
                InputUnderstandingStatus.CLARIFICATION_REQUIRED,
                "open a door", "push the door", None,
                ("target",), "Which door?", "choice",
                tuple(item.handle for item in doors),
            )

        def resolve_clarification(self, request, *, original, prior, candidates):
            selected = next(item for item in candidates if item.handle == (
                prior.option_handles[1] if wrong_selection == "wrong_ordinal" else
                next(item.handle for item in candidates if item.handle not in prior.option_handles)
            ))
            return PlayerInputAssessment(InputUnderstandingStatus.ACTION, prior.intent,
                                         selected.supported_methods[0], selected.handle)

    package = WorldPackageCatalog(PACKAGES).package("rain-harbor")
    locations = list(package.proposal.locations)
    locations[0] = replace(locations[0], mechanisms=locations[0].mechanisms + (
        MechanismTemplate("second-door", "door"),
    ))
    package = replace(package, proposal=replace(package.proposal, locations=tuple(locations)))
    session = start_new_world(package, trust=HmacPersistenceTrust(b"wrong-choice-key" * 4),
                              input_understanding_provider=WrongChoice())
    try:
        binding = session.runtime.context.player_session
        first = session.player_tasks.submit_input(PlayerInputRequest(
            "subset-question", binding.session_id, "rain-harbor", "Open a door.",
        ))
        assert session.player_tasks.completion(first).result(timeout=5).outcome_status == "clarification_required"
        before_events = session.runtime.context.event_history.get_events()
        before_state = dict(session.runtime.context.world_state.environment)
        second = session.player_tasks.submit_input(PlayerInputRequest(
            "subset-answer", binding.session_id, "rain-harbor", "1",
            clarification_id="subset-question",
        ))
        assert session.player_tasks.completion(second).result(timeout=5).outcome_status == "reasoning_unavailable"
        assert session.runtime.context.event_history.get_events() == before_events
        assert session.runtime.context.world_state.environment == before_state
        assert all(event.cause != "subset-answer" for event in before_events)
    finally:
        session.close()


def test_free_text_clarification_keeps_authorized_target_path():
    class FreeText(CandidateInteractionInterpreter):
        def understand_candidates(self, request, *, candidates):
            return PlayerInputAssessment(
                InputUnderstandingStatus.CLARIFICATION_REQUIRED,
                "open the observed door", "push the door", None,
                ("target",), "Which object?", "free_text",
            )

        def resolve_clarification(self, request, *, original, prior, candidates):
            door = next(item for item in candidates if item.kind == "door")
            return PlayerInputAssessment(InputUnderstandingStatus.ACTION, prior.intent,
                                         door.supported_methods[0], door.handle)

    session = start_new_world(WorldPackageCatalog(PACKAGES).package("rain-harbor"),
                              trust=HmacPersistenceTrust(b"free-text-choice-key" * 4),
                              input_understanding_provider=FreeText())
    try:
        binding = session.runtime.context.player_session
        first = session.player_tasks.submit_input(PlayerInputRequest(
            "free-text-question", binding.session_id, "rain-harbor", "Open that.",
        ))
        assert session.player_tasks.completion(first).result(timeout=5).outcome_status == "clarification_required"
        answer = session.player_tasks.submit_input(PlayerInputRequest(
            "free-text-answer", binding.session_id, "rain-harbor", "The door I can see.",
            clarification_id="free-text-question",
        ))
        assert session.player_tasks.completion(answer).result(timeout=5).outcome_status == "resolved"
        door = next(reference for candidate, reference in session.player_service._request_candidates()
                    if candidate.kind == "door")
        assert session.runtime.context.world_state.environment[door].is_open
    finally:
        session.close()


def test_late_reply_cannot_answer_a_newer_clarification():
    class TwoQuestions(CandidateInteractionInterpreter):
        def understand_candidates(self, request, *, candidates):
            selected = candidates[0] if request.text == "first question" else candidates[-1]
            return PlayerInputAssessment(
                InputUnderstandingStatus.CLARIFICATION_REQUIRED,
                "operate the selected object", "pending", None,
                ("target",), "Which object?", "choice", (selected.handle,),
            )

        def resolve_clarification(self, request, *, original, prior, candidates):
            if request.text == "second question":
                return PlayerInputAssessment(InputUnderstandingStatus.INDEPENDENT_REQUEST)
            selected = next(item for item in candidates if item.handle == prior.option_handles[0])
            return PlayerInputAssessment(InputUnderstandingStatus.ACTION, prior.intent,
                                         selected.supported_methods[0], selected.handle)

    session = start_new_world(WorldPackageCatalog(PACKAGES).package("rain-harbor"),
                              trust=HmacPersistenceTrust(b"two-questions-key" * 4),
                              input_understanding_provider=TwoQuestions())
    try:
        binding = session.runtime.context.player_session
        for request_id, text, clarification_id in (
            ("question-a", "first question", None),
            ("question-b", "second question", "question-a"),
        ):
            handle = session.player_tasks.submit_input(PlayerInputRequest(
                request_id, binding.session_id, "rain-harbor", text,
                clarification_id=clarification_id,
            ))
            assert session.player_tasks.completion(handle).result(timeout=5).outcome_status == "clarification_required"
        before_events = session.runtime.context.event_history.get_events()
        before_state = dict(session.runtime.context.world_state.environment)
        stale = session.player_tasks.submit_input(PlayerInputRequest(
            "late-a", binding.session_id, "rain-harbor", "1", clarification_id="question-a",
        ))
        assert session.player_tasks.completion(stale).result(timeout=5).outcome_status == "clarification_expired"
        missing = session.player_tasks.submit_input(PlayerInputRequest(
            "missing-id", binding.session_id, "rain-harbor", "1",
        ))
        assert session.player_tasks.completion(missing).result(timeout=5).outcome_status == "clarification_expired"
        assert session.runtime.context.event_history.get_events() == before_events
        assert session.runtime.context.world_state.environment == before_state
        current = session.player_tasks.submit_input(PlayerInputRequest(
            "answer-b", binding.session_id, "rain-harbor", "1", clarification_id="question-b",
        ))
        assert session.player_tasks.completion(current).result(timeout=5).outcome_status == "resolved"
        assert len(session.runtime.context.event_history.get_events()) == len(before_events) + 1
    finally:
        session.close()


def test_clarification_expires_after_formal_target_state_change():
    session = start_new_world(WorldPackageCatalog(PACKAGES).package("rain-harbor"),
                              trust=HmacPersistenceTrust(b"changed-choice-key" * 4),
                              input_understanding_provider=CandidateInteractionInterpreter(clarify=True))
    try:
        service = session.player_service
        binding = session.runtime.context.player_session
        candidate, target = service._request_candidates()[0]
        first = session.player_tasks.submit_input(PlayerInputRequest(
            "changed-choice", binding.session_id, "rain-harbor", "Operate this object.",
        ))
        assert session.player_tasks.completion(first).result(timeout=5).outcome_status == "clarification_required"
        with session.runtime.write_fence.operation():
            service.submit(PlayerActionRequest("independent-operation", binding.session_id,
                "rain-harbor", "operate", candidate.supported_methods[0], target))
        assert session.runtime.context.world_state.environment[target].is_open
        before = session.runtime.context.event_history.get_events()
        second = session.player_tasks.submit_input(PlayerInputRequest(
            "changed-answer", binding.session_id, "rain-harbor", "1",
            clarification_id="changed-choice",
        ))
        assert session.player_tasks.completion(second).result(timeout=5).outcome_status == "clarification_expired"
        assert session.runtime.context.event_history.get_events() == before
    finally:
        session.close()


@pytest.mark.parametrize("replacement", (False, True))
def test_clarification_rejects_removed_or_same_description_different_identity(replacement):
    from cognitive_world.event.factory import SystemEventFactory
    from cognitive_world.event.handler import EventHandler
    from cognitive_world.core.update import WorldUpdate

    session = start_new_world(WorldPackageCatalog(PACKAGES).package("rain-harbor"),
                              trust=HmacPersistenceTrust(b"identity-choice-key" * 4),
                              input_understanding_provider=CandidateInteractionInterpreter(clarify=True))
    try:
        service = session.player_service
        context = session.runtime.context
        binding = context.player_session
        candidate, target = service._request_candidates()[0]
        first = session.player_tasks.submit_input(PlayerInputRequest(
            "identity-choice", binding.session_id, "rain-harbor", "Operate this object.",
        ))
        assert session.player_tasks.completion(first).result(timeout=5).outcome_status == "clarification_required"
        # Trusted test host changes the collection through EventProcessor, not
        # by mutating WorldState. The replacement has exactly the old state.
        environment = dict(context.world_state.environment)
        old_value = environment.pop(target)
        new_target = target + "-replacement"
        if replacement:
            environment[new_target] = old_value

        class ReplaceEnvironment(EventHandler):
            def handle(self, event):
                return WorldUpdate("environment", "set", environment)

        session.runtime.event_processor.register_handler("test_environment_replaced", ReplaceEnvironment())
        session.runtime.event_processor.dispatch_with_evidence(SystemEventFactory().create(
            event_id="replace-original-target", event_type="test_environment_replaced", timestamp="0",
        ))
        if replacement:
            session.runtime.event_processor.dispatch_with_evidence(SystemEventFactory().create(
                event_id="observe-replacement", event_type="environment_state_observed", timestamp="0",
                simulation_tick=context.clock.current_time, changes=[{"environment_id": new_target}],
            ))
            assert any(item.description == candidate.description and ref != target
                       for item, ref in service._request_candidates())
        before_events = context.event_history.get_events()
        before_state = dict(context.world_state.environment)
        second = session.player_tasks.submit_input(PlayerInputRequest(
            "identity-answer", binding.session_id, "rain-harbor", "1",
            clarification_id="identity-choice",
        ))
        assert session.player_tasks.completion(second).result(timeout=5).outcome_status == "clarification_expired"
        assert context.event_history.get_events() == before_events
        assert context.world_state.environment == before_state
    finally:
        session.close()


def test_clarification_rechecks_context_at_final_dispatch_boundary(monkeypatch):
    session = start_new_world(WorldPackageCatalog(PACKAGES).package("rain-harbor"),
                              trust=HmacPersistenceTrust(b"final-check-key" * 4),
                              input_understanding_provider=CandidateInteractionInterpreter(clarify=True))
    try:
        service = session.player_service
        context = session.runtime.context
        binding = context.player_session
        pairs = service._request_candidates()
        target = pairs[0][1]
        passage = next(ref for candidate, ref in pairs if candidate.kind == "passage")
        first = session.player_tasks.submit_input(PlayerInputRequest(
            "final-choice", binding.session_id, "rain-harbor", "Operate this object.",
        ))
        assert session.player_tasks.completion(first).result(timeout=5).outcome_status == "clarification_required"
        execute = service.resolution_flow.execute_with_result
        moved = False

        def change_location_after_resolution(*args, **kwargs):
            nonlocal moved
            result = execute(*args, **kwargs)
            if not moved:
                moved = True
                service.submit(PlayerActionRequest("interleaved-travel", binding.session_id,
                    "rain-harbor", "travel", "walk through the passage", passage))
            return result

        monkeypatch.setattr(service.resolution_flow, "execute_with_result", change_location_after_resolution)
        before = len(context.event_history.get_events())
        second = session.player_tasks.submit_input(PlayerInputRequest(
            "final-answer", binding.session_id, "rain-harbor", "1",
            clarification_id="final-choice",
        ))
        assert session.player_tasks.completion(second).result(timeout=5).outcome_status == "clarification_expired"
        assert len(context.event_history.get_events()) == before + 1  # travel only
        assert not context.world_state.environment[target].is_open
    finally:
        session.close()


@pytest.mark.parametrize("world_id", ("clockwork-library", "rain-harbor"))
def test_ollama_readonly_null_method_uses_current_authorized_observations(monkeypatch, world_id):
    from copy import deepcopy
    from cognitive_world.player.input_understanding import OllamaPlayerInputUnderstandingProvider

    calls = []

    def transport(url, body, **kwargs):
        calls.append(json.loads(body))
        response = {"status": "observe", "intent": "inspect current surroundings",
                    "method": None, "target_ref": None}
        return json.dumps({"choices": [{"message": {"content": json.dumps(response)}}]}).encode()

    monkeypatch.setattr("cognitive_world.player.input_understanding._post_loopback_json", transport)
    session = start_new_world(
        WorldPackageCatalog(PACKAGES).package(world_id),
        trust=HmacPersistenceTrust(b"readonly-wire-test-key" * 4),
        input_understanding_provider=OllamaPlayerInputUnderstandingProvider(
            "http://127.0.0.1:11434/v1", "test-model"),
    )
    try:
        context = session.runtime.context
        binding = context.player_session
        before_events = context.event_history.get_events()
        def world_snapshot():
            return deepcopy(tuple(dict(getattr(context.world_state, name)) for name in (
                "entities", "locations", "relationships", "facts", "environment")))

        before_world = world_snapshot()
        visible = session.player_service._current_visible_environment()
        assert visible
        request = PlayerInputRequest("readonly-null-method", binding.session_id, world_id,
                                     "inspect the surroundings")
        handle = session.player_tasks.submit_input(request)
        result = session.player_tasks.completion(handle).result(timeout=5)
        assert result.outcome_status == "observed"
        delivered = session.output.observation_results_for(binding.player_id)
        assert len(delivered) == 1 and delivered[0].request_id == request.request_id
        messages = delivered[0].batch.messages
        assert messages
        assert {message.content for message in messages} == {
            session.player_service.presentation.composer._render(item) for item in visible
        }
        assert context.event_history.get_events() == before_events
        assert world_snapshot() == before_world
        assert session.player_tasks.submit_input(request) == handle
        assert len(calls) == 1
        assert len(session.output.observation_results_for(binding.player_id)) == 1
    finally:
        session.close()


class GroundedActionInterpreter:
    def understand(self, request, *, authorized_targets):
        assert authorized_targets
        return PlayerInputAssessment(
            InputUnderstandingStatus.ACTION,
            intent="open the observed door", method="push the closed door",
            target_ref=next(target for target in authorized_targets if "door" in target),
        )


class CandidateInteractionInterpreter:
    def __init__(self, *, clarify=False, observe=False):
        self.clarify, self.observe = clarify, observe
        self.calls = []

    def understand_candidates(self, request, *, candidates):
        self.calls.append((request.text, candidates))
        assert candidates and all(candidate.handle.startswith("candidate-") for candidate in candidates)
        assert all("instance:" not in candidate.description for candidate in candidates)
        if self.observe:
            return PlayerInputAssessment(InputUnderstandingStatus.OBSERVE,
                                         "inspect", "read current observation", None)
        if self.clarify:
            return PlayerInputAssessment(
                InputUnderstandingStatus.CLARIFICATION_REQUIRED,
                "operate the selected object", "operation pending target", None,
                ("target",), "请选择要操作的对象。", "choice",
                tuple(candidate.handle for candidate in candidates),
            )
        selected = next(candidate for candidate in candidates if candidate.kind == "door")
        return PlayerInputAssessment(InputUnderstandingStatus.ACTION,
                                     "open the observed object", selected.supported_methods[0],
                                     selected.handle)

    def resolve_clarification(self, request, *, original, prior, candidates):
        self.calls.append((request.text, candidates))
        if prior.answer_mode == "choice" and request.text.strip().isdecimal():
            index = int(request.text.strip()) - 1
            if 0 <= index < len(prior.option_handles):
                candidate = next(item for item in candidates
                                 if item.handle == prior.option_handles[index])
                if candidate.supported_methods:
                    return PlayerInputAssessment(
                        InputUnderstandingStatus.ACTION, prior.intent,
                        candidate.supported_methods[0], candidate.handle,
                    )
        if prior.answer_mode == "yes_no":
            if request.text.strip() in {"不是", "否", "no", "n"}:
                return PlayerInputAssessment(InputUnderstandingStatus.CANCELLED)
            if request.text.strip() in {"是", "yes", "y"}:
                candidate = next(item for item in candidates
                                 if item.handle == prior.resolved_target_handle)
                return PlayerInputAssessment(
                    InputUnderstandingStatus.ACTION, prior.intent,
                    candidate.supported_methods[0], candidate.handle,
                )
        return PlayerInputAssessment(InputUnderstandingStatus.INDEPENDENT_REQUEST)


@pytest.mark.parametrize("world_id", ("clockwork-library", "rain-harbor"))
def test_candidate_interaction_observation_and_choice_are_authorized_across_worlds(world_id):
    catalog = WorldPackageCatalog(PACKAGES)
    observer = CandidateInteractionInterpreter(observe=True)
    session = start_new_world(catalog.package(world_id),
                              trust=HmacPersistenceTrust(b"candidate-test-key" * 4),
                              input_understanding_provider=observer)
    try:
        binding = session.runtime.context.player_session
        before_events = session.runtime.context.event_history.get_events()
        before_state = dict(session.runtime.context.world_state.environment)
        request = PlayerInputRequest("inspect-one", binding.session_id, world_id, "查看周围")
        handle = session.player_tasks.submit_input(request)
        outcome = session.player_tasks.completion(handle).result(timeout=5)
        assert outcome.outcome_status == "observed"
        results = session.output.observation_results_for(binding.player_id)
        assert results and results[-1].request_id == request.request_id
        assert results[-1].batch.messages
        assert session.runtime.context.event_history.get_events() == before_events
        assert session.runtime.context.world_state.environment == before_state
        assert all(item.handle not in item.description for item in observer.calls[0][1])
    finally:
        session.close()


@pytest.mark.parametrize("world_id", ("clockwork-library", "rain-harbor"))
def test_choice_clarification_continues_original_action_once_across_worlds(world_id):
    catalog = WorldPackageCatalog(PACKAGES)
    interpreter = CandidateInteractionInterpreter(clarify=True)
    session = start_new_world(catalog.package(world_id),
                              trust=HmacPersistenceTrust(b"choice-test-key" * 4),
                              input_understanding_provider=interpreter)
    try:
        binding = session.runtime.context.player_session
        history = session.runtime.context.event_history
        before = len(history.get_events())
        original = PlayerInputRequest("clarify-original", binding.session_id, world_id,
                                      "打开这个")
        first = session.player_tasks.submit_input(original)
        assert session.player_tasks.completion(first).result(timeout=5).outcome_status == "clarification_required"
        assert len(history.get_events()) == before
        answer = PlayerInputRequest("clarify-answer", binding.session_id, world_id, "1",
                                    clarification_id="clarify-original")
        second = session.player_tasks.submit_input(answer)
        outcome = session.player_tasks.completion(second).result(timeout=5)
        assert outcome.outcome_status == "resolved"
        assert len(history.get_events()) == before + 1
        assert history.get_events()[-1].has_trusted_source("resolution")
        assert session.player_tasks.submit_input(answer) == second
        assert len(history.get_events()) == before + 1
    finally:
        session.close()


@pytest.mark.parametrize("world_id", ("clockwork-library", "rain-harbor"))
def test_candidate_handle_maps_only_to_observed_target_before_formal_commit(world_id):
    catalog = WorldPackageCatalog(PACKAGES)
    session = start_new_world(catalog.package(world_id),
                              trust=HmacPersistenceTrust(b"handle-test-key" * 4),
                              input_understanding_provider=CandidateInteractionInterpreter())
    try:
        binding = session.runtime.context.player_session
        before_events = session.runtime.context.event_history.get_events()
        before = len(before_events)
        before_environment = dict(session.runtime.context.world_state.environment)
        handle = session.player_tasks.submit_input(PlayerInputRequest(
            "candidate-action", binding.session_id, world_id, "打开看到的对象",
        ))
        result = session.player_tasks.completion(handle).result(timeout=5)
        assert result.outcome_status == "resolved"
        events = session.runtime.context.event_history.get_events()
        assert len(events) == before + 1
        assert events[-1].has_trusted_source("resolution")
        changed = [key for key, value in session.runtime.context.world_state.environment.items()
                   if getattr(value, "is_open", False)
                   and not getattr(before_environment.get(key), "is_open", False)]
        assert len(changed) == 1
        assert session.output.messages_for(binding.player_id)
    finally:
        session.close()


@pytest.mark.parametrize("world_id", ("clockwork-library", "rain-harbor"))
def test_unoffered_candidate_method_fails_closed_without_false_physical_result(world_id):
    class UnsupportedMethod(CandidateInteractionInterpreter):
        def understand_candidates(self, request, *, candidates):
            candidate = next(item for item in candidates if item.kind == "door")
            return PlayerInputAssessment(
                InputUnderstandingStatus.ACTION, "open", "open it differently",
                candidate.handle,
            )

    catalog = WorldPackageCatalog(PACKAGES)
    session = start_new_world(
        catalog.package(world_id), trust=HmacPersistenceTrust(b"unsupported-method-key" * 2),
        input_understanding_provider=UnsupportedMethod(),
    )
    try:
        binding = session.runtime.context.player_session
        before_events = session.runtime.context.event_history.get_events()
        before_environment = dict(session.runtime.context.world_state.environment)
        handle = session.player_tasks.submit_input(PlayerInputRequest(
            "unsupported-candidate-method", binding.session_id, world_id, "打开观察到的对象",
        ))
        outcome = session.player_tasks.completion(handle).result(timeout=5)
        assert outcome.outcome_status == "reasoning_unavailable"
        assert session.runtime.context.event_history.get_events() == before_events
        assert session.runtime.context.world_state.environment == before_environment
    finally:
        session.close()


def test_bare_model_method_reproduces_resolution_method_rule_gap_without_event():
    catalog = WorldPackageCatalog(PACKAGES)
    session = start_new_world(
        catalog.package("clockwork-library"),
        trust=HmacPersistenceTrust(b"method-gap-repro-key" * 3),
    )
    engine = session.player_service.resolution_flow.resolution_engine
    installed = engine.assessment_policy
    trace = {}

    class CapturePolicy:
        def supported_attempt_methods(self, kind):
            return installed.supported_attempt_methods(kind)

        def assess(self, attempt, context):
            result = installed.assess(attempt, context)
            trace.update(status=result.status.value, explanation=result.explanation,
                         missing_evidence=result.missing_evidence)
            return result

    engine.assessment_policy = CapturePolicy()
    try:
        binding = session.runtime.context.player_session
        door_ref = next(reference for reference in session.player_service.available_targets()
                        if "reading-door" in reference)
        before = session.runtime.context.event_history.get_events()
        outcome = session.player_service.submit(PlayerActionRequest(
            "bare-method-repro", binding.session_id, "clockwork-library",
            "open the door", "open", door_ref,
        ))
        assert outcome.status == "unresolved"
        assert trace == {
            "status": "insufficient_information",
            "explanation": "method is not covered by an installed causal rule",
            "missing_evidence": ("method_rule",),
        }
        assert session.runtime.context.event_history.get_events() == before
        assert not any(getattr(value, "is_open", False)
                       for value in session.runtime.context.world_state.environment.values())
    finally:
        session.close()


def test_expired_clarification_cannot_resume_a_world_action(monkeypatch):
    catalog = WorldPackageCatalog(PACKAGES)
    clock = [0.0]
    monkeypatch.setattr("cognitive_world.player.service.monotonic", lambda: clock[0])
    session = start_new_world(catalog.package("rain-harbor"),
                              trust=HmacPersistenceTrust(b"expiry-test-key" * 4),
                              input_understanding_provider=CandidateInteractionInterpreter(clarify=True))
    try:
        binding = session.runtime.context.player_session
        before = len(session.runtime.context.event_history.get_events())
        first = session.player_tasks.submit_input(PlayerInputRequest(
            "expired-original", binding.session_id, "rain-harbor", "打开这个",
        ))
        assert session.player_tasks.completion(first).result(timeout=5).outcome_status == "clarification_required"
        clock[0] = 121.0
        second = session.player_tasks.submit_input(PlayerInputRequest(
            "expired-answer", binding.session_id, "rain-harbor", "1",
            clarification_id="expired-original",
        ))
        assert session.player_tasks.completion(second).result(timeout=5).outcome_status == "clarification_expired"
        assert len(session.runtime.context.event_history.get_events()) == before
    finally:
        session.close()


@pytest.mark.parametrize("invalidator", ("generation", "session", "cancel"))
def test_pending_clarification_is_not_reused_after_runtime_or_user_invalidation(invalidator):
    catalog = WorldPackageCatalog(PACKAGES)
    session = start_new_world(catalog.package("rain-harbor"),
                              trust=HmacPersistenceTrust(b"stale-choice-key" * 4),
                              input_understanding_provider=CandidateInteractionInterpreter(clarify=True))
    try:
        binding = session.runtime.context.player_session
        history = session.runtime.context.event_history
        before = len(history.get_events())
        first = session.player_tasks.submit_input(PlayerInputRequest(
            "pending-original", binding.session_id, "rain-harbor", "打开这个",
        ))
        assert session.player_tasks.completion(first).result(timeout=5).outcome_status == "clarification_required"
        if invalidator == "generation":
            session.runtime.freeze_writes()
            session.runtime.unfreeze_writes()
        elif invalidator == "session":
            from dataclasses import replace
            binding = replace(binding, session_id="replacement-player-session")
            session.runtime.context.player_session = binding
        else:
            assert session.player_service.cancel_pending_clarification(
                "pending-original", session_id=binding.session_id,
            )
            assert not session.player_service.cancel_pending_clarification(
                "pending-original", session_id=binding.session_id,
            )
        second = session.player_tasks.submit_input(PlayerInputRequest(
            "pending-answer", binding.session_id, "rain-harbor", "1",
            clarification_id="pending-original",
        ))
        outcome = session.player_tasks.completion(second).result(timeout=5)
        assert outcome.outcome_status != "resolved"
        assert len(history.get_events()) == before
    finally:
        session.close()


def test_explicit_new_request_replaces_pending_clarification_without_reusing_its_intent():
    class SwitchInterpreter(CandidateInteractionInterpreter):
        def understand_candidates(self, request, *, candidates):
            if request.request_id == "new-independent":
                return PlayerInputAssessment(InputUnderstandingStatus.OBSERVE,
                                             "inspect surroundings", "read current facts", None)
            return super().understand_candidates(request, candidates=candidates)

    catalog = WorldPackageCatalog(PACKAGES)
    session = start_new_world(catalog.package("rain-harbor"),
                              trust=HmacPersistenceTrust(b"new-request-key" * 4),
                              input_understanding_provider=SwitchInterpreter(clarify=True))
    try:
        binding = session.runtime.context.player_session
        history = session.runtime.context.event_history
        before = len(history.get_events())
        first = session.player_tasks.submit_input(PlayerInputRequest(
            "old-original", binding.session_id, "rain-harbor", "打开这个",
        ))
        assert session.player_tasks.completion(first).result(timeout=5).outcome_status == "clarification_required"
        second = session.player_tasks.submit_input(PlayerInputRequest(
            "new-independent", binding.session_id, "rain-harbor", "查看周围",
            new_request=True,
        ))
        assert session.player_tasks.completion(second).result(timeout=5).outcome_status == "observed"
        assert session.player_service._pending_clarification is None
        assert len(history.get_events()) == before
    finally:
        session.close()


@pytest.mark.parametrize("answer, expected_delta", (("是", 1), ("不是", 0)))
def test_yes_no_answer_is_only_interpreted_for_an_explicit_yes_no_clarification(answer, expected_delta):
    class ConfirmationInterpreter(CandidateInteractionInterpreter):
        def understand_candidates(self, request, *, candidates):
            return PlayerInputAssessment(
                InputUnderstandingStatus.CLARIFICATION_REQUIRED,
                "open the observed object", "push the door", None,
                ("confirmation",), "确认要尝试这次行动吗？", "yes_no", (), candidates[0].handle,
            )

    catalog = WorldPackageCatalog(PACKAGES)
    session = start_new_world(catalog.package("rain-harbor"),
                              trust=HmacPersistenceTrust(b"confirm-test-key" * 4),
                              input_understanding_provider=ConfirmationInterpreter())
    try:
        binding = session.runtime.context.player_session
        history = session.runtime.context.event_history
        before = len(history.get_events())
        first = session.player_tasks.submit_input(PlayerInputRequest(
            "confirm-original", binding.session_id, "rain-harbor", "尝试操作看到的对象",
        ))
        assert session.player_tasks.completion(first).result(timeout=5).outcome_status == "clarification_required"
        second = session.player_tasks.submit_input(PlayerInputRequest(
            "confirm-answer", binding.session_id, "rain-harbor", answer,
            clarification_id="confirm-original",
        ))
        status = session.player_tasks.completion(second).result(timeout=5).outcome_status
        assert status == ("resolved" if expected_delta else "clarification_cancelled")
        assert len(history.get_events()) == before + expected_delta
    finally:
        session.close()


def test_unlisted_candidate_handle_does_not_enter_resolution():
    class UnknownHandle(CandidateInteractionInterpreter):
        def understand_candidates(self, request, *, candidates):
            return PlayerInputAssessment(InputUnderstandingStatus.ACTION,
                                         "open", "push", "unlisted-handle")

    catalog = WorldPackageCatalog(PACKAGES)
    session = start_new_world(catalog.package("rain-harbor"),
                              trust=HmacPersistenceTrust(b"unknown-test-key" * 4),
                              input_understanding_provider=UnknownHandle())
    try:
        binding = session.runtime.context.player_session
        before = len(session.runtime.context.event_history.get_events())
        handle = session.player_tasks.submit_input(PlayerInputRequest(
            "unknown-handle", binding.session_id, "rain-harbor", "打开未知目标",
        ))
        assert session.player_tasks.completion(handle).result(timeout=5).outcome_status == "reasoning_unavailable"
        assert len(session.runtime.context.event_history.get_events()) == before
    finally:
        session.close()


@pytest.mark.parametrize("world_id", ("clockwork-library", "rain-harbor"))
def test_desktop_read_only_observation_uses_thin_authorized_projection(world_id):
    gateway = DesktopProductGateway(
        PACKAGES, trust_supplier=lambda: HmacPersistenceTrust(b"desktop-observe-key" * 4),
        input_understanding_provider=CandidateInteractionInterpreter(observe=True),
    )
    try:
        gateway.begin_world(world_id)
        assert _wait_for_entry(gateway).state == "ready"
        gateway.read_display()
        request_id = gateway.submit_input("查看周围")
        deadline = monotonic() + 5
        while gateway.input_status(request_id).execution.value in {"accepted", "running"} and monotonic() < deadline:
            sleep(0.01)
        assert gateway.input_status(request_id).outcome_status == "observed"
        entries = gateway.read_display()
        assert entries and all(entry.kind == "observation" for entry in entries)
        assert all("instance:" not in entry.text and "mechanism:" not in entry.text
                   for entry in entries)
        assert gateway.read_display() == ()
    finally:
        gateway.close()


def test_desktop_gateway_continues_the_issued_clarification():
    gateway = DesktopProductGateway(
        PACKAGES, trust_supplier=lambda: HmacPersistenceTrust(b"desktop-clarification-key" * 3),
        input_understanding_provider=CandidateInteractionInterpreter(clarify=True),
    )
    try:
        gateway.begin_world("rain-harbor")
        assert _wait_for_entry(gateway).state == "ready"
        gateway.read_display()
        question_id = gateway.submit_input("Open this object.")
        deadline = monotonic() + 5
        while gateway.input_status(question_id).execution.value in {"accepted", "running"} and monotonic() < deadline:
            sleep(0.01)
        assert gateway.input_status(question_id).outcome_status == "clarification_required"
        assert any(entry.kind == "clarification" and entry.request_id == question_id
                   for entry in gateway.read_display())
        session = gateway._active
        target = session.player_service._request_candidates()[0][1]
        before_events = len(session.runtime.context.event_history.get_events())
        answer_id = gateway.submit_input("1", clarification_id=question_id)
        while gateway.input_status(answer_id).execution.value in {"accepted", "running"} and monotonic() < deadline:
            sleep(0.01)
        assert gateway.input_status(answer_id).outcome_status == "resolved"
        new_events = session.runtime.context.event_history.get_events()[before_events:]
        assert len(new_events) == 1 and new_events[0].has_trusted_source("resolution")
        assert session.runtime.context.world_state.environment[target].is_open
    finally:
        gateway.close()


@pytest.mark.parametrize("world_id", ("clockwork-library", "rain-harbor"))
def test_passage_arrival_reaches_desktop_and_followup_uses_new_location(
    world_id, tmp_path, monkeypatch, caplog,
):
    monkeypatch.setenv("COGNITIVEWORLD_DESKTOP_INPUT_DIAGNOSTICS", "1")
    class TravelThenObserve:
        def understand_candidates(self, request, *, candidates):
            if request.text == "look after travel":
                return PlayerInputAssessment(InputUnderstandingStatus.OBSERVE,
                                             "inspect current surroundings")
            passage = next(item for item in candidates if item.kind == "passage")
            return PlayerInputAssessment(InputUnderstandingStatus.ACTION,
                                         "travel through observed passage",
                                         passage.supported_methods[0], passage.handle)

    gateway = DesktopProductGateway(
        PACKAGES, trust_supplier=lambda: HmacPersistenceTrust(b"arrival-display-key" * 4),
        input_understanding_provider=TravelThenObserve(), saves_root=tmp_path / "saves",
    )
    try:
        gateway.begin_world(world_id)
        assert _wait_for_entry(gateway).state == "ready"
        session = gateway._active
        context = session.runtime.context
        actor = context.player_session.controlled_agent_id
        original_location = context.world_state.locations[actor]
        original_targets = {reference for _, reference in session.player_service._request_candidates()}
        gateway.read_display()
        before_events = context.event_history.get_events()

        request_id = gateway.submit_input("travel through the passage")
        deadline = monotonic() + 5
        while (gateway.input_status(request_id).execution.value in {"accepted", "running"}
               and monotonic() < deadline):
            sleep(0.01)
        assert gateway.input_status(request_id).outcome_status == "resolved"
        arrival_location = context.world_state.locations[actor]
        assert arrival_location != original_location
        assert len(context.event_history.get_events()) == len(before_events) + 1
        event = context.event_history.get_events()[-1]
        assert event.has_trusted_source("resolution")
        observations = context.observation_store.get_by_observer(actor)
        assert any(item.source_event_id == event.id
                   and item.content.predicate == "actor_arrived"
                   and item.content.value == arrival_location for item in observations)
        entries = gateway.read_display()
        assert any(item.kind == "fact" and item.text == "你到达了新的地点。"
                   for item in entries)
        assert all(arrival_location not in item.text and actor not in item.text
                   for item in entries)
        diagnostic = [json.loads(item.getMessage().split("CW_INPUT_DIAGNOSTIC ", 1)[1])
                      for item in caplog.records
                      if "CW_INPUT_DIAGNOSTIC " in item.getMessage()
                      and f'"request_id": "{request_id}"' in item.getMessage()]
        processed = next(item for item in diagnostic if item["stage"] == "event_processing")
        presented = next(item for item in diagnostic if item["stage"] == "presentation")
        terminal = next(item for item in diagnostic if item["stage"] == "gateway_terminal")
        assert processed["effect_type"] == "actor_location_changed"
        assert processed["location_before"] == original_location
        assert processed["location_after"] == arrival_location
        assert processed["location_changed"] is True
        assert processed["event_processed"] is True
        assert processed["arrival_fact_emitted"] is True
        assert processed["arrival_observation_authorized"] is True
        assert presented["arrival_observation_used_by_presentation"] is True
        assert presented["confirmed_message_count"] == 1
        assert terminal["outcome_status"] == "resolved"
        assert not original_targets.intersection(
            reference for _, reference in session.player_service._request_candidates()
        )

        count_after_travel = len(context.event_history.get_events())
        followup_id = gateway.submit_input("look after travel")
        deadline = monotonic() + 5
        while (gateway.input_status(followup_id).execution.value in {"accepted", "running"}
               and monotonic() < deadline):
            sleep(0.01)
        assert gateway.input_status(followup_id).outcome_status == "observed"
        assert len(context.event_history.get_events()) == count_after_travel
        assert any(item.kind == "observation" and item.text == "你到达了新的地点。"
                   for item in gateway.read_display())
    finally:
        gateway.close()


@pytest.mark.parametrize("traversable,suppress_display", ((False, False), (True, True)))
def test_input_diagnostics_separate_location_arrival_observation_and_display(
    traversable, suppress_display, monkeypatch, caplog,
):
    from dataclasses import replace

    class Travel:
        def understand_candidates(self, request, *, candidates):
            passage = next(item for item in candidates if item.kind == "passage")
            return PlayerInputAssessment(InputUnderstandingStatus.ACTION, "traverse passage",
                                         passage.supported_methods[0], passage.handle)

    monkeypatch.setenv("COGNITIVEWORLD_DESKTOP_INPUT_DIAGNOSTICS", "1")
    package = WorldPackageCatalog(PACKAGES).package("rain-harbor")
    locations = list(package.proposal.locations)
    source = locations[0]
    locations[0] = replace(source, mechanisms=tuple(
        replace(item, operable=traversable) if item.kind == "passage" else item
        for item in source.mechanisms
    ))
    package = replace(package, proposal=replace(package.proposal, locations=tuple(locations)))
    session = start_new_world(package, trust=HmacPersistenceTrust(b"diagnostic-route-key" * 4),
                              input_understanding_provider=Travel())
    try:
        if suppress_display:
            monkeypatch.setattr(session.player_service.presentation.visibility_filter,
                                "filter", lambda *args: ())
        context = session.runtime.context
        binding = context.player_session
        actor = binding.controlled_agent_id
        before_location = context.world_state.locations[actor]
        before_events = len(context.event_history.get_events())
        task = session.player_tasks.submit_input(PlayerInputRequest(
            "diagnostic-route", binding.session_id, "rain-harbor", "travel",
        ))
        outcome = session.player_tasks.completion(task).result(timeout=5)
        after_location = context.world_state.locations[actor]
        records = [json.loads(item.getMessage().split("CW_INPUT_DIAGNOSTIC ", 1)[1])
                   for item in caplog.records
                   if "CW_INPUT_DIAGNOSTIC " in item.getMessage()
                   and '"request_id": "diagnostic-route"' in item.getMessage()]
        processed = next(item for item in records if item["stage"] == "event_processing")
        presented = next(item for item in records if item["stage"] == "presentation")
        assert len(context.event_history.get_events()) == before_events + 1
        assert processed["location_before"] == before_location
        assert processed["location_after"] == after_location
        assert processed["location_changed"] is traversable
        assert processed["arrival_fact_emitted"] is traversable
        assert processed["arrival_observation_authorized"] is traversable
        assert presented["arrival_observation_used_by_presentation"] is False
        assert presented["confirmed_message_count"] == 0
        assert outcome.outcome_status == (
            "executed_no_observable_change" if traversable else "failed"
        )
    finally:
        session.close()


def test_arrival_observes_only_destination_mechanisms_and_allows_followup_action():
    from dataclasses import replace
    from cognitive_world.content.models import LocationTemplate, MechanismTemplate

    class TravelThenOpen:
        def understand_candidates(self, request, *, candidates):
            kind = "passage" if request.text == "travel" else "door"
            selected = next(item for item in candidates if item.kind == kind)
            return PlayerInputAssessment(InputUnderstandingStatus.ACTION,
                                         request.text, selected.supported_methods[0], selected.handle)

    package = WorldPackageCatalog(PACKAGES).package("rain-harbor")
    locations = list(package.proposal.locations)
    locations[1] = replace(locations[1], mechanisms=(MechanismTemplate("arrival-door", "door"),))
    locations.append(LocationTemplate("hidden-room", "Unreachable room", (
        MechanismTemplate("hidden-door", "door"),
    )))
    scenario = package.proposal.scenarios[0]
    scenario = replace(scenario, locations=scenario.locations + (("hidden", "hidden-room"),))
    package = replace(package, proposal=replace(
        package.proposal, locations=tuple(locations), scenarios=(scenario,),
    ))
    session = start_new_world(package, trust=HmacPersistenceTrust(b"arrival-mechanism-key" * 4),
                              input_understanding_provider=TravelThenOpen())
    try:
        context = session.runtime.context
        binding = context.player_session
        actor = binding.controlled_agent_id
        before_location = context.world_state.locations[actor]
        before_events = context.event_history.get_events()
        assert all(candidate.kind != "door" or "arrival-door" not in reference
                   for candidate, reference in session.player_service._request_candidates())

        travel = session.player_tasks.submit_input(PlayerInputRequest(
            "travel-with-destination", binding.session_id, "rain-harbor", "travel",
        ))
        assert session.player_tasks.completion(travel).result(timeout=5).outcome_status == "resolved"
        destination = context.world_state.locations[actor]
        assert destination != before_location
        new_events = context.event_history.get_events()[len(before_events):]
        arrivals = [event for event in new_events if any(
            isinstance(change, dict) and change.get("effect_type") == "actor_location_changed"
            for change in event.changes)]
        assert len(arrivals) == 1 and arrivals[0].has_trusted_source("resolution")
        observations = context.observation_store.get_by_observer(actor)
        assert any(item.source_event_id == arrivals[0].id
                   and item.content.predicate == "actor_arrived"
                   and item.content.value == destination for item in observations)
        assert any(item.content.predicate == "door_open"
                   and "arrival-door" in (item.content.subject_ref or "")
                   and item.content.location_id == destination for item in observations)
        assert not any("hidden-door" in (item.content.subject_ref or "") for item in observations)
        assert any("arrival-door" in reference for _, reference in session.player_service._request_candidates())
        assert not any("hidden-door" in reference for _, reference in session.player_service._request_candidates())
        assert any(item.content == "你到达了新的地点。"
                   for item in session.output.messages_for(binding.player_id))

        event_count_after_travel = len(context.event_history.get_events())
        replay = session.player_service.retry_input_presentation(PlayerInputRequest(
            "travel-with-destination", binding.session_id, "rain-harbor", "travel",
        ))
        assert replay.status == "resolved"
        assert len(context.event_history.get_events()) == event_count_after_travel

        before_followup = len(context.event_history.get_events())
        followup = session.player_tasks.submit_input(PlayerInputRequest(
            "open-arrival-door", binding.session_id, "rain-harbor", "open door",
        ))
        assert session.player_tasks.completion(followup).result(timeout=5).outcome_status == "resolved"
        target = next(reference for _, reference in session.player_service._request_candidates()
                      if "arrival-door" in reference)
        assert context.world_state.environment[target].is_open
        assert len(context.event_history.get_events()) == before_followup + 1
    finally:
        session.close()


def test_read_only_observation_gateway_rejects_unissued_result():
    from cognitive_world.presentation.contracts import ReadOnlyObservationResult

    catalog = WorldPackageCatalog(PACKAGES)
    session = start_new_world(catalog.package("rain-harbor"),
                              trust=HmacPersistenceTrust(b"observation-receipt-key" * 4),
                              input_understanding_provider=CandidateInteractionInterpreter(observe=True))
    try:
        binding = session.runtime.context.player_session
        handle = session.player_tasks.submit_input(PlayerInputRequest(
            "issued-observation", binding.session_id, "rain-harbor", "查看周围",
        ))
        assert session.player_tasks.completion(handle).result(timeout=5).outcome_status == "observed"
        issued = session.output.observation_results_for(binding.player_id)[0]
        with pytest.raises(PermissionError, match="validated result"):
            session.output.send_observation_result(
                ReadOnlyObservationResult("forged-observation", issued.batch),
            )
        assert len(session.output.observation_results_for(binding.player_id)) == 1
    finally:
        session.close()


@pytest.mark.parametrize("world_id", ("clockwork-library", "rain-harbor"))
def test_distinct_packages_start_and_submit_through_real_async_event_chain(world_id):
    catalog = WorldPackageCatalog(PACKAGES)
    assert catalog.package(world_id).projection().characters == ()
    assert catalog.package(world_id).projection().locations == ()
    session = start_new_world(
        catalog.package(world_id), trust=HmacPersistenceTrust(b"host-test-key" * 4),
        input_understanding_provider=GroundedActionInterpreter(),
    )
    try:
        runtime = session.runtime
        initial_events = len(runtime.context.event_history.get_events())
        binding = runtime.context.player_session
        request = PlayerInputRequest(
            "player-raw-input", binding.session_id, world_id, "Please open the door.",
        )
        handle = session.player_tasks.submit_input(request)
        assert session.player_tasks.submit_input(request) == handle
        result = session.player_tasks.completion(handle).result(timeout=5)
        assert result.execution is PlayerTaskExecutionState.COMPLETED
        assert result.outcome_status == "resolved"
        events = runtime.context.event_history.get_events()
        assert len(events) == initial_events + 1
        assert events[-1].has_trusted_source("resolution")
        assert session.output.messages_for(binding.player_id)
        assert session.player_tasks.completion(handle).result(timeout=5) == result
        assert len(runtime.context.event_history.get_events()) == len(events)
    finally:
        session.close()


def test_product_gateway_exposes_only_bounded_status_and_authorized_display():
    gateway = DesktopProductGateway(
        PACKAGES, trust_supplier=lambda: HmacPersistenceTrust(b"product-gateway-test-key" * 2),
        input_understanding_provider=GroundedActionInterpreter(),
    )
    try:
        gateway.begin_world("rain-harbor")
        deadline = monotonic() + 5
        while gateway.entry_status().state == "starting" and monotonic() < deadline:
            sleep(0.01)
        assert gateway.entry_status().state == "ready"
        request_id = gateway.submit_input("Please open the observed door.")
        while gateway.input_status(request_id).execution.value in {"accepted", "running"} and monotonic() < deadline:
            sleep(0.01)
        status = gateway.input_status(request_id)
        assert status.execution is PlayerTaskExecutionState.COMPLETED
        assert status.outcome_status == "resolved"
        display = gateway.read_display()
        assert display and all(item.kind == "fact" for item in display)
        assert gateway.read_display() == ()
        assert all(type(item.text) is str for item in display)
    finally:
        gateway.close()


def _wait_for_entry(gateway):
    deadline = monotonic() + 5
    status = gateway.entry_status()
    while status.state == "starting" and monotonic() < deadline:
        sleep(0.01)
        status = gateway.entry_status()
    return status


def test_failed_world_entry_leaves_no_active_session_and_allows_retry():
    attempts = 0

    def trust_supplier():
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise PermissionError("test trust unavailable")
        return HmacPersistenceTrust(b"retry-test-key" * 4)

    gateway = DesktopProductGateway(PACKAGES, trust_supplier=trust_supplier)
    try:
        gateway.begin_world("clockwork-library")
        assert _wait_for_entry(gateway).state == "failed"
        assert gateway.available_targets("clockwork-library") == ()
        gateway.begin_world("rain-harbor")
        assert _wait_for_entry(gateway).state == "ready"
    finally:
        gateway.close()


def test_partial_save_directory_listing_fails_without_writing_and_save_can_retry(tmp_path):
    world_id = "clockwork-library"
    world_saves = tmp_path / "saves" / world_id
    world_saves.mkdir(parents=True)
    marker = world_saves / "existing-resource"
    marker.write_bytes(b"preserve")
    calls = 0

    def trust_supplier():
        nonlocal calls
        calls += 1
        return HmacPersistenceTrust(b"partial-directory-test-key" * 4)

    gateway = DesktopProductGateway(PACKAGES, trust_supplier=trust_supplier,
                                    saves_root=tmp_path / "saves")
    try:
        with pytest.raises(FileNotFoundError, match="save catalog is unavailable"):
            gateway.list_saves(world_id)
        assert calls == 0
        assert tuple(world_saves.iterdir()) == (marker,)
        assert marker.read_bytes() == b"preserve"
        gateway.begin_world(world_id)
        assert _wait_for_entry(gateway).state == "ready"
        gateway.begin_save()
        deadline = monotonic() + 5
        while gateway.save_status().state == "saving" and monotonic() < deadline:
            sleep(0.01)
        assert gateway.save_status().state == "saved"
        assert len(gateway.list_saves(world_id)) == 1
        assert marker.read_bytes() == b"preserve"
    finally:
        gateway.close()


def test_save_permission_failure_preserves_active_world_and_retry_succeeds(tmp_path):
    world_id = "rain-harbor"
    gateway = DesktopProductGateway(
        PACKAGES,
        trust_supplier=lambda: HmacPersistenceTrust(b"permission-retry-test-key" * 4),
        saves_root=tmp_path / "saves",
    )
    try:
        gateway.begin_world(world_id)
        assert _wait_for_entry(gateway).state == "ready"
        active = gateway._active
        original = gateway._save_manager

        def denied(*args, **kwargs):
            raise PermissionError("controlled save directory denial")

        gateway._save_manager = denied
        gateway.begin_save()
        deadline = monotonic() + 5
        while gateway.save_status().state == "saving" and monotonic() < deadline:
            sleep(0.01)
        assert gateway.save_status().state == "failed"
        assert gateway.save_status().error_code == "PermissionError"
        assert gateway._active is active
        assert not active.runtime.write_fence.frozen
        gateway._save_manager = original
        gateway.begin_save()
        while gateway.save_status().state == "saving" and monotonic() < deadline:
            sleep(0.01)
        assert gateway.save_status().state == "saved"
        assert len(gateway.list_saves(world_id)) == 1
    finally:
        gateway.close()


def test_late_old_world_result_cannot_commit_after_world_switch():
    started, release, returned = Event(), Event(), Event()

    class DelayedInterpreter(GroundedActionInterpreter):
        def understand(self, request, *, authorized_targets):
            started.set()
            assert release.wait(5)
            result = super().understand(request, authorized_targets=authorized_targets)
            returned.set()
            return result

    gateway = DesktopProductGateway(
        PACKAGES, trust_supplier=lambda: HmacPersistenceTrust(b"switch-test-key" * 4),
        input_understanding_provider=DelayedInterpreter(),
    )
    try:
        gateway.begin_world("clockwork-library")
        assert _wait_for_entry(gateway).state == "ready"
        old_session = gateway._active
        initial_count = len(old_session.runtime.context.event_history.get_events())
        gateway.submit_input("Open the observed door.")
        assert started.wait(5)
        gateway.leave_world()
        assert old_session.runtime.write_fence.frozen
        gateway.begin_world("rain-harbor")
        assert _wait_for_entry(gateway).state == "ready"
        new_session = gateway._active
        new_count = len(new_session.runtime.context.event_history.get_events())
        release.set()
        assert returned.wait(5)
        assert len(old_session.runtime.context.event_history.get_events()) == initial_count
        assert len(new_session.runtime.context.event_history.get_events()) == new_count
        assert new_session.runtime.write_fence.session_id != old_session.runtime.write_fence.session_id
    finally:
        release.set()
        gateway.close()


@pytest.mark.parametrize("world_id", ("clockwork-library", "rain-harbor"))
def test_fresh_world_checkpoint_is_signed_and_load_verified(world_id, tmp_path):
    trust = HmacPersistenceTrust(b"save-checkpoint-test-key" * 4)
    session = start_new_world(WorldPackageCatalog(PACKAGES).package(world_id), trust=trust)
    try:
        manager = SaveManager(tmp_path / world_id, trust=trust, codec=scenario_snapshot_codec())
        metadata = manager.create_manual_save(
            name="checkpoint", runtime=session.runtime, cognition=session.cognition,
            memory_store=session.memory_store, agent_contexts=session.agent_contexts,
        )
        verified = manager.load_verified(metadata.save_id, timeline_id=metadata.timeline_id)
        assert verified.metadata.save_id == metadata.save_id
        assert verified.bundle_manifest.timeline_id == session.runtime.context.event_history.timeline_id
    finally:
        session.close()


@pytest.mark.parametrize("world_id", ("clockwork-library", "rain-harbor"))
def test_saved_world_cold_resumes_original_history_and_continues_action(world_id, tmp_path):
    trust = HmacPersistenceTrust(b"cold-desktop-test-key" * 4)
    package = WorldPackageCatalog(PACKAGES).package(world_id)
    manager = SaveManager(tmp_path / world_id, trust=trust, codec=scenario_snapshot_codec())
    first = start_new_world(package, trust=trust,
                            input_understanding_provider=GroundedActionInterpreter())
    initial_ids = tuple(event.id for event in first.runtime.context.event_history.get_events())
    try:
        saved = manager.create_manual_save(
            runtime=first.runtime, cognition=first.cognition,
            memory_store=first.memory_store, agent_contexts=first.agent_contexts,
        )
    finally:
        first.close()
    reopened = SaveManager(manager.root, trust=trust, codec=scenario_snapshot_codec())
    resumed = resume_saved_world(
        package, manager=reopened, save_id=saved.save_id,
        timeline_id=saved.timeline_id, trust=trust,
        input_understanding_provider=GroundedActionInterpreter(),
    )
    try:
        assert resumed.runtime.context.event_history.timeline_id == saved.timeline_id
        restored_events = resumed.runtime.context.event_history.get_events()
        assert tuple(event.id for event in restored_events[:len(initial_ids)]) == initial_ids
        assert all(event.type == "environment_state_observed" for event in restored_events[len(initial_ids):])
        assert resumed.output.messages_for(resumed.runtime.context.player_session.player_id)
        assert resumed.runtime.write_fence.session_id != saved.runtime_session_id
        binding = resumed.runtime.context.player_session
        request = PlayerInputRequest("after-restart", binding.session_id, world_id,
                                     "Open the observed door.")
        handle = resumed.player_tasks.submit_input(request)
        result = resumed.player_tasks.completion(handle).result(timeout=5)
        assert result.execution is PlayerTaskExecutionState.COMPLETED
        assert len(resumed.runtime.context.event_history.get_events()) == len(restored_events) + 1
    finally:
        resumed.close()


@pytest.mark.parametrize("world_id", ("clockwork-library", "rain-harbor"))
def test_desktop_gateway_lists_signed_save_after_reopen_and_restores(world_id, tmp_path):
    saves_root = tmp_path / "saves"
    def trust_supplier():
        return HmacPersistenceTrust(b"gateway-cold-test-key" * 4)

    first = DesktopProductGateway(
        PACKAGES, trust_supplier=trust_supplier,
        input_understanding_provider=GroundedActionInterpreter(),
        saves_root=saves_root,
    )
    try:
        first.begin_world(world_id)
        assert _wait_for_entry(first).state == "ready"
        first.begin_save()
        deadline = monotonic() + 5
        while first.save_status().state == "saving" and monotonic() < deadline:
            sleep(0.01)
        saved_status = first.save_status()
        assert saved_status.state == "saved"
        before_listing = {path.relative_to(saves_root): path.read_bytes()
                          for path in saves_root.rglob("*") if path.is_file()}
        slots = first.list_saves(world_id)
        assert {path.relative_to(saves_root): path.read_bytes()
                for path in saves_root.rglob("*") if path.is_file()} == before_listing
        assert len(slots) == 1 and slots[0].id == saved_status.save_id
        assert slots[0].name == "手动存档"
        assert slots[0].timeline_count == 1
        assert not hasattr(slots[0], "timeline_ids")
        first.leave_world()
    finally:
        first.close()

    reopened = DesktopProductGateway(
        PACKAGES, trust_supplier=trust_supplier,
        input_understanding_provider=GroundedActionInterpreter(),
        saves_root=saves_root,
    )
    try:
        reopened.begin_restore(world_id, saved_status.save_id)
        assert _wait_for_entry(reopened).state == "ready"
        assert reopened.read_display()
        request_id = reopened.submit_input("Open the observed door.")
        deadline = monotonic() + 5
        while reopened.input_status(request_id).execution.value in {"accepted", "running"} and monotonic() < deadline:
            sleep(0.01)
        assert reopened.input_status(request_id).execution is PlayerTaskExecutionState.COMPLETED
    finally:
        reopened.close()


def test_product_listing_rejects_tampered_candidate_without_changing_storage(tmp_path):
    world_id = "clockwork-library"
    saves_root = tmp_path / "saves"
    trust = HmacPersistenceTrust(b"listing-tamper-test-key" * 4)
    gateway = DesktopProductGateway(
        PACKAGES, trust_supplier=lambda: trust, saves_root=saves_root,
    )
    try:
        gateway.begin_world(world_id)
        assert _wait_for_entry(gateway).state == "ready"
        gateway.begin_save()
        deadline = monotonic() + 5
        while gateway.save_status().state == "saving" and monotonic() < deadline:
            sleep(0.01)
        assert gateway.save_status().state == "saved"
        manager = SaveManager(saves_root / world_id, trust=trust,
                              codec=scenario_snapshot_codec())
        saved = manager.list_saves()[0]
        verified = manager.load_verified(saved.save_id, timeline_id=saved.timeline_id)
        world_resource = "sha256:" + sha256_hex(verified.world_checkpoint)
        blob = saves_root / world_id / "resources" / f"{world_resource.removeprefix('sha256:')}.blob"
        blob.write_bytes(blob.read_bytes() + b"tampered")
        before_listing = {path.relative_to(saves_root): path.read_bytes()
                          for path in saves_root.rglob("*") if path.is_file()}
        with pytest.raises(PermissionError, match="digest mismatch"):
            gateway.list_saves(world_id)
        assert {path.relative_to(saves_root): path.read_bytes()
                for path in saves_root.rglob("*") if path.is_file()} == before_listing
        assert gateway._active is not None
    finally:
        gateway.close()


def test_cold_resume_rejects_tampered_resource_without_publishing(tmp_path):
    trust = HmacPersistenceTrust(b"tampered-product-key" * 4)
    package = WorldPackageCatalog(PACKAGES).package("clockwork-library")
    manager = SaveManager(tmp_path / "saves", trust=trust, codec=scenario_snapshot_codec())
    session = start_new_world(package, trust=trust)
    try:
        saved = manager.create_manual_save(runtime=session.runtime,
            cognition=session.cognition, memory_store=session.memory_store,
            agent_contexts=session.agent_contexts)
        active = session.runtime
        verified = manager.load_verified(saved.save_id, timeline_id=saved.timeline_id)
        world_ref = "sha256:" + sha256_hex(verified.world_checkpoint)
        assert world_ref in saved.resource_ids
        blob = manager._blob_path(world_ref)
        blob.write_bytes(blob.read_bytes() + b"tampered")
        with pytest.raises(PermissionError, match="digest mismatch"):
            manager.stage_cold_resume(saved.save_id, timeline_id=saved.timeline_id,
                assembler=object(), dependencies=object())
        assert session.runtime is active and not active.write_fence.frozen
    finally:
        session.close()


def test_scenario_checkpoint_rejects_unregistered_record_and_unsupported_version(tmp_path):
    trust = HmacPersistenceTrust(b"codec-rejection-key" * 4)
    codec = scenario_snapshot_codec()
    with pytest.raises(ValueError, match="unregistered persisted record"):
        codec.loads(b'{"$record":"unknown.module:Untrusted","fields":{}}')
    session = start_new_world(
        WorldPackageCatalog(PACKAGES).package("rain-harbor"), trust=trust,
    )
    try:
        checkpoint = session.runtime.context.world_state.export_persisted_snapshot(
            event_history=session.runtime.context.event_history,
            simulation_tick=session.runtime.context.clock.current_time,
            timeline_id=session.runtime.context.event_history.timeline_id,
            trust=trust, codec=codec,
        )
        envelope = json.loads(checkpoint.decode("utf-8"))
        envelope["version"] = 999
        with pytest.raises(ValueError, match="unsupported WorldState checkpoint version"):
            WorldState.restore_persisted_snapshot(
                json.dumps(envelope).encode("utf-8"), trust=trust, codec=codec,
            )
    finally:
        session.close()


def test_cold_resume_refuses_wrong_trust_and_other_world_save(tmp_path):
    package = WorldPackageCatalog(PACKAGES).package("clockwork-library")
    good = HmacPersistenceTrust(b"trusted-product-key" * 4)
    manager = SaveManager(tmp_path / package.world_id, trust=good,
                          codec=scenario_snapshot_codec())
    session = start_new_world(package, trust=good)
    try:
        saved = manager.create_manual_save(runtime=session.runtime,
            cognition=session.cognition, memory_store=session.memory_store,
            agent_contexts=session.agent_contexts)
    finally:
        session.close()
    wrong = HmacPersistenceTrust(b"different-product-key" * 4)
    with pytest.raises(PermissionError, match="catalog signature"):
        SaveManager(manager.root, trust=wrong, codec=scenario_snapshot_codec())
    other = SaveManager(tmp_path / "rain-harbor", trust=good,
                        codec=scenario_snapshot_codec())
    with pytest.raises(KeyError):
        other.load_verified(saved.save_id, timeline_id=saved.timeline_id)


def test_pending_old_input_cannot_commit_after_cold_resume(tmp_path):
    started, release, returned = Event(), Event(), Event()

    class DelayedInterpreter(GroundedActionInterpreter):
        def understand(self, request, *, authorized_targets):
            started.set()
            assert release.wait(5)
            result = super().understand(request, authorized_targets=authorized_targets)
            returned.set()
            return result

    def trust_supplier():
        return HmacPersistenceTrust(b"old-task-cold-resume-key" * 4)

    root = tmp_path / "saves"
    gateway = DesktopProductGateway(
        PACKAGES, trust_supplier=trust_supplier,
        input_understanding_provider=DelayedInterpreter(), saves_root=root,
    )
    try:
        gateway.begin_world("clockwork-library")
        assert _wait_for_entry(gateway).state == "ready"
        gateway.begin_save()
        deadline = monotonic() + 5
        while gateway.save_status().state == "saving" and monotonic() < deadline:
            sleep(0.01)
        assert gateway.save_status().state == "saved"
        save_id = gateway.save_status().save_id
        old_runtime = gateway._active.runtime
        old_ids = tuple(event.id for event in old_runtime.context.event_history.get_events())
        gateway.submit_input("Open the observed door.")
        assert started.wait(5)
        gateway.leave_world()
        assert old_runtime.write_fence.frozen
        gateway.begin_restore("clockwork-library", save_id)
        assert _wait_for_entry(gateway).state == "ready"
        new_runtime = gateway._active.runtime
        new_ids = tuple(event.id for event in new_runtime.context.event_history.get_events())
        release.set()
        assert returned.wait(5)
        assert tuple(event.id for event in old_runtime.context.event_history.get_events()) == old_ids
        assert tuple(event.id for event in new_runtime.context.event_history.get_events()) == new_ids
        assert new_runtime.write_fence.session_id != old_runtime.write_fence.session_id
    finally:
        release.set()
        gateway.close()


def test_failed_desktop_restore_does_not_publish_and_healthy_retry_succeeds(tmp_path):
    def trust_supplier():
        return HmacPersistenceTrust(b"restore-retry-test-key" * 4)

    root = tmp_path / "saves"
    creator = DesktopProductGateway(PACKAGES, trust_supplier=trust_supplier,
                                    saves_root=root)
    try:
        creator.begin_world("rain-harbor")
        assert _wait_for_entry(creator).state == "ready"
        creator.begin_save()
        deadline = monotonic() + 5
        while creator.save_status().state == "saving" and monotonic() < deadline:
            sleep(0.01)
        assert creator.save_status().state == "saved"
        save_id = creator.save_status().save_id
    finally:
        creator.close()

    manager = SaveManager(root / "rain-harbor", trust=trust_supplier(),
                          codec=scenario_snapshot_codec())
    slot = next(item for item in manager.list_saves() if item.save_id == save_id)
    verified = manager.load_verified(save_id, timeline_id=slot.timeline_id)
    resource = manager._blob_path("sha256:" + sha256_hex(verified.world_checkpoint))
    original = resource.read_bytes()
    resource.write_bytes(original + b"tampered")

    gateway = DesktopProductGateway(PACKAGES, trust_supplier=trust_supplier,
                                    saves_root=root)
    try:
        gateway.begin_restore("rain-harbor", save_id)
        assert _wait_for_entry(gateway).state == "failed"
        assert gateway._active is None
        assert gateway.available_targets("rain-harbor") == ()
        resource.write_bytes(original)
        gateway.begin_restore("rain-harbor", save_id)
        assert _wait_for_entry(gateway).state == "ready"
        assert gateway._active.runtime.context.event_history.timeline_id == slot.timeline_id
    finally:
        gateway.close()
