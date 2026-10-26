"""Structured generation, validation, registration and pre-runtime installation."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from cognitive_world.agent.character import Character
from cognitive_world.agent.registry import AgentRegistry
from cognitive_world.agent.runtime_agent import RuntimeAgent
from cognitive_world.cognition.container import CognitionContainer
from cognitive_world.cognition.goal import Goal
from cognitive_world.cognition.personality import Personality
from cognitive_world.cognition.self_model import SelfModel
from cognitive_world.core.door import DoorState
from cognitive_world.core.entity import Entity
from cognitive_world.core.passage import PassageState
from cognitive_world.core.world_state import WorldState
from cognitive_world.safety.governance import SafetyDisposition, SafetyInput, UniversalSafetyGovernance

from .models import (CharacterInstance, CharacterTemplate, EventSeed, LocationInstance,
                     LocationTemplate, ScenarioInstance, ScenarioTemplate, ObjectTemplate)


@dataclass(frozen=True)
class GenerationProposal:
    characters: tuple[CharacterTemplate, ...]
    locations: tuple[LocationTemplate, ...]
    scenarios: tuple[ScenarioTemplate, ...]
    objects: tuple[ObjectTemplate, ...] = ()


class ContentGenerator(Protocol):
    """Future providers return a proposal, never a world mutation."""
    def generate(self) -> GenerationProposal: ...


@dataclass(frozen=True)
class ContentValidator:
    safety: UniversalSafetyGovernance

    def __post_init__(self) -> None:
        if type(self.safety) is not UniversalSafetyGovernance:
            raise TypeError("content validation requires UniversalSafetyGovernance")

    def _check_text(self, text: str) -> None:
        assessment = self.safety.assess(SafetyInput(
            actor_id="content_generation", source="world_content_hint",
            intent=text, context="untrusted reusable content proposal",
        ))
        if assessment.disposition in {SafetyDisposition.REFUSE, SafetyDisposition.CLARIFY}:
            raise PermissionError("generated content did not pass P0 safety review")

    def validate(self, proposal: GenerationProposal) -> None:
        if type(proposal) is not GenerationProposal:
            raise TypeError("generation requires a typed proposal")
        objects = self._index(proposal.objects, ObjectTemplate)
        characters = self._index(proposal.characters, CharacterTemplate)
        locations = self._index(proposal.locations, LocationTemplate)
        scenarios = self._index(proposal.scenarios, ScenarioTemplate)
        for template in (*characters.values(), *locations.values(), *scenarios.values(), *objects.values()):
            self._check_text(template.description)
        for character in characters.values():
            for goal in character.goal_descriptions:
                self._check_text(goal)
        for scenario in scenarios.values():
            location_keys = [key for key, _ in scenario.locations]
            character_keys = [key for key, _, _ in scenario.characters]
            if not location_keys or len(set(location_keys)) != len(location_keys):
                raise ValueError("scenario locations must have distinct local keys")
            if len(set(character_keys)) != len(character_keys):
                raise ValueError("scenario characters must have distinct local keys")
            for key in (*location_keys, *character_keys, scenario.entry_key, *scenario.exit_keys):
                if not isinstance(key, str) or not key:
                    raise ValueError("scenario references must be non-empty strings")
            if scenario.entry_key not in location_keys or not scenario.exit_keys or any(key not in location_keys for key in scenario.exit_keys):
                raise ValueError("scenario entry and exits must reference locations")
            mechanism_keys: set[str] = set()
            for key, template_id in scenario.locations:
                if template_id not in locations:
                    raise ValueError("missing LocationTemplate")
                for mechanism in locations[template_id].mechanisms:
                    if mechanism.kind == "passage" and mechanism.destination_key not in location_keys:
                        raise ValueError("passage destination is not in scenario")
                    mechanism_keys.add(f"{key}/{mechanism.local_id}")
            for _, template_id, location_key in scenario.characters:
                if template_id not in characters or location_key not in location_keys:
                    raise ValueError("missing CharacterTemplate or placement")
            for _, tid in scenario.locations:
                zone = locations[tid].observation_zone
                if zone is not None and zone.frame_id not in location_keys:
                    raise ValueError("observation frame is not a scenario location")
            object_keys = [row[0] for row in scenario.objects]
            if len(set(object_keys)) != len(object_keys) or set(object_keys) & (set(character_keys) | set(location_keys)):
                raise ValueError("object local identity conflict")
            refs = {"location:" + k for k in location_keys} | {"actor:" + k for k in character_keys}
            for key, tid, place, owner in scenario.objects:
                if tid not in objects or place not in refs or (owner is not None and owner not in {"actor:" + k for k in character_keys}):
                    raise ValueError("object placement or owner reference missing")
                policy = objects[tid].observation_policy
                if policy is not None and not set(policy.detail_observers).issubset(character_keys):
                    raise ValueError("detail recipient is outside the scenario")
            for _, tid in scenario.locations:
                for mechanism in locations[tid].mechanisms:
                    if mechanism.appearance_ref is not None:
                        appearance = objects.get(mechanism.appearance_ref)
                        if appearance is None:
                            raise ValueError("mechanism appearance template missing")
                        policy = appearance.observation_policy
                        if policy is not None and not set(policy.detail_observers).issubset(character_keys):
                            raise ValueError("mechanism detail recipient is outside scenario")
                    if mechanism.key_ref is not None and mechanism.key_ref not in object_keys:
                        raise ValueError("door key reference missing")
                    if mechanism.key_ref is not None:
                        template_id = next(row[1] for row in scenario.objects if row[0] == mechanism.key_ref)
                        if objects[template_id].kind != "tool":
                            raise ValueError("door key requires a tool object")
            seed_ids = [seed.seed_id for seed in scenario.event_seeds]
            if len(seed_ids) != len(set(seed_ids)):
                raise ValueError("duplicate EventSeed ID")
            for seed in scenario.event_seeds:
                for claim in (*seed.possible_effects, *seed.constraints):
                    self._check_text(claim)
                if any(key not in character_keys for key in seed.participant_keys):
                    raise ValueError("seed participant is not placed in scenario")
                if any(hook not in seed_ids for hook in seed.follow_up_hooks):
                    raise ValueError("seed follow-up is missing")
            valid_refs = set(character_keys) | mechanism_keys | set(seed_ids)
            if any(ref not in valid_refs for ref in scenario.value_refs):
                raise ValueError("side-branch value must reference real content")
            meaningful_refs = {
                ref for ref in scenario.value_refs
                if ref in mechanism_keys
                or ref in seed_ids and any(seed.seed_id == ref and (seed.possible_effects or seed.follow_up_hooks) for seed in scenario.event_seeds)
                or ref in character_keys and any(key == ref and characters[template_id].goal_descriptions for key, template_id, _ in scenario.characters)
            }
            if scenario.side_branch and not meaningful_refs:
                raise ValueError("meaningless side branch has no continuation value")

    @staticmethod
    def _index(items: tuple, kind: type) -> dict[str, object]:
        if not isinstance(items, tuple) or any(type(item) is not kind for item in items):
            raise TypeError("proposal collections must contain exact template types")
        result = {item.template_id: item for item in items}
        if len(result) != len(items):
            raise ValueError("duplicate template ID")
        return result


@dataclass(frozen=True)
class ContentRegistry:
    """Only validated template definitions, never live world or cognition state."""
    validator: ContentValidator
    _objects: dict[str, ObjectTemplate] = field(default_factory=dict, init=False, repr=False)
    _characters: dict[str, CharacterTemplate] = field(default_factory=dict, repr=False)
    _locations: dict[str, LocationTemplate] = field(default_factory=dict, repr=False)
    _scenarios: dict[str, ScenarioTemplate] = field(default_factory=dict, repr=False)

    def __post_init__(self) -> None:
        if type(self.validator) is not ContentValidator:
            raise TypeError("content registry requires the P0 ContentValidator")

    def register_generated(self, generator: ContentGenerator) -> None:
        """Invoke a generator once; its output gains no authority before validation."""
        self.register(generator.generate())

    def register(self, proposal: GenerationProposal) -> None:
        self.validator.validate(proposal)
        groups = ((self._characters, proposal.characters), (self._locations, proposal.locations),
                  (self._scenarios, proposal.scenarios), (self._objects, proposal.objects))
        if any(item.template_id in target for target, items in groups for item in items):
            raise ValueError("template ID already registered")
        for target, items in groups:
            target.update({item.template_id: item for item in items})

    def matches_registered(self, proposal: GenerationProposal) -> bool:
        """Return whether every validated definition already exists exactly."""
        self.validator.validate(proposal)
        groups = ((self._characters, proposal.characters),
                  (self._locations, proposal.locations),
                  (self._scenarios, proposal.scenarios), (self._objects, proposal.objects))
        return any(items for _, items in groups) and all(
            target.get(item.template_id) == item
            for target, items in groups for item in items
        )

    def conflicts_with_registered(self, proposal: GenerationProposal) -> bool:
        """Detect reused IDs whose immutable definitions differ."""
        self.validator.validate(proposal)
        groups = ((self._characters, proposal.characters),
                  (self._locations, proposal.locations),
                  (self._scenarios, proposal.scenarios), (self._objects, proposal.objects))
        return any(
            item.template_id in target and target[item.template_id] != item
            for target, items in groups for item in items
        )

    def has_registered_ids(self, proposal: GenerationProposal) -> bool:
        """Return whether any proposal ID is already owned by this registry."""
        self.validator.validate(proposal)
        groups = ((self._characters, proposal.characters),
                  (self._locations, proposal.locations),
                  (self._scenarios, proposal.scenarios), (self._objects, proposal.objects))
        return any(item.template_id in target for target, items in groups for item in items)

    def object(self, template_id):
        return self._objects[template_id]

    def scenario(self, template_id: str) -> ScenarioTemplate:
        return self._scenarios[template_id]

    def character(self, template_id: str) -> CharacterTemplate:
        return self._characters[template_id]

    def location(self, template_id: str) -> LocationTemplate:
        return self._locations[template_id]


@dataclass
class ContentInstantiator:
    registry: ContentRegistry

    def prepare(self, template_id: str, instance_id: str, world_id: str, *,
                world: WorldState, cognition: CognitionContainer,
                agents: AgentRegistry, clock: object | None = None) -> "ContentInstallationPlan":
        """Validate all identities and build isolated records without mutating authorities."""
        from cognitive_world.content.runtime import ScenarioPhase, ScenarioRuntimeState, scenario_state_key
        from cognitive_world.runtime.clock import SimulationClock

        for value in (instance_id, world_id):
            if not isinstance(value, str) or not value or len(value) > 160:
                raise ValueError("instance/world ID must be bounded and non-empty")
        if type(world) is not WorldState or type(cognition) is not CognitionContainer or type(agents) is not AgentRegistry:
            raise TypeError("installation requires canonical authorities")
        if clock is not None and type(clock) is not SimulationClock:
            raise TypeError("scenario creation time requires the trusted SimulationClock")
        scenario = self.registry.scenario(template_id)
        locations = tuple(LocationInstance(location_template_id,
            f"{world_id}:{instance_id}:location:{key}",
            tuple(f"{world_id}:{instance_id}:mechanism:{key}/{mechanism.local_id}"
                  for mechanism in self.registry.location(location_template_id).mechanisms))
            for key, location_template_id in scenario.locations)
        location_ids = {key: location.instance_id for (key, _), location in zip(scenario.locations, locations)}
        characters = tuple(CharacterInstance(character_template_id,
            f"{world_id}:{instance_id}:character:{key}",
            f"{world_id}:{instance_id}:agent:{key}", location_ids[location_key])
            for key, character_template_id, location_key in scenario.characters)
        object_ids = {key: f"{world_id}:{instance_id}:object:{key}" for key, _, _, _ in scenario.objects}
        actor_ids = {key: actor.agent_id for (key, _, _), actor in zip(scenario.characters, characters)}
        local_refs = {**{"location:" + k: v for k, v in location_ids.items()},
                      **{"actor:" + k: v for k, v in actor_ids.items()}}
        instance = ScenarioInstance(template_id, instance_id, world_id, locations, characters,
            location_ids[scenario.entry_key], tuple(location_ids[key] for key in scenario.exit_keys),
            scenario.event_seeds, scenario.side_branch, scenario.value_refs)
        state_key = scenario_state_key(world_id, instance_id)
        existing_entities, existing_environment, existing_locations = world.entities, world.environment, world.locations
        if state_key in world.facts:
            raise ValueError("scenario runtime identity already exists")
        if any(location.instance_id in existing_entities or any(mid in existing_environment for mid in location.mechanism_ids)
               for location in locations):
            raise ValueError("location or mechanism instance ID already exists")
        if any(character.agent_id in existing_entities or character.agent_id in existing_locations
               or agents.get(character.agent_id) is not None
               or cognition.get_personality(character.agent_id) is not None
               or cognition.get_self_model(character.agent_id) is not None
               or cognition.goal_store.get(character.agent_id) for character in characters):
            raise ValueError("character instance ID already exists")
        if any(oid in existing_entities or oid in existing_locations or oid in existing_environment for oid in object_ids.values()):
            raise ValueError("object instance ID already exists")
        planned_ids = [*location_ids.values(), *actor_ids.values(), *object_ids.values(),
                       *(mid for location in locations for mid in location.mechanism_ids)]
        if len(set(planned_ids)) != len(planned_ids) or any(
                identity in existing_entities or identity in existing_environment or identity in existing_locations
                or agents.get(identity) is not None for identity in planned_ids):
            raise ValueError("content runtime identity conflict")
        object_locations = []
        from cognitive_world.core.observation_range import ObservationZone, ObservationRangePolicy
        entities = []
        for location in locations:
            zone = self.registry.location(location.template_id).observation_zone
            attributes = {} if zone is None else {"observation_zone": ObservationZone(
                1, location_ids[zone.frame_id], zone.offset_m)}
            entities.append(Entity(location.instance_id, "location", attributes=attributes))
        for key, tid, place, owner in scenario.objects:
            template = self.registry.object(tid)
            oid = object_ids[key]
            attributes = {"appearance": template.appearance}
            policy = template.observation_policy
            if policy is not None:
                attributes["observation_policy"] = ObservationRangePolicy(1,
                    policy.coarse_distance_m, policy.detail_distance_m,
                    tuple(actor_ids[key] for key in policy.detail_observers))
            entities.append(Entity(oid, template.kind, attributes=attributes,
                                   owner_id=None if owner is None else local_refs[owner]))
            object_locations.append((oid, local_refs[place]))
        environment: list[tuple[str, DoorState | PassageState]] = []
        for location in locations:
            for mechanism, mid in zip(self.registry.location(location.template_id).mechanisms, location.mechanism_ids):
                if mechanism.kind == "door":
                    state = DoorState(mid, location.instance_id, mechanism.initially_open,
                                      mechanism.initially_locked, mechanism.operable,
                                      None if mechanism.key_ref is None else object_ids[mechanism.key_ref])
                else:
                    state = PassageState(mid, location.instance_id,
                        location_ids[mechanism.destination_key], mechanism.operable)
                environment.append((mid, state))
                if mechanism.interaction_policy is not None or mechanism.appearance_ref is not None:
                    attributes = {}
                    if mechanism.interaction_policy is not None:
                        attributes["interaction_policy"] = mechanism.interaction_policy
                    if mechanism.appearance_ref is not None:
                        template = self.registry.object(mechanism.appearance_ref)
                        attributes["appearance"] = template.appearance
                        policy = template.observation_policy
                        if policy is not None:
                            attributes["observation_policy"] = ObservationRangePolicy(1,
                                policy.coarse_distance_m, policy.detail_distance_m,
                                tuple(actor_ids[key] for key in policy.detail_observers))
                    # The physical mechanism and its observable representation
                    # share one canonical identity; this is not a second object.
                    entities.append(Entity(mid, mechanism.kind, attributes=attributes))
                    object_locations.append((mid, location.instance_id))
        personalities, self_models, goals, runtime_agents = [], [], [], []
        for character in characters:
            template = self.registry.character(character.template_id)
            goal_ids = [f"{character.agent_id}:goal:{index}" for index in range(len(template.goal_descriptions))]
            entities.append(Entity(character.agent_id, "character",
                sensory_capabilities=template.sensory_capabilities,
                physical_capabilities=template.physical_capabilities))
            personalities.append(Personality(character.agent_id))
            self_models.append(SelfModel(character.agent_id,
                capabilities={cap: True for cap in template.physical_capabilities}))
            goals.extend(Goal(goal_id, character.agent_id, description, 1.0, "active")
                         for goal_id, description in zip(goal_ids, template.goal_descriptions))
            runtime_agents.append(RuntimeAgent(character.agent_id, character.instance_id, goal_ids=goal_ids))
        state = ScenarioRuntimeState(world_id, instance_id, template_id,
            ScenarioPhase.AVAILABLE, instance.entry_location_id, instance.exit_location_ids,
            clock.capture().tick if clock is not None else None)
        return ContentInstallationPlan(instance, tuple(entities),
            tuple((character.agent_id, character.location_id) for character in characters) + tuple(object_locations),
            tuple(environment), state_key, state, tuple(personalities),
            tuple(self_models), tuple(goals), tuple(runtime_agents))

    def instantiate(self, template_id: str, instance_id: str, world_id: str, *,
                    world: WorldState, cognition: CognitionContainer,
                    agents: AgentRegistry, clock: object | None = None) -> ScenarioInstance:
        if world._initialization_sealed:
            raise PermissionError("runtime content changes require Resolution and EventProcessor")
        plan = self.prepare(template_id, instance_id, world_id, world=world,
            cognition=cognition, agents=agents, clock=clock)
        for entity in plan.entities:
            world.load_entity(entity)
        for key, value in plan.environment:
            world.load_environment_data(key, value)
        for actor_id, location_id in plan.locations:
            world.load_location(actor_id, location_id)
        for personality in plan.personalities:
            cognition.add_personality(personality)
        for self_model in plan.self_models:
            cognition.add_self_model(self_model)
        for goal in plan.goals:
            cognition.add_goal(goal)
        for agent in plan.agents:
            agents.register(agent)
        world.load_fact(plan.state_key, plan.state)
        return plan.instance

    @staticmethod
    def character_reference(instance: CharacterInstance, cognition: CognitionContainer) -> Character:
        goals = cognition.goal_store.get(instance.agent_id)
        return Character(instance.instance_id, instance.agent_id, instance.agent_id,
                         goal_ids=[goal.goal_id for goal in goals])


@dataclass(frozen=True)
class ContentInstallationPlan:
    """Prepared records for existing authorities; no installation capability."""
    instance: ScenarioInstance
    entities: tuple[Entity, ...]
    locations: tuple[tuple[str, str], ...]
    environment: tuple[tuple[str, DoorState | PassageState], ...]
    state_key: str
    state: object
    personalities: tuple[Personality, ...]
    self_models: tuple[SelfModel, ...]
    goals: tuple[Goal, ...]
    agents: tuple[RuntimeAgent, ...]
