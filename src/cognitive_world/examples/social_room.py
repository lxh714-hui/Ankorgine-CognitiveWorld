"""Executable, deterministic social/physical room using the production Runtime.

Names and the room's behavioral policy are content configuration. No new physical
solver is supplied: keyed door manipulation is the supported physical slice.
Run from the checkout: py -3.14 run_social_room.py --save-root PATH
"""
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from cognitive_world.agent.action_loop import AgentActionLoop
from cognitive_world.agent.turn import AgentTurn
from cognitive_world.safety.governance import UniversalSafetyGovernance
from cognitive_world.runtime.conflict_opportunity import ConflictOpportunityScheduler
from cognitive_world.cognition.snapshot import cognitive_snapshot_codec
from cognitive_world.agent.character import Character
from cognitive_world.agent.cognition_context import CognitionContext
from cognitive_world.agent.registry import AgentRegistry
from cognitive_world.agent.runtime_agent import RuntimeAgent
from cognitive_world.cognition.belief import Belief
from cognitive_world.cognition.container import CognitionContainer
from cognitive_world.cognition.goal import Goal
from cognitive_world.cognition.goal_completion import GoalCompletionCondition, ConsumedResultGoalCompletion
from cognitive_world.cognition.memory_store import MemoryStore
from cognitive_world.cognition.personality import Personality
from cognitive_world.core.attributed_claim import AttributedClaimDraft, ClaimPropertyContract
from cognitive_world.core.door import DoorState
from cognitive_world.core.entity import Entity
from cognitive_world.core.world_state import WorldState
from cognitive_world.decision.agent_decision import AgentDecision
from cognitive_world.decision.autonomous import ActionCandidate, CandidateEvaluation
from cognitive_world.dialogue.npc import NpcCommunicationDraft
from cognitive_world.event import EventHistory, EventProcessor, SystemEventFactory, RoomLightChangedHandler
from cognitive_world.event.environment import EnvironmentStateObservedHandler
from cognitive_world.observation.store import ObservationStore
from cognitive_world.resolution.action_flow import ActionResolutionFlow
from cognitive_world.resolution.causal import MethodBasedResolutionEngine
from cognitive_world.runtime.agent_scheduler import AgentScheduler
from cognitive_world.runtime.clock import SimulationClock
from cognitive_world.runtime.context import RuntimeContext
from cognitive_world.runtime.runtime import SimulationRuntime
from cognitive_world.runtime.scheduler import EventScheduler
from cognitive_world.runtime.write_fence import RuntimeWriteFence
from cognitive_world.memory.social_experience import (
    SocialExperienceService, SocialExperience, EvidenceGoalDraft, with_social_memory_grants,
)
from cognitive_world.memory.decision_policy import MemoryDecisionResult, MemoryPolicyOutput


@dataclass(frozen=True)
class RecipientDefinition:
    owner_id: str
    act_on_verified_testimony: bool
    can_see: bool = True
    prior_light_value: bool = False

    def __post_init__(self):
        if not isinstance(self.owner_id, str) or not self.owner_id or len(self.owner_id) > 256:
            raise ValueError("recipient requires a bounded owner identity")
        if any(type(value) is not bool for value in (
                self.act_on_verified_testimony, self.can_see, self.prior_light_value)):
            raise TypeError("recipient settings must be explicit booleans")


@dataclass(frozen=True)
class RoomAssessment:
    """Read-only host diagnostic, not a player-facing Presentation DTO."""
    owner_id: str
    speech_event_id: str
    evidence_status: str
    goal_ids: tuple[str, ...]


@dataclass(frozen=True)
class RoomDefinition:
    room: str = "workroom"
    speaker: str = "informant"
    receiver: str = "investigator"
    key: str = "brass-key"
    table: str = "worktable"
    drawer: str = "table-drawer"
    door: str = "exit-door"
    goal_description: str = "Try opening the exit door using my key"
    observation_property: str = "room_light_on"
    testimony_value: bool = True
    accept_testimony: bool = True
    key_available: bool = True
    testimony_text: str | None = None
    additional_receivers: tuple[RecipientDefinition, ...] = ()
    goal_completion: GoalCompletionCondition | None = None

    def __post_init__(self):
        if self.goal_completion is not None and type(self.goal_completion) is not GoalCompletionCondition:
            raise TypeError("room Goal completion must use a typed condition")
        if (not isinstance(self.additional_receivers, tuple)
                or any(type(item) is not RecipientDefinition for item in self.additional_receivers)):
            raise TypeError("additional receivers must be explicit immutable definitions")
        ids = (self.room, self.key, self.table, self.drawer, self.door,
               self.speaker, self.receiver, *(item.owner_id for item in self.additional_receivers))
        if len(set(ids)) != len(ids):
            raise ValueError("room actors and objects must have distinct identities")

    @property
    def recipients(self):
        return (RecipientDefinition(self.receiver, self.accept_testimony), *self.additional_receivers)



class RoomSocialPolicy:
    """Explicit content policy: assess this experience, not global speaker truth."""
    policy_id = "social-room/evidence-review"
    policy_version = "2"

    def __init__(self, definition, *, personalities):
        self.definition = definition
        # Stable owner preferences are copied from canonical Personality on
        # assembly/restore, never inferred from speech or current host flags.
        self.willing_owners = frozenset(
            p.owner_id for p in personalities
            if p.preferences.get("act_on_verified_testimony") is True)


    def evaluate(self, request):
        return MemoryPolicyOutput(MemoryDecisionResult.ACCEPTED, 0.6, "retain_bounded_comparison")

    def propose_goals(self, experiences):
        eligible = [(identity, value) for identity, value in experiences
                    if value.comparison == "supported"
                    and value.owner_id in {r.owner_id for r in self.definition.recipients}
                    and value.speaker_id == self.definition.speaker]
        if not eligible or eligible[0][1].owner_id not in self.willing_owners:
            return ()
        # One stable evidence set; a new turn does not manufacture new Goals.
        condition = self.definition.goal_completion or GoalCompletionCondition(
            "object:" + self.definition.door, "environment_state", "door_open",
            self.definition.door, True)
        return (EvidenceGoalDraft(self.definition.goal_description, 0.8, (eligible[0][0],), condition),)

    def propose_beliefs(self, beliefs, experiences):
        from cognitive_world.cognition.belief_update import BeliefUpdater
        if not experiences:
            return ()
        identity, experience = experiences[0]
        relevant = [b for b in beliefs if b.content.get("property") == self.definition.observation_property]
        if not relevant:
            return ()
        value = experience.observed_value
        belief = relevant[0]
        content = {"property": experience.property_ref, "value": value}
        if belief.content == content:
            return ()
        return (BeliefUpdater().propose_update(belief, {
            "new_value": content, "source_refs": [identity],
            "reason": "Review this exact historical observation, not all testimony.",
            "confidence": 0.8,
        }),)


class RoomSpeechPolicy:
    def __init__(self, definition):
        self.definition = definition
        self.recipient_id = definition.receiver

    def propose(self, situation, *, recipient_ids, maximum_candidates):
        d = self.definition
        if situation.owner_id != d.speaker or self.recipient_id not in recipient_ids:
            return ()
        fact = next((f for f in situation.observed_facts
                     if f.predicate == d.observation_property), None)
        if fact is None:
            return ()
        claim = AttributedClaimDraft(d.room, d.observation_property, "boolean",
                                     d.testimony_value, 0, 0, "event:room-initial-light")
        return (NpcCommunicationDraft(
            self.recipient_id, d.testimony_text or f"My claim concerns the room light at tick zero: {d.testimony_value}.",
            (fact.percept_id,), claim),)


class RoomCandidates:
    def __init__(self, definition):
        self.definition = definition

    def generate(self, situation):
        d = self.definition
        wait = ActionCandidate(
            "wait:" + situation.owner_id, situation.owner_id, None, "Wait", None,
            "wait for further information", (), (), (), ("Wait.",),
            "No world change is assumed.", (), 0.0, 0.0, 0.1, (), "room-content")
        active = next((g for g in situation.goals
                       if g.description == d.goal_description and g.status == "active" and not g.blocked), None)
        door = next((f for f in situation.observed_facts
                     if f.subject_ref == d.door and f.predicate == "door_open" and f.value == "False"), None)
        if active is None or door is None:
            return (wait,)
        return (wait, ActionCandidate(
            "open:" + d.door, situation.owner_id, active.goal_id,
            "Try opening the exit", "object:" + d.door,
            "use key to unlock and open the door", (d.key,), ("manual_manipulation",),
            ("The actual key must be held.",), ("Use the key and push.",),
            "The installed mechanism will adjudicate the attempt.",
            ("Having an intention does not establish success.",),
            0.1, 0.1, 0.5, (door.percept_id,), "room-content"))


class RoomEvaluation:
    def evaluate(self, situation, candidates):
        return tuple(CandidateEvaluation(
            c.candidate_id, 0.9 if c.strategy == "npc_communication_v1" or c.goal_id else 0.1,
            (("explicit_room_policy", 0.9 if c.goal_id else 0.1),), c.uncertainties)
            for c in candidates)


class NoExtraReview:
    def should_review(self, situation, evaluations):
        return False


class SocialRoom:
    def __init__(self, *, trust, definition=RoomDefinition(), inputs=None):
        self.definition, self.trust = definition, trust
        d = definition
        world = WorldState() if inputs is None else inputs.world_state
        cognition = CognitionContainer() if inputs is None else inputs.cognition
        memory = MemoryStore() if inputs is None else inputs.memory_store
        history = EventHistory(timeline_id="social-room:" + uuid4().hex) if inputs is None else inputs.event_history
        clock = SimulationClock() if inputs is None else inputs.clock
        fence = RuntimeWriteFence() if inputs is None else inputs.write_fence
        agents, observations = AgentRegistry(), ObservationStore()
        self.base_characters = {}
        profiles = {r.owner_id: r for r in d.recipients}
        if inputs is None:
            world.load_environment_snapshot({
                d.room: {"light_on": False},
                d.door: DoorState(d.door, d.room, False, True, True, d.key),
            })
            for identity, kind in ((d.room, "room"), (d.table, "table"), (d.drawer, "drawer"), (d.door, "door")):
                world.load_entity(Entity(identity, kind))
            world.load_location(d.table, d.room)
            world.load_location(d.drawer, d.table)  # declared static hierarchy, no general containment solver
            world.load_location(d.door, d.room)
            world.load_entity(Entity(d.key, "tool", attributes={"kind": "key"}, owner_id=d.receiver if d.key_available else None))
            world.load_location(d.key, d.receiver if d.key_available else d.drawer)
            for owner in (d.speaker, *profiles):
                profile = profiles.get(owner)
                world.load_entity(Entity(owner, "character",
                    sensory_capabilities=("sight",) if profile is None or profile.can_see else (),
                    physical_capabilities=("manual_manipulation",)))
                world.load_location(owner, d.room)
                cognition.add_personality(Personality(owner, preferences={
                    "act_on_verified_testimony": profile.act_on_verified_testimony
                    if profile is not None else False}))
                cognition.add_belief(Belief("light:" + owner, owner,
                    {"property": d.observation_property,
                     "value": profile.prior_light_value if profile is not None else False}, [], 0.4))
                cognition.add_goal(Goal("assess:" + owner, owner, "Assess available evidence", 0.4))
                self.base_characters[owner] = Character(
                    "character:" + owner, owner, owner,
                    belief_ids=["light:" + owner], goal_ids=["assess:" + owner])
        else:
            links = {link.agent_id: link for link in inputs.agent_links}
            if set(links) != {d.speaker, *profiles}:
                raise ValueError("saved roster does not match this content definition")
            for owner, link in links.items():
                self.base_characters[owner] = Character(
                    link.character_id, owner, link.personality_id or "",
                    list(link.memory_ids), list(link.belief_ids), link.emotion_id or "",
                    goal_ids=list(link.goal_ids))
        for owner, character in self.base_characters.items():
            agents.register(RuntimeAgent(owner, character.id, character.goal_ids))
        scheduler, agent_scheduler = EventScheduler(), AgentScheduler()
        safety = UniversalSafetyGovernance()
        processor = EventProcessor(world_state=world, event_history=history,
            simulation_clock=clock, agent_registry=agents, observation_store=observations,
            persistence_trust=trust, persistence_codec=cognitive_snapshot_codec(), write_fence=fence)
        processor.register_handler("room_light_changed", RoomLightChangedHandler())
        processor.register_handler("environment_state_observed", EnvironmentStateObservedHandler())
        context = RuntimeContext(clock, world, history, event_scheduler=scheduler,
            agent_scheduler=agent_scheduler, agent_registry=agents, observation_store=observations, safety_governance=safety)
        self.cognition, self.memory, self.processor = cognition, memory, processor

        def context_for(agent):
            from dataclasses import replace
            canonical = agents.get(agent.agent_id)
            character = replace(self.base_characters[agent.agent_id], goal_ids=list(canonical.goal_ids))
            character = with_social_memory_grants(character, memory,
                history=history, trust=trust, tick=clock.current_time)
            return CognitionContext.from_character(character, cognition, memory, observation_store=observations)

        kwargs = {} if inputs is None else {
            "memory_revision_lineage": inputs.memory_revision_lineage,
            "behavior_feedback": inputs.behavior_feedback,
            "behavior_feedback_status": inputs.behavior_feedback_status,
        }
        from cognitive_world.decision.evidence_review import DeterministicLocalEvidenceReviewProvider
        loop = AgentActionLoop(agent_turn=AgentTurn(write_fence=fence), write_fence=fence,
            safety_governance=safety, action_resolution_flow=ActionResolutionFlow(
            resolution_engine=MethodBasedResolutionEngine(world_state=world),
            world_state=world, event_history=history, safety_governance=safety))
        self.runtime = SimulationRuntime(context, write_fence=fence, scheduler=scheduler,
            event_processor=processor, agent_action_loop=loop,
            cognition_context_provider=context_for,
            agent_decision=AgentDecision(candidate_policy=RoomCandidates(d),
                evaluation_policy=RoomEvaluation(), review_policy=NoExtraReview()),
            npc_communication_provider=RoomSpeechPolicy(d),
            npc_claim_property_contracts=(ClaimPropertyContract(d.observation_property, "boolean"),),
            evidence_review_provider=DeterministicLocalEvidenceReviewProvider(),
            conflict_opportunity_scheduler=ConflictOpportunityScheduler(),
            strict_dependency_binding=inputs is not None,
            allow_environment_provider_discovery=False, **kwargs)
        cognition.bind_write_fence(fence)
        memory.bind_write_fence(fence)
        self.social = SocialExperienceService(runtime=self.runtime, cognition=cognition,
            memory_store=memory, policy=RoomSocialPolicy(d, personalities=cognition.personality_store.get_all()))
        loop.agent_turn.social_experience_service = self.social
        self.goal_completion = ConsumedResultGoalCompletion(self.runtime)
        loop.agent_turn.goal_completion_service = self.goal_completion
        if inputs is None:
            with fence.operation():
                processor.dispatch_with_evidence(SystemEventFactory().create(
                    event_id="room-initial-light", event_type="room_light_changed", timestamp="0",
                    simulation_tick=0, changes=[{"room_id": d.room, "from_light_on": False, "to_light_on": True}]))
                self.observe_door()

    def observe_door(self):
        rt = self.runtime
        count = len(rt.context.event_history.get_events())
        self.processor.dispatch_with_evidence(SystemEventFactory().create(
            event_id=f"door-observation:{rt.context.event_history.timeline_id}:{count}",
            event_type="environment_state_observed", timestamp=str(rt.context.clock.current_time),
            simulation_tick=rt.context.clock.current_time,
            changes=[{"environment_id": self.definition.door}]))

    def advance(self, *, speak=False, recipient=None):
        rt, d = self.runtime, self.definition
        recipient = d.receiver if recipient is None else recipient
        if recipient not in {r.owner_id for r in d.recipients}:
            raise ValueError("recipient is not part of this room")
        turns = ()
        if speak:
            # A directed exchange spans two bounded ticks. Scheduling both
            # owners together would make consumption depend on ID ordering.
            # This offers one candidate; it never retries or forces speech.
            rt.npc_communication_provider.recipient_id = recipient
            rt.context.agent_scheduler.schedule_agent(d.speaker, rt.context.clock.current_time + 1)
            rt.step()
            turns = rt.last_agent_turn_results
            if rt.write_fence.recovery_required:
                return turns
        rt.context.agent_scheduler.schedule_agent(recipient, rt.context.clock.current_time + 1)
        rt.step()
        return (*turns, *rt.last_agent_turn_results)

    def advance_receivers(self):
        rt = self.runtime
        for recipient in self.definition.recipients:
            rt.context.agent_scheduler.schedule_agent(recipient.owner_id, rt.context.clock.current_time + 1)
        rt.step()
        return rt.last_agent_turn_results

    def assessments(self, owner_id):
        from cognitive_world.cognition.l1_consumption_proof import (
            PROOF_MEMORY_TYPE, NONVERBAL_PROOF_MEMORY_TYPE, verify_proof,
        )
        from cognitive_world.memory.social_experience import build_experience
        rt = self.runtime
        agent = rt.context.agent_registry.get(owner_id)
        if agent is None or owner_id not in {r.owner_id for r in self.definition.recipients}:
            raise ValueError("unknown room recipient")
        context = rt.cognition_context_provider(agent)
        experiences = tuple(m for m in context.get_memories()
                            if type(m.content) is SocialExperience)
        results = []
        for memory in self.memory.get_memories_by_owner(owner_id):
            if memory.type != PROOF_MEMORY_TYPE:
                continue
            verify_proof(memory.content, history=rt.context.event_history, trust=self.trust,
                         checkpoint_timeline_id=rt.context.event_history.timeline_id,
                         checkpoint_tick=rt.context.clock.current_time)
            matching = [m for m in experiences if m.content.speech_memory_id == memory.id]
            if len(matching) == 1:
                status = matching[0].content.comparison
            elif matching:
                status = "unresolved"
            else:
                status = "insufficient"
                # Missing Memory is not automatically missing evidence. Reuse
                # the comparator, without writing, to distinguish pending review.
                for evidence in self.memory.get_memories_by_owner(owner_id):
                    if evidence.type != NONVERBAL_PROOF_MEMORY_TYPE:
                        continue
                    try:
                        build_experience(owner_id=owner_id, character_id=agent.character_id,
                            speech=memory, evidence=evidence, history=rt.context.event_history,
                            trust=self.trust, tick=rt.context.clock.current_time)
                    except PermissionError:
                        continue
                    status = "awaiting_review"
                    break
            source_ids = {m.id for m in matching}
            goals = tuple(g.goal_id for g in context.get_goals()
                          if source_ids.intersection(g.source_refs) and g.status == "active")
            results.append(RoomAssessment(owner_id, memory.source_event, status, goals))
        return tuple(results)

    def save(self, manager):
        return manager.create_manual_save(runtime=self.runtime, cognition=self.cognition,
                                         memory_store=self.memory, agent_contexts=(), name="social-physical-room")


class SocialRoomAssembler:
    def __init__(self, *, trust, definition=RoomDefinition()):
        self.trust, self.definition = trust, definition

    def assemble(self, inputs):
        self.scene = SocialRoom(trust=self.trust, definition=self.definition, inputs=inputs)
        return self.scene.runtime


def dependency_manifest():
    from cognitive_world.runtime.reconstruction import (
        RuntimeDependencyManifest, RuntimeDependencyResolution, DependencyStrategy,
    )
    hosts = ("agent_character_catalog", "agent_runtime_metadata", "agent_scheduler_state",
             "event_scheduler_state", "event_handler_registry", "agent_decision_policy",
             "agent_action_loop_policy", "cognition_context_provider", "safety_policy",
             "observation_policy")
    return RuntimeDependencyManifest(tuple(
        [RuntimeDependencyResolution(role, DependencyStrategy.HOST, "social_room.py: explicit content host")
         for role in hosts] +
        [RuntimeDependencyResolution(role, DependencyStrategy.REBUILT, "current bounded diagnostics")
         for role in ("event_tree_policy", "conflict_scheduler_policy")] +
        [RuntimeDependencyResolution(role, DependencyStrategy.DISABLED, "not used by this room")
         for role in ("provider_policy", "content_expansion_policy", "player_session_policy")]))


def main():
    import argparse
    from cognitive_world.examples.persistence_trust import open_demo_trust
    from cognitive_world.cognition.snapshot import cognitive_snapshot_codec
    from cognitive_world.runtime.save_manager import SaveManager
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--save-root", type=Path, required=True)
    parser.add_argument("--contrasting-receivers", action="store_true")
    args = parser.parse_args()
    args.save_root.mkdir(parents=True, exist_ok=True)
    trust = open_demo_trust(args.save_root)
    definition = (RoomDefinition(additional_receivers=(
        RecipientDefinition("cautious-investigator", False),))
        if args.contrasting_receivers else RoomDefinition())
    scene = SocialRoom(trust=trust, definition=definition)
    rounds = [scene.advance(speak=True, recipient=r.owner_id) for r in definition.recipients]
    rounds.append(scene.advance_receivers())
    # A bounded next turn consumes the committed result before Goal completion.
    rounds.append(scene.advance_receivers())
    if any(turn.failure_type is not None for turns in rounds for turn in turns):
        raise RuntimeError("room turn failed; checkpoint not published")
    manager = SaveManager(args.save_root / "saves", trust=trust, codec=cognitive_snapshot_codec())
    saved = scene.save(manager)
    state = scene.runtime.context.world_state.environment[scene.definition.door]
    print(f"Door open={state.is_open}, locked={state.is_locked}; checkpoint={saved.save_id}")
    completed = sum(g.status == "completed" for g in scene.cognition.goal_store.get_all())
    print(f"Completed goals={completed}")
    if args.contrasting_receivers:
        for recipient in definition.recipients:
            for assessment in scene.assessments(recipient.owner_id):
                print(f"{assessment.owner_id}: evidence={assessment.evidence_status}, active_goals={len(assessment.goal_ids)}")


if __name__ == "__main__":
    main()
