from copy import deepcopy

from cognitive_world.agent import Character, CognitionContext
from cognitive_world.cognition import Belief, CognitionContainer, CognitiveEvolutionEngine
from cognitive_world.cognition import MemoryStore
from cognitive_world.observation import Observation, ObservationStore
from tests._trusted_event_support import make_system_event
from tests._trusted_observation_support import make_trusted_observation


def test_default_belief_proposal_has_stable_changes_shape_and_is_detached():
    cognition = CognitionContainer()
    belief = Belief(
        belief_id="belief-1",
        owner_id="agent-1",
        content={"claim": "existing judgement"},
        source_refs=["event-old"],
        confidence=0.7,
    )
    cognition.add_belief(belief)
    character = Character(
        id="character-1",
        agent_id="agent-1",
        personality_id="personality-1",
        belief_ids=[belief.belief_id],
    )
    observation_store = ObservationStore()
    context = CognitionContext.from_character(
        character, cognition, MemoryStore(), observation_store=observation_store
    )
    stored_before = cognition.get_belief(belief.belief_id)
    event = make_system_event("event-1", "change", changes=[{"fact": "new"}])
    observation_store.add(
        make_trusted_observation("observation-1", "agent-1", event.id, {"detail": "seen"})
    )

    result = CognitiveEvolutionEngine().process(event, context)
    proposal = result.belief_update_proposals[0]

    assert proposal.change.proposed_value == {
        "claim": "existing judgement",
        "changes": [],
    }
    proposal.change.proposed_value["changes"].append("caller mutation")
    proposal.source_refs.append("caller mutation")

    assert cognition.get_belief(belief.belief_id) == stored_before
    assert belief == stored_before
