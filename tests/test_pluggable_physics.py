"""Real JSON admission, signed installation, Resolution, commit and restore."""

from copy import deepcopy
from dataclasses import replace
import json
import pytest
from test_runtime_content_commit_boundary import _signed_runtime
from cognitive_world.content.llm import parse_generation_proposal
from cognitive_world.core.physical import (
    PhysicalPropertyDefinition,
    PhysicalValue,
    PhysicalStateSet,
    PhysicalRelation,
    validate_physical_world,
)
from cognitive_world.core.persistence import PersistedValueCodec
from cognitive_world.decision import ActionPipeline, ActionProposal
from cognitive_world.physics.engine import BooleanTransitionEngine, PhysicsOutcome
from cognitive_world.physics.adapter import StateTransitionResolutionEngine
from cognitive_world.resolution.action_flow import ActionResolutionFlow


def document():
    from pathlib import Path

    return json.loads(
        (
            Path(__file__).resolve().parents[1] / "examples/data/physical_assembly.json"
        ).read_text(encoding="utf-8")
    )


class Host:
    def __init__(self, data=None, inputs=None, trust=None):
        self.runtime, self.cognition, self.memory, self.installer = _signed_runtime(
            trust, inputs
        )
        self.trust = self.runtime.event_processor.persistence_trust
        if inputs is None:
            with self.runtime.write_fence.operation():
                self.installer.install_proposal(
                    parse_generation_proposal(json.dumps(data or document())),
                    template_id="visit",
                    instance_id="one",
                    world_id="physical",
                    source_id="authored-json",
                )
        self.owner = "physical:one:agent:worker"
        self.target = "physical:one:object:handle"
        self.panel = "physical:one:object:panel"

    def prepare(self, engine=None, operation="operate"):
        rt = self.runtime
        proposal = ActionProposal(
            "physical:" + str(len(rt.context.event_history.get_events())),
            self.owner,
            "operate",
            ["object:" + self.target],
            {"method": "manipulate the control", "physical_operation": operation},
        )
        attempt = ActionPipeline().create_attempt(proposal)
        flow = ActionResolutionFlow(
            StateTransitionResolutionEngine(
                rt.context.world_state, rt.context.event_history, engine
            ),
            world_state=rt.context.world_state,
            event_history=rt.context.event_history,
        )
        return flow.execute_with_result(
            attempt, simulation_tick=rt.context.clock.capture()
        )

    def run(self, engine=None, operation="operate"):
        with self.runtime.write_fence.operation():
            result, event = self.prepare(engine, operation)
            if event is not None:
                self.runtime.event_processor.dispatch_with_evidence(event)
        return result, event

    def value(self):
        return (
            self.runtime.context.world_state.get_entity(self.panel)
            .state["physical"]
            .get("open")
            .value
        )


def test_json_installation_and_formal_physical_commit():
    host = Host()
    assert not host.value()
    history = host.runtime.context.event_history
    assert len(history.get_events()) == 2
    before = host.runtime.context.world_state.entities
    with host.runtime.write_fence.operation():
        result, event = host.prepare()
        assert result.success and not host.value()
        host.runtime.event_processor.dispatch_with_evidence(event)
    assert host.value() is True and len(history.get_events()) == 3
    assert before[host.target] == host.runtime.context.world_state.get_entity(
        host.target
    )
    assert history.get_processing_evidence(event.id).has_trusted_source(event)
    assert (
        host.runtime.context.world_state.read_state_slot(
            __import__(
                "cognitive_world.core.world_state", fromlist=["WorldStateSlot"]
            ).WorldStateSlot(
                "entities", host.panel, ("state", "physical", "properties")
            ),
            event_history=history,
        ).source_event_id
        == event.id
    )


@pytest.mark.parametrize("change", ["property", "relation"])
def test_json_property_or_relation_changes_formal_outcome(change):
    data = document()
    if change == "property":
        data["objects"][1]["physical_state"]["properties"][0]["value"] = False
    else:
        data["scenarios"][0]["physical_relations"].pop()
    host = Host(data)
    before = host.runtime.context.world_state.entities
    result, event = host.run()
    assert result.success is False and event is not None
    assert not host.value() and host.runtime.context.world_state.entities == before
    assert len(host.runtime.context.event_history.get_events()) == 3


def test_interchangeable_engine_uses_same_domain_protocol():
    class OtherEngine:
        def evaluate(self, request, context):
            return BooleanTransitionEngine().evaluate(request, context)

    host = Host()
    result, event = host.run(OtherEngine())
    assert result.success and host.value() and event.has_trusted_source("resolution")


@pytest.mark.parametrize(
    "change", ["unit", "value", "version", "field", "endpoint", "cycle", "operation"]
)
def test_invalid_content_or_unsupported_request_cannot_succeed(change):
    data = document()
    if change == "unit":
        data["objects"][0]["physical_state"]["properties"][0]["definition"][
            "unit"
        ] = "kg"
    elif change == "value":
        data["objects"][0]["physical_state"]["properties"][0]["value"] = 1
    elif change == "version":
        data["objects"][0]["physical_state"]["version"] = 99
    elif change == "field":
        data["objects"][0]["physical_state"]["executable"] = "forbidden"
    elif change == "endpoint":
        data["scenarios"][0]["physical_relations"][0]["target"] = "object:missing"
    elif change == "cycle":
        data["scenarios"][0]["physical_relations"][2] = {
            "source": "object:panel",
            "target": "object:handle",
            "kinds": ["part_of"],
        }
    else:
        host = Host()
        before = len(host.runtime.context.event_history.get_events())
        result, event = host.run(operation="unsupported")
        assert not result.confirmed and event is None and not host.value()
        assert len(host.runtime.context.event_history.get_events()) == before
        return
    with pytest.raises((ValueError, TypeError)):
        Host(data)


def test_physical_codec_closed_and_definition_bounds():
    definition = PhysicalPropertyDefinition(1, "mass", "number", "kg", 0, 100)
    state = PhysicalStateSet(1, "x", (PhysicalValue(definition, 2),))
    codec = PersistedValueCodec()
    assert codec.loads(codec.dumps(state)) == state
    with pytest.raises(ValueError):
        PhysicalValue(definition, -1)
    raw = json.loads(codec.dumps(state))
    raw["fields"]["version"] = 99
    with pytest.raises(ValueError):
        codec.loads(json.dumps(raw).encode())
    raw = json.loads(codec.dumps(state))
    raw["fields"]["unapproved"] = True
    with pytest.raises(ValueError):
        codec.loads(json.dumps(raw).encode())
    with pytest.raises(ValueError):
        codec.loads(b'{"$record":"unknown:PhysicalState","fields":{}}')


def test_signed_checkpoint_restore_and_branch_isolation(tmp_path, monkeypatch):
    from cognitive_world.runtime.save_manager import SaveManager
    from cognitive_world.runtime.recovery import ActiveRuntimeSlot, RestoreCoordinator
    from cognitive_world.content.persistence import scenario_snapshot_codec
    from test_runtime_reconstruction import _dependency_manifest
    import cognitive_world.event.processor as processor_module

    host = Host()
    runtime = host.runtime
    manager = SaveManager(
        tmp_path / "saves", trust=host.trust, codec=scenario_snapshot_codec()
    )
    contexts = tuple(
        runtime.cognition_context_provider(a)
        for a in runtime.context.agent_registry.all_agents()
    )
    saved = manager.create_manual_save(
        runtime=runtime,
        cognition=host.cognition,
        memory_store=host.memory,
        agent_contexts=contexts,
    )
    records = [
        runtime.context.event_history.get_persistence_record(e.id).to_json_record()
        for e in runtime.context.event_history.get_events()
    ]

    class Assembler:
        def assemble(self, inputs):
            self.host = Host(inputs=inputs, trust=host.trust)
            return self.host.runtime

    sign = processor_module.make_persisted_event_record

    def forbid(*args, **kwargs):
        pytest.fail("historical evidence must not be reissued")

    monkeypatch.setattr(processor_module, "make_persisted_event_record", forbid)
    assembler = Assembler()
    staged = manager.stage_restore(
        saved.save_id,
        timeline_id=saved.timeline_id,
        active_runtime=runtime,
        assembler=assembler,
        dependencies=_dependency_manifest(),
        new_timeline_id="physical-child",
    )
    child = RestoreCoordinator(ActiveRuntimeSlot(runtime)).activate(staged)
    assert not assembler.host.value()
    assert [
        child.context.event_history.get_persistence_record(e.id).to_json_record()
        for e in child.context.event_history.get_events()
    ] == records
    assert (
        child.context.world_state.relationships
        == runtime.context.world_state.relationships
    )
    monkeypatch.setattr(processor_module, "make_persisted_event_record", sign)
    assert assembler.host.run()[0].success and assembler.host.value()
    # An independent branch from the same published checkpoint retains its own state.
    from cognitive_world.runtime.cold_restore import ColdRuntimePublisher

    parent_assembler = Assembler()
    parent_slot = ColdRuntimePublisher().activate(
        manager.stage_cold_resume(
            saved.save_id,
            timeline_id=saved.timeline_id,
            assembler=parent_assembler,
            dependencies=_dependency_manifest(),
        )
    )
    parent = parent_assembler.host.runtime
    sibling_assembler = Assembler()
    staged = manager.stage_restore(
        saved.save_id,
        timeline_id=saved.timeline_id,
        active_runtime=parent,
        assembler=sibling_assembler,
        dependencies=_dependency_manifest(),
        new_timeline_id="physical-sibling",
    )
    sibling = RestoreCoordinator(parent_slot).activate(staged)
    assert not sibling_assembler.host.value() and assembler.host.value()
    assert len(sibling.context.event_history.get_events()) == 2
    # A checkpoint after the transition retains the committed value, not just declarations.
    contexts = tuple(
        sibling.cognition_context_provider(a)
        for a in sibling.context.agent_registry.all_agents()
    )
    assert sibling_assembler.host.run()[0].success
    saved2 = manager.create_manual_save(
        runtime=sibling,
        cognition=sibling_assembler.host.cognition,
        memory_store=sibling_assembler.host.memory,
        agent_contexts=contexts,
    )
    again = Assembler()
    staged = manager.stage_restore(
        saved2.save_id,
        timeline_id=saved2.timeline_id,
        active_runtime=sibling,
        assembler=again,
        dependencies=_dependency_manifest(),
        new_timeline_id="physical-grandchild",
    )
    restored = RestoreCoordinator(parent_slot).activate(staged)
    assert again.host.value()
    before = len(restored.context.event_history.get_events())
    result, event = again.host.run()
    assert result.success is False and again.host.value()
    assert len(restored.context.event_history.get_events()) == before + 1


def test_stale_candidate_cannot_commit_after_another_transition():
    host = Host()
    runtime = host.runtime
    with runtime.write_fence.operation():
        first, event = host.prepare()
        second, other = host.prepare()
        runtime.event_processor.dispatch_with_evidence(event)
        assert host.value()
        with pytest.raises(PermissionError, match="stale physical read"):
            runtime.event_processor.dispatch_with_evidence(other)
    assert len(runtime.context.event_history.get_events()) == 3
    assert host.value()


def test_unjustified_engine_delta_cannot_create_event_or_mutate_world():
    class WrongEngine:
        def evaluate(self, request, context):
            valid = BooleanTransitionEngine().evaluate(request, context)
            return replace(valid, evidence=("fabricated",))

    host = Host()
    before = host.runtime.context.world_state.entities
    with pytest.raises(PermissionError, match="violates"):
        host.run(WrongEngine())
    assert host.runtime.context.world_state.entities == before
    assert len(host.runtime.context.event_history.get_events()) == 2


@pytest.mark.parametrize(
    "kind", ["part_of", "attached_to", "controls", "owned_by", "held_by"]
)
def test_relation_semantics_and_exact_endpoint_validation(kind):
    from cognitive_world.core.entity import Entity

    relation = PhysicalRelation(1, "item", "actor", (kind,))
    entities = {
        "item": Entity("item", "object", owner_id="actor"),
        "actor": Entity("actor", "agent"),
    }
    validate_physical_world(entities, {"item": "actor"}, {("item", "actor"): relation})
    with pytest.raises(ValueError):
        validate_physical_world(
            {"item": entities["item"]}, {}, {("item", "actor"): relation}
        )
    with pytest.raises(ValueError):
        PhysicalRelation(1, "item", "item", (kind,))
    if kind == "owned_by":
        with pytest.raises(ValueError):
            validate_physical_world(
                {
                    "item": replace(entities["item"], owner_id=None),
                    "actor": entities["actor"],
                },
                {},
                {("item", "actor"): relation},
            )
    if kind == "held_by":
        with pytest.raises(ValueError):
            validate_physical_world(
                entities, {"item": "room"}, {("item", "actor"): relation}
            )


def test_numeric_declaration_does_not_enable_boolean_operation():
    data = document()
    data["objects"][0]["physical_state"]["properties"][0] = {
        "definition": {
            "version": 1,
            "name": "open",
            "value_type": "number",
            "unit": "1",
            "minimum": 0,
            "maximum": 1,
        },
        "value": 0,
    }
    with pytest.raises(ValueError, match="receiver property"):
        Host(data)


def test_fixture_names_do_not_determine_transition():
    # Consistent renaming changes no engine or production rule code.
    raw = (
        json.dumps(document())
        .replace("panel", "leaf")
        .replace("handle", "control")
        .replace("latch", "stop")
    )
    host = Host(json.loads(raw))
    host.target = "physical:one:object:control"
    host.panel = "physical:one:object:leaf"
    assert host.run()[0].success and host.value()


def test_event_retry_is_idempotent_and_creates_no_new_observation(monkeypatch):
    host = Host()
    runtime = host.runtime
    world = runtime.context.world_state
    applied = []
    apply = world.apply_event

    def record(event, update):
        applied.append(event.id)
        return apply(event, update)

    monkeypatch.setattr(world, "apply_event", record)
    with runtime.write_fence.operation():
        _, event = host.prepare()
        first = runtime.event_processor.dispatch_with_evidence(event)
        repeated = runtime.event_processor.dispatch_with_evidence(event)
    assert first == repeated and applied == [event.id]
    assert len(runtime.context.event_history.get_events()) == 3 and host.value()
    assert (
        runtime.context.event_history.get_processing_evidence(event.id).observable_facts
        == ()
    )


def test_old_generation_candidate_does_not_gain_new_commit_authority():
    import asyncio

    async def scenario():
        host = Host()
        runtime = host.runtime
        release = asyncio.Event()

        async def delayed(event):
            await release.wait()
            runtime.event_processor.dispatch_with_evidence(event)

        with runtime.write_fence.operation():
            _, event = host.prepare()
            task = asyncio.create_task(delayed(event))
        runtime.write_fence.freeze_and_advance()
        runtime.write_fence.unfreeze()
        release.set()
        with pytest.raises(PermissionError):
            await task
        assert not host.value() and len(runtime.context.event_history.get_events()) == 2

    asyncio.run(scenario())


def test_signed_but_semantically_invalid_relation_rejected_on_restore():
    # Adversarial test-root re-signing, not a supported content delivery route.
    import base64
    from hashlib import sha256
    from cognitive_world.core.world_state import WorldState
    from cognitive_world.content.persistence import scenario_snapshot_codec

    host = Host()
    runtime = host.runtime
    codec = scenario_snapshot_codec()
    envelope = json.loads(
        runtime.context.world_state.export_persisted_snapshot(
            event_history=runtime.context.event_history,
            simulation_tick=runtime.context.clock.current_time,
            trust=host.trust,
            timeline_id=runtime.context.event_history.timeline_id,
            codec=codec,
        )
    )
    body = codec.loads(base64.b64decode(envelope["body"]))
    pair, relation = next(iter(body["relationships"].items()))
    body["relationships"][pair] = replace(relation, target="not-an-entity")
    data = codec.dumps(body)
    envelope["body"] = base64.b64encode(data).decode()
    envelope["body_sha256"] = sha256(data).hexdigest()
    signed = json.dumps(
        {
            k: envelope[k]
            for k in (
                "schema",
                "version",
                "timeline_id",
                "simulation_tick",
                "body_sha256",
            )
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    envelope["signature"] = base64.b64encode(
        host.trust.sign("cognitive-world/world-state-checkpoint/v3", signed)
    ).decode()
    with pytest.raises(ValueError, match="endpoint"):
        WorldState.restore_persisted_snapshot(
            json.dumps(envelope).encode(), trust=host.trust, codec=codec
        )
    assert not host.value()


def test_existing_runnable_json_host_commits_the_installed_rule(capsys):
    from pathlib import Path
    from cognitive_world.examples.json_objects import run

    context = run(
        Path(__file__).resolve().parents[1] / "examples/data/physical_assembly.json",
        "visit",
    )
    entity = context.world_state.get_entity("local:demo:object:panel")
    assert entity.state["physical"].get("open").value is True
    resolutions = [
        e for e in context.event_history.get_events() if e.type == "resolution"
    ]
    assert len(resolutions) == 1
    assert "Committed physical transition: True" in capsys.readouterr().out


@pytest.mark.parametrize(
    "definition,value",
    [
        (
            lambda: PhysicalPropertyDefinition(1, "x", "number", "kg", 0, 10),
            float("nan"),
        ),
        (lambda: PhysicalPropertyDefinition(1, "x", "number", "kg", 0, 10), 11),
        (lambda: PhysicalPropertyDefinition(1, "x", "number", "kg", 0, 10), True),
        (lambda: PhysicalPropertyDefinition(1, "x", "number", "unknown", 0, 10), 1),
        (lambda: PhysicalPropertyDefinition(1, "x", "number", "kg", 10, 0), 1),
    ],
)
def test_invalid_units_and_constraints_fail_closed(definition, value):
    with pytest.raises(ValueError):
        PhysicalValue(definition(), value)


def multi_rule_document():
    data = document()
    scenario = data["scenarios"][0]
    scenario["physical_relations"] = []
    first = scenario["physical_rules"][0]
    first["conditions"] = []
    first["relations"] = []
    second = deepcopy(first)
    second.update(
        target_ref="object:panel",
        rule_id="independent-control",
        operation="other",
        receiver_id="object:latch",
        property_name="engaged",
    )
    scenario["physical_rules"].append(second)
    return data


def close_rule_document():
    data = multi_rule_document()
    scenario = data["scenarios"][0]
    closing = deepcopy(scenario["physical_rules"][0])
    closing.update(
        rule_id="close-assembly", operation="close", expected=True, replacement=False
    )
    scenario["physical_rules"] = [scenario["physical_rules"][0], closing]
    return data


def signed_history(host):
    history = host.runtime.context.event_history
    return tuple(
        history.get_persistence_record(e.id).to_json_record()
        for e in history.get_events()
    )


def test_active_rule_does_not_validate_another_rules_partial_graph():
    host = Host(multi_rule_document())
    latch = "physical:one:object:latch"

    class LocalEngine:
        def evaluate(self, request, context):
            assert latch not in {state.entity_id for state in context.states}
            return BooleanTransitionEngine().evaluate(request, context)

    result, event = host.run(LocalEngine())
    assert result.success and host.value()
    assert (
        event is not None and len(host.runtime.context.event_history.get_events()) == 3
    )
    assert (
        host.runtime.context.world_state.get_entity(latch)
        .state["physical"]
        .get("engaged")
        .value
        is False
    )
    # R2 remains usable through the same formal production path.
    host.target = host.panel
    result, event = host.run(operation="other")
    assert result.success and event is not None
    assert (
        host.runtime.context.world_state.get_entity(latch)
        .state["physical"]
        .get("engaged")
        .value
        is True
    )


@pytest.mark.parametrize("invalid", ["receiver", "condition", "relation", "property"])
def test_invalid_active_rule_references_still_reject_before_installation(invalid):
    data = multi_rule_document()
    rule = data["scenarios"][0]["physical_rules"][0]
    if invalid == "receiver":
        rule["receiver_id"] = "object:absent"
    elif invalid == "condition":
        rule["conditions"] = [
            {"entity_id": "object:absent", "property_name": "open", "value": False}
        ]
    elif invalid == "relation":
        rule["relations"] = [
            {
                "source": "object:handle",
                "target": "object:absent",
                "kinds": ["controls"],
            }
        ]
    else:
        rule["property_name"] = "not-declared"
    runtime, cognition, memory, installer = _signed_runtime()
    before = runtime.context.world_state.entities
    with runtime.write_fence.operation():
        with pytest.raises(ValueError):
            installer.install_proposal(
                parse_generation_proposal(json.dumps(data)),
                template_id="visit",
                instance_id="one",
                world_id="physical",
                source_id="authored-json",
            )
    assert runtime.context.world_state.entities == before
    assert runtime.context.world_state.relationships == {}
    assert runtime.context.event_history.get_events() == ()
    assert not runtime.write_fence.recovery_required


def corrupt_delta(valid, context, kind):
    if kind == "target":
        other = next(s for s in context.states if s.entity_id != valid.delta.entity_id)
        prop = other.properties[0]
        replacement = replace(
            other,
            properties=(replace(prop, value=not prop.value), *other.properties[1:]),
        )
        from cognitive_world.core.physical import CandidateStateDelta

        return CandidateStateDelta(other.entity_id, other, replacement)
    if kind == "replacement":
        return replace(valid.delta, replacement=valid.delta.expected)
    return replace(valid.delta, expected=valid.delta.replacement)


@pytest.mark.parametrize("kind", ["target", "replacement", "expected"])
def test_actual_invalid_engine_delta_is_rejected_without_state_or_history_changes(kind):
    class InvalidEngine:
        def evaluate(self, request, context):
            valid = BooleanTransitionEngine().evaluate(request, context)
            return replace(valid, delta=corrupt_delta(valid, context, kind))

    host = Host()
    world = host.runtime.context.world_state
    before = (
        world.entities,
        world.locations,
        world.relationships,
        world.environment,
        world.facts,
    )
    records = signed_history(host)
    with pytest.raises(PermissionError, match="violates"):
        host.run(InvalidEngine())
    assert (
        world.entities,
        world.locations,
        world.relationships,
        world.environment,
        world.facts,
    ) == before
    assert (
        signed_history(host) == records
        and not host.runtime.write_fence.recovery_required
    )
    assert host.run()[0].success and host.value()


@pytest.mark.parametrize("kind", ["target", "replacement", "expected"])
def test_commit_independently_rejects_actual_invalid_delta(kind):
    # Fault injection at the trusted Resolution strategy, not a provider permission.
    from cognitive_world.physics.adapter import capture
    from cognitive_world.physics.engine import InteractionRequest
    from cognitive_world.resolution.engine import ResolutionEngine, ResolutionDecision

    host = Host()
    runtime = host.runtime
    world = runtime.context.world_state
    records = signed_history(host)
    before = world.entities
    with runtime.write_fence.operation():
        _, original = host.prepare()
        effect = deepcopy(original.changes[1])
        context, _ = capture(
            world,
            runtime.context.event_history,
            InteractionRequest(host.owner, host.target, "operate"),
        )
        valid = BooleanTransitionEngine().evaluate(
            InteractionRequest(host.owner, host.target, "operate"), context
        )
        effect["delta"] = corrupt_delta(valid, context, kind)

        class FaultyResolution(ResolutionEngine):
            def _adjudicate(self, attempt):
                return ResolutionDecision(
                    True,
                    "physical state changed",
                    metadata={"simulation_tick": runtime.context.clock.current_time},
                    world_effects=(effect,),
                )

        attempt = ActionPipeline().create_attempt(
            ActionProposal(
                "fault-injection",
                host.owner,
                "operate",
                ["object:" + host.target],
                {
                    "method": "operate the installed control",
                    "physical_operation": "operate",
                },
            )
        )
        _, event = ActionResolutionFlow(
            FaultyResolution(),
            world_state=world,
            event_history=runtime.context.event_history,
        ).execute_with_result(attempt)
        assert event.has_trusted_source("resolution")
        with pytest.raises(PermissionError, match="delta is not justified"):
            runtime.event_processor.dispatch_with_evidence(event)
        assert runtime.context.event_history.get_event(event.id) is None
    assert world.entities == before and signed_history(host) == records
    assert not runtime.write_fence.recovery_required
    assert host.run()[0].success and host.value()


def test_stale_failed_current_result_is_rejected_before_formal_append():
    host = Host(close_rule_document())
    runtime = host.runtime
    with runtime.write_fence.operation():
        result, failed = host.prepare(operation="close")
        assert result.confirmed and result.success is False and not host.value()
        opened, opening = host.prepare()
        runtime.event_processor.dispatch_with_evidence(opening)
        assert opened.success and host.value()
        records = signed_history(host)
        before = runtime.context.world_state.entities
        with pytest.raises(PermissionError, match="state-slot reads are stale"):
            runtime.event_processor.dispatch_with_evidence(failed)
        assert runtime.context.event_history.get_event(failed.id) is None
        assert signed_history(host) == records
        assert runtime.context.world_state.entities == before
        assert not runtime.write_fence.recovery_required
        # Rejection does not retry the action. A new, explicit evaluation is valid.
        current, _ = host.prepare(operation="close")
        assert current.success and host.value()


def test_failed_result_survives_unrelated_change_and_duplicate_delivery():
    data = close_rule_document()
    extra = deepcopy(data["scenarios"][0]["physical_rules"][0])
    extra.update(
        target_ref="object:latch",
        rule_id="independent",
        operation="other",
        receiver_id="object:latch",
        property_name="engaged",
    )
    data["scenarios"][0]["physical_rules"].append(extra)
    host = Host(data)
    runtime = host.runtime
    with runtime.write_fence.operation():
        result, failed = host.prepare(operation="close")
        assert result.success is False
        target = host.target
        host.target = "physical:one:object:latch"
        _, unrelated = host.prepare(operation="other")
        host.target = target
        runtime.event_processor.dispatch_with_evidence(unrelated)
        first = runtime.event_processor.dispatch_with_evidence(failed)
        records = signed_history(host)
        repeated = runtime.event_processor.dispatch_with_evidence(failed)
        assert first == repeated and signed_history(host) == records
        assert first.observable_facts == ()
    assert not host.value() and len(runtime.context.event_history.get_events()) == 4
    assert not runtime.write_fence.recovery_required


def test_failed_read_bindings_chunk_and_restore_as_immutable_history(
    tmp_path, monkeypatch
):
    from cognitive_world.content.persistence import scenario_snapshot_codec
    from cognitive_world.runtime.save_manager import SaveManager
    from cognitive_world.runtime.cold_restore import ColdRuntimePublisher
    from test_runtime_reconstruction import _dependency_manifest
    import cognitive_world.event.processor as processor_module

    data = document()
    body = deepcopy(data["objects"][0])
    body["template_id"] = "body"
    data["objects"] = [body]
    scenario = data["scenarios"][0]
    scenario["objects"] = [[key, "body", "location:far", None] for key in "abcde"]
    relations = [
        {"source": "object:" + a, "target": "object:" + b, "kinds": ["controls"]}
        for a, b in zip("abcde", "bcdea")
    ]
    scenario["physical_relations"] = relations
    rule = scenario["physical_rules"][0]
    rule.update(
        target_ref="object:a",
        receiver_id="object:b",
        relations=deepcopy(relations),
        conditions=[
            {"entity_id": "object:c", "property_name": "open", "value": True},
            {"entity_id": "object:d", "property_name": "open", "value": False},
        ],
    )
    # This second, independent operation changes the same receiver formally.
    opening = deepcopy(rule)
    opening.update(
        rule_id="open-direct", operation="open-direct", conditions=[], relations=[]
    )
    scenario["physical_rules"].append(opening)
    host = Host(data)
    host.target = "physical:one:object:a"
    host.panel = "physical:one:object:b"
    runtime = host.runtime
    with runtime.write_fence.operation():
        result, failed = host.prepare()
        assert result.success is False
        entries = failed.metadata["physical_effect_provenance"]
        assert [len(entry["state_slot_reads"]) for entry in entries] == [32, 1]
        assert "confirmed_attempt_failure" not in failed.metadata
        runtime.event_processor.dispatch_with_evidence(failed)
        _, opening_event = host.prepare(operation="open-direct")
        runtime.event_processor.dispatch_with_evidence(opening_event)
        assert host.value()
    records = signed_history(host)
    manager = SaveManager(
        tmp_path / "saves", trust=host.trust, codec=scenario_snapshot_codec()
    )
    contexts = tuple(
        runtime.cognition_context_provider(a)
        for a in runtime.context.agent_registry.all_agents()
    )
    saved = manager.create_manual_save(
        runtime=runtime,
        cognition=host.cognition,
        memory_store=host.memory,
        agent_contexts=contexts,
    )

    class Assembler:
        def assemble(self, inputs):
            self.host = Host(inputs=inputs, trust=host.trust)
            self.host.target = host.target
            self.host.panel = host.panel
            return self.host.runtime

    def forbid(*args, **kwargs):
        pytest.fail("restore must not re-sign historical failed candidates")

    monkeypatch.setattr(processor_module, "make_persisted_event_record", forbid)
    assembler = Assembler()
    stage = manager.stage_cold_resume(
        saved.save_id,
        timeline_id=saved.timeline_id,
        assembler=assembler,
        dependencies=_dependency_manifest(),
    )
    ColdRuntimePublisher().activate(stage)
    assert assembler.host.value() and signed_history(assembler.host) == records
    restored = assembler.host.runtime.context.event_history.get_event(failed.id)
    assert restored == failed
    assert assembler.host.runtime.context.observation_store.all() == ()
