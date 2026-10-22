import pytest

from cognitive_world.agent import Character, CognitionContext
from cognitive_world.cognition import CognitionContainer, Memory, MemoryQuery, MemoryStore
from cognitive_world.cognition.memory_event_index import (
    MemoryEventCandidate,
    MemoryEventIndex,
)
from cognitive_world.cognition.memory_retrieval import MemoryRetriever, MemorySnapshot
from cognitive_world.cognition.memory_semantic_retrieval import HybridMemoryRetriever
from cognitive_world.core.event import Event
from cognitive_world.core.persistence import HmacPersistenceTrust, PersistedValueCodec
from cognitive_world.core.update import WorldUpdate
from cognitive_world.core.world_state import WorldState
from cognitive_world.event import EventHistory, EventProcessor, SystemEventFactory
from cognitive_world.event.handler import EventHandler
from cognitive_world.observation.observable import ObservableFactDraft
from cognitive_world.observation import Observation, ObservationStore
from cognitive_world.agent import AgentRegistry, RuntimeAgent, AgentActionLoop, AgentTurn
from cognitive_world.agent.action_loop import AgentTurnExecution
from cognitive_world.decision.action_proposal import ActionProposal
from cognitive_world.runtime import RuntimeContext, SimulationClock, SimulationRuntime


OWNER = "agent-index"
CODEC = PersistedValueCodec()


class _NoopHandler(EventHandler):
    def handle(self, event: Event) -> WorldUpdate:
        return WorldUpdate("facts", "update", {})


class _CountingStore(MemoryStore):
    def __init__(self):
        super().__init__()
        self.read_ids = []

    def get_memory(self, memory_id):
        self.read_ids.append(memory_id)
        return super().get_memory(memory_id)


class _CountingRetriever:
    def __init__(self, store):
        self.store = store
        self.delegate = MemoryRetriever(store)
        self.candidate_scan_count = 0
        self.scan_store_read_count = 0
        self.after_retrieve = None

    def retrieve(self, query, *, allowed_memory_ids):
        self.candidate_scan_count = len(dict.fromkeys(allowed_memory_ids))
        before = len(self.store.read_ids)
        result = self.delegate.retrieve(query, allowed_memory_ids=allowed_memory_ids)
        self.scan_store_read_count = len(self.store.read_ids) - before
        if self.after_retrieve is not None:
            self.after_retrieve()
        return result


class _CaptureDecision:
    def __init__(self):
        self.context = None

    def propose(self, context):
        self.context = context
        return ActionProposal("proposal:memory-index", OWNER, "wait")


class _CaptureProposalLoop(AgentActionLoop):
    def run_proposal_with_result(self, proposal, **_kwargs):
        return AgentTurnExecution(proposal, None, None, None)


class _DialogueFactHandler(EventHandler):
    def handle(self, event: Event) -> WorldUpdate:
        return WorldUpdate("facts", "update", {})

    def observable_facts(self, event: Event, update: WorldUpdate):
        return (ObservableFactDraft(
            "social_input", "utterance_delivered", event.metadata["utterance"],
            subject_ref=OWNER, location_id="room-index",
        ),)


def _runtime_with_trusted_dialogue(
    *, event_id="event-dialogue", utterance="the lantern is quiet",
    timeline_id="timeline:agent-turn-index",
):
    trust = HmacPersistenceTrust(b"memory-event-index-test-trust-key-0001")
    history = EventHistory(timeline_id=timeline_id)
    world = WorldState()
    world.load_location(OWNER, "room-index")
    store = ObservationStore()
    registry = AgentRegistry()
    agent = RuntimeAgent(OWNER, "character-index")
    registry.register(agent)
    clock = SimulationClock()
    processor = EventProcessor(
        event_history=history, world_state=world, simulation_clock=clock,
        agent_registry=registry, observation_store=store,
        persistence_trust=trust, persistence_codec=CODEC,
    )
    processor.register_handler("dialogue_input", _DialogueFactHandler())
    turn = AgentTurn()
    runtime = SimulationRuntime(
        RuntimeContext(clock, world, history, agent_registry=registry,
                       observation_store=store),
        event_processor=processor,
        agent_action_loop=AgentActionLoop(agent_turn=turn),
    )
    turn.write_fence = runtime.write_fence
    clock.advance(1)
    processor.dispatch_with_evidence(SystemEventFactory().create(
        event_id=event_id, event_type="dialogue_input", timestamp="t1",
        participants=[OWNER], simulation_tick=1,
        metadata={"utterance": utterance},
    ))
    return runtime, turn, agent, history, world, store, trust


def _verified_history(*event_ids):
    trust = HmacPersistenceTrust(b"memory-event-index-test-trust-key-0001")
    history = EventHistory(timeline_id="timeline:index-test")
    world = WorldState()
    processor = EventProcessor(
        event_history=history,
        world_state=world,
        persistence_codec=CODEC,
        persistence_trust=trust,
    )
    processor.register_handler("index-test", _NoopHandler())
    factory = SystemEventFactory()
    for tick, event_id in enumerate(event_ids, start=1):
        event = factory.create(
            event_id=event_id,
            event_type="index-test",
            timestamp=f"descriptive-time-{tick}",
            participants=["entity:unverified-as-a-world-reference"],
            simulation_tick=tick,
        )
        processor.process_with_evidence(event, world)
    history.verify_persisted_lineage(codec=CODEC, trust=trust)
    return history, trust


def _context(memories, *, refs, store_type=MemoryStore, owner=OWNER):
    store = store_type()
    for memory in memories:
        store._commit_memory(memory)
    character = Character(
        "character-index", owner, "personality-index", memory_ids=list(refs)
    )
    return CognitionContext.from_character(character, CognitionContainer(), store), store


def test_agent_turn_merges_lexical_semantic_and_verified_event_candidates():
    from cognitive_world.cognition.metacognition import MetacognitiveFeedback

    runtime, turn, agent, history, world, observations, _ = _runtime_with_trusted_dialogue()
    memories = (
        Memory("m-lexical", OWNER, "experience", "watchman report", 0.6, "event-lexical"),
        Memory("m-semantic", OWNER, "experience", "sentry report", 0.5, "event-semantic"),
        Memory("m-associated", OWNER, "experience", "librarian ceremony ledger", 0.7, "event-dialogue"),
    )
    memory_store = MemoryStore()
    for memory in memories:
        memory_store._commit_memory(memory)

    class _LocalEmbedding:
        def embed(self, text):
            return (1.0, 0.0) if "watchman" in text or "sentry" in text else (0.0, 0.0)

    context = CognitionContext.from_character(
        Character(
            "character-index", OWNER, "personality-index",
            memory_ids=[item.id for item in memories],
        ),
        CognitionContainer(), memory_store,
        observation_store=observations,
        metacognitive_feedback=MetacognitiveFeedback(
            OWNER, memory_queries=(MemoryQuery(OWNER, "watchman", 5),),
        ),
    )
    context.memory_retriever = HybridMemoryRetriever(memory_store, _LocalEmbedding())
    with runtime.write_fence.operation():
        first, _ = turn.prepare_decision_context(agent, context)
    assert tuple(item.id for item in first.long_term_memories) == (
        "m-lexical", "m-semantic", "m-associated",
    )

    world_before = (world.entities, world.locations, world.relationships,
                    world.facts, world.environment)
    history_before = history.get_events()
    memories_before = memory_store.get_all_memories()
    with runtime.write_fence.operation():
        second, _ = turn.prepare_decision_context(agent, context)
    assert tuple(item.id for item in second.long_term_memories) == (
        "m-lexical", "m-semantic", "m-associated",
    )
    assert (world.entities, world.locations, world.relationships,
            world.facts, world.environment) == world_before
    assert history.get_events() == history_before
    assert memory_store.get_all_memories() == memories_before


def test_memory_event_index_rebuilds_verified_source_links_with_time_and_scope():
    history, trust = _verified_history("event-1", "event-2")
    memories = (
        Memory("m-event-1-a", OWNER, "experience", "archive token record", 0.7, "event-1"),
        Memory("m-event-1-b", OWNER, "experience", "librarian ceremony", 0.6, "event-1"),
        Memory("m-event-2", OWNER, "experience", "harbor ferry", 0.5, "event-2"),
        Memory("m-orphan", OWNER, "experience", "unverified source", 0.9, "event-missing"),
        Memory("m-unlinked", OWNER, "experience", "private token", 1.0, "event-1"),
        Memory("m-other-owner", "agent-private", "experience", "private token", 1.0, "event-1"),
    )
    authorized = ("m-event-1-a", "m-event-1-b", "m-event-2", "m-orphan")
    context, store = _context(
        memories, refs=authorized, store_type=_CountingStore
    )

    index = MemoryEventIndex.rebuild_for_context(
        context, history, codec=CODEC, trust=trust
    )
    first = index.candidate_links(context, "event-1")
    second = index.candidate_links(context, "event-2")
    rebuilt = MemoryEventIndex.rebuild_for_context(
        context, history, codec=CODEC, trust=trust
    )

    assert first == rebuilt.candidate_links(context, "event-1")
    assert tuple(link.memory_id for link in first) == ("m-event-1-a", "m-event-1-b")
    assert tuple(link.memory_id for link in second) == ("m-event-2",)
    assert first[0].source_event_id == "event-1"
    assert first[0].event_timestamp == "descriptive-time-1"
    assert first[0].simulation_tick == 1
    assert first[0].history_position == 0
    assert first[0].evidence_status == "verified_persisted_event_history"
    assert "m-orphan" not in {link.memory_id for link in first + second}
    assert "m-unlinked" not in store.read_ids
    assert "m-other-owner" not in store.read_ids
    assert set(store.read_ids) <= set(authorized)


def test_unverified_history_and_nonexistent_event_cannot_create_index_links():
    trust = HmacPersistenceTrust(b"memory-event-index-test-trust-key-0001")
    history = EventHistory(timeline_id="timeline:index-test")
    unprocessed = SystemEventFactory().create(
        event_id="event-unverified", event_type="index-test", timestamp="t1"
    )
    history.append(unprocessed)
    context, _ = _context(
        (Memory("m-unverified", OWNER, "experience", "unverified", 0.4, unprocessed.id),),
        refs=("m-unverified",),
    )

    with pytest.raises(PermissionError, match="not durably attestable"):
        MemoryEventIndex.rebuild_for_context(context, history, codec=CODEC, trust=trust)

    verified_history, verified_trust = _verified_history("event-known")
    empty_context, _ = _context((), refs=())
    index = MemoryEventIndex.rebuild_for_context(
        empty_context, verified_history, codec=CODEC, trust=verified_trust
    )
    assert index.candidate_links(empty_context, "event-does-not-exist") == ()
    assert index.resolve_event_candidates(empty_context, "event-known") == ()
    with pytest.raises(PermissionError, match="must be built"):
        MemoryEventIndex(
            owner_id=OWNER,
            memory_store=empty_context.memory_store,
            authorized_memory_ids=frozenset(),
            verified_event_ids=frozenset({"forged-event"}),
            event_to_links={},
            _issuer=object(),
        )


def test_event_candidates_recheck_store_merge_dedupe_and_obey_scope_and_limit():
    history, trust = _verified_history("event-token")
    memories = (
        Memory("m-lexical", OWNER, "experience", "archive token record", 0.7, "event-token"),
        Memory("m-associated", OWNER, "experience", "librarian ceremony", 0.6, "event-token"),
        Memory("m-unlinked", OWNER, "experience", "private archive", 1.0, "event-token"),
        Memory("m-private", "agent-private", "experience", "private archive", 1.0, "event-token"),
    )
    context, store = _context(
        memories,
        refs=("m-lexical", "m-associated"),
        store_type=_CountingStore,
    )
    index = MemoryEventIndex.rebuild_for_context(
        context, history, codec=CODEC, trust=trust
    )
    lexical = context.get_relevant_memories(MemoryQuery(OWNER, "archive", 5))
    store.read_ids.clear()
    associated = index.resolve_event_candidates(context, "event-token", limit=5)

    assert tuple(item.memory.id for item in associated) == ("m-associated", "m-lexical")
    assert tuple(store.read_ids) == ("m-associated", "m-lexical")
    assert all(isinstance(item.memory, MemorySnapshot) for item in associated)
    assert all(item.memory.source_event == item.link.source_event_id for item in associated)
    assert all(item.link.simulation_tick == 1 for item in associated)
    merged = index.merge_candidates(context, lexical, associated, limit=1)
    assert tuple(item.id for item in merged) == ("m-lexical",)
    merged_all = index.merge_candidates(context, lexical, associated, limit=5)
    assert tuple(item.id for item in merged_all) == ("m-lexical", "m-associated")
    assert {item.source_event for item in merged_all} == {"event-token"}
    forged_candidate = MemoryEventCandidate(
        MemorySnapshot(
            "m-associated", OWNER, "experience", "forged text", 1.0,
            "event-token", {},
        ),
        associated[0].link,
    )
    canonicalized = index.merge_candidates(context, (), (forged_candidate,), limit=5)
    assert canonicalized[0].content == "librarian ceremony"
    assert not ({"m-unlinked", "m-private"} & {item.id for item in merged_all})
    assert index.resolve_event_candidates(context, "event-token", limit=99) == associated


def test_missing_index_or_anchor_keeps_lexical_path_and_no_answer_behavior():
    history, trust = _verified_history("event-known")
    memory = Memory("m-known", OWNER, "experience", "brass key in archive", 0.5, "event-known")
    context, _ = _context((memory,), refs=(memory.id,))
    lexical = context.get_relevant_memories(MemoryQuery(OWNER, "brass key", 5))
    index = MemoryEventIndex.rebuild_for_context(
        context, history, codec=CODEC, trust=trust
    )

    assert tuple(item.id for item in lexical) == (memory.id,)
    assert index.resolve_event_candidates(context, None) == ()
    assert index.resolve_event_candidates(context, "event-missing") == ()
    assert context.get_relevant_memories(
        MemoryQuery(OWNER, "silver compass observatory roof", 5)
    ) == ()


def test_agent_turn_uses_only_current_verified_observation_anchors_and_keeps_reads_pure():
    from cognitive_world.cognition import Memory

    runtime, turn, agent, history, world, observations, trust = _runtime_with_trusted_dialogue()
    memory = Memory(
        "m-event-associated", OWNER, "experience",
        "librarian ceremony ledger", 0.7, "event-dialogue",
    )
    memory_store = _CountingStore()
    memory_store._commit_memory(memory)
    cognition_container = CognitionContainer()
    context = CognitionContext.from_character(
        Character("character-index", OWNER, "personality-index", memory_ids=[memory.id]),
        cognition_container, memory_store, observation_store=observations,
    )
    retriever = _CountingRetriever(memory_store)
    context.memory_retriever = retriever

    with runtime.write_fence.operation():
        decision_context, _ = turn.prepare_decision_context(agent, context)
    assert tuple(item.id for item in decision_context.long_term_memories) == (memory.id,)
    assert decision_context.long_term_memories[0].source_event == "event-dialogue"
    query_snapshot = decision_context.metacognitive_feedback.memory_queries[0]
    query = MemoryQuery(OWNER, query_snapshot.query, query_snapshot.limit)
    lexical_baseline = context.get_relevant_memories(query)
    assert lexical_baseline == ()

    # The first L1 pass may issue its separate consumption proof. From this
    # point onward, retrieval itself must not mutate canonical state.
    world_before = (world.entities, world.locations, world.relationships,
                    world.facts, world.environment)
    history_before = history.get_events()
    memories_before = memory_store.get_all_memories()
    beliefs_before = cognition_container.belief_store.get_all()
    goals_before = cognition_container.goal_store.get_all()
    memory_store.read_ids.clear()
    capture_decision = _CaptureDecision()
    capture_loop = _CaptureProposalLoop(agent_turn=turn)
    with runtime.write_fence.operation():
        capture_loop.run_turn_with_result(
            agent, context, capture_decision,
            cognitive_review_provider=object(),
        )
    second_context = capture_decision.context
    assert second_context is not None
    assert tuple(item.id for item in second_context.long_term_memories) == (memory.id,)
    assert (world.entities, world.locations, world.relationships,
            world.facts, world.environment) == world_before
    assert history.get_events() == history_before
    assert memory_store.get_all_memories() == memories_before
    assert cognition_container.belief_store.get_all() == beliefs_before
    assert cognition_container.goal_store.get_all() == goals_before
    assert retriever.candidate_scan_count == 1
    assert retriever.scan_store_read_count == 1
    assert memory_store.read_ids == [memory.id] * 4
    assert all(item in context._memory_ids for item in memory_store.read_ids)
    assert len(second_context.long_term_memories) <= 5
    relevant_ids = {memory.id}
    ranked_ids = tuple(item.id for item in second_context.long_term_memories)
    recall_at_5 = len(set(ranked_ids[:5]) & relevant_ids) / len(relevant_ids)
    reciprocal_rank = next(
        (1 / rank for rank, item_id in enumerate(ranked_ids, start=1)
         if item_id in relevant_ids),
        0.0,
    )
    assert recall_at_5 == 1.0
    assert reciprocal_rank == 1.0


def test_agent_turn_rejects_forged_or_wrong_timeline_observation_anchor():
    from cognitive_world.cognition import Memory
    from cognitive_world.cognition.metacognition import MetacognitiveFeedback

    runtime, turn, agent, history, _, observations, trust = _runtime_with_trusted_dialogue()
    memory_store = MemoryStore()
    memory = Memory(
        "m-event-associated", OWNER, "experience",
        "librarian ceremony ledger", 0.7, "event-dialogue",
    )
    memory_store._commit_memory(memory)
    # The query is explicit and unrelated to the stored Memory. Without a
    # valid Observation anchor it must retain the ordinary lexical no-answer.
    forged_store = ObservationStore()
    forged_store.add(Observation(
        "forged", OWNER, "event-dialogue",
        ObservableFactDraft("social_input", "utterance_delivered", "the lantern is quiet"),
    ))
    context = CognitionContext.from_character(
        Character("character-index", OWNER, "personality-index", memory_ids=[memory.id]),
        CognitionContainer(), memory_store,
        observation_store=forged_store,
        metacognitive_feedback=MetacognitiveFeedback(
            OWNER, memory_queries=(MemoryQuery(OWNER, "unrelated query", 5),),
        ),
    )
    with runtime.write_fence.operation():
        forged_context, _ = turn.prepare_decision_context(agent, context)
    assert forged_context.long_term_memories == ()

    # A valid Observation from another timeline with the same Event ID is not
    # enough: its processor-issued fact receipt is bound to that other Event.
    _, _, _, foreign_history, _, foreign_observations, _ = (
        _runtime_with_trusted_dialogue(
            event_id="event-dialogue", utterance="the lantern is quiet",
            timeline_id="timeline:foreign-agent-turn-index",
        )
    )
    foreign = foreign_observations.get_by_observer(OWNER)[0]
    assert foreign.has_trusted_provenance()
    assert foreign_history.timeline_id != history.timeline_id

    # An anchor from an earlier index generation cannot be replayed into a
    # freshly rebuilt generation, even while the underlying Event remains.
    current_context, store = _context((memory,), refs=(memory.id,))
    first_index = MemoryEventIndex.rebuild_for_context(
        current_context, history, codec=CODEC, trust=trust,
        runtime_fence=runtime.write_fence,
    )
    trusted_observation = observations.get_by_observer(OWNER)[0]
    from cognitive_world.cognition.runtime import CognitiveRuntime

    foreign_runtime = CognitiveRuntime()
    foreign_percepts = tuple(
        foreign_runtime.process(OWNER, (foreign,)).percepts
    )
    assert first_index.verified_observation_anchors(
        current_context, (foreign,), consumed_percepts=foreign_percepts,
        cognitive_runtime=foreign_runtime,
    ) == ()

    cognitive_runtime = CognitiveRuntime()
    percepts = tuple(cognitive_runtime.process(OWNER, (trusted_observation,)).percepts)
    anchors = first_index.verified_observation_anchors(
        current_context, (trusted_observation,), consumed_percepts=percepts,
        cognitive_runtime=cognitive_runtime,
    )
    second_index = MemoryEventIndex.rebuild_for_context(
        current_context, history, codec=CODEC, trust=trust,
        runtime_fence=runtime.write_fence,
    )
    assert second_index.resolve_anchor_candidates(current_context, anchors) == ()
    history.append(Event("event-added-after-index", "unattested", "t2"))
    with pytest.raises(PermissionError, match="changed after the retrieval index was verified"):
        second_index.resolve_anchor_candidates(current_context, ())


def test_agent_turn_index_verification_failure_keeps_lexical_retrieval_and_marks_unavailable():
    from cognitive_world.agent import AgentTurn, RuntimeAgent
    from cognitive_world.cognition import Memory
    from cognitive_world.cognition.metacognition import MetacognitiveFeedback

    trust = HmacPersistenceTrust(b"memory-event-index-test-trust-key-0001")
    history = EventHistory(timeline_id="timeline:unattested-index")
    history.append(Event("event-unattested-index", "legacy", "t1"))
    memory = Memory(
        "m-lexical-fallback", OWNER, "experience", "lantern archive ledger",
        0.5, "event-unattested-index",
    )
    store = MemoryStore()
    store._commit_memory(memory)
    context = CognitionContext.from_character(
        Character("character-index", OWNER, "personality-index", memory_ids=[memory.id]),
        CognitionContainer(), store,
        metacognitive_feedback=MetacognitiveFeedback(
            OWNER, memory_queries=(MemoryQuery(OWNER, "lantern archive", 5),),
        ),
    )
    turn = AgentTurn()
    from cognitive_world.runtime.write_fence import RuntimeWriteFence

    turn._bind_memory_event_verifier(
        history=history, codec=CODEC, trust=trust, fence=RuntimeWriteFence(),
    )
    decision_context, _ = turn.prepare_decision_context(
        RuntimeAgent(OWNER, "character-index"), context,
    )
    assert tuple(item.id for item in decision_context.long_term_memories) == (memory.id,)
    assert any(
        "Event-linked Memory retrieval was unavailable" in cue
        for cue in decision_context.metacognitive_feedback.review_cues
    )


def test_observation_from_prior_runtime_generation_cannot_anchor_same_event():
    from cognitive_world.cognition import Memory
    from cognitive_world.cognition.metacognition import MetacognitiveFeedback

    timeline_id = "timeline:reused-event-across-runtime"
    old_runtime, _, _, old_history, _, old_store, _ = _runtime_with_trusted_dialogue(
        event_id="event-reused-runtime", timeline_id=timeline_id,
    )
    old_observation = old_store.get_by_observer(OWNER)[0]
    new_runtime, turn, agent, new_history, _, _, _ = _runtime_with_trusted_dialogue(
        event_id="event-reused-runtime", timeline_id=timeline_id,
    )
    assert old_runtime.write_fence.session_id != new_runtime.write_fence.session_id
    assert old_history.timeline_id == new_history.timeline_id
    assert old_observation.source_event_id == new_history.get_events()[0].id

    reused_observation_store = ObservationStore()
    reused_observation_store.add(old_observation)
    memory = Memory(
        "m-reused-runtime", OWNER, "experience", "librarian ceremony ledger",
        0.5, "event-reused-runtime",
    )
    memory_store = MemoryStore()
    memory_store._commit_memory(memory)
    context = CognitionContext.from_character(
        Character("character-index", OWNER, "personality-index", memory_ids=[memory.id]),
        CognitionContainer(), memory_store,
        observation_store=reused_observation_store,
        metacognitive_feedback=MetacognitiveFeedback(
            OWNER, memory_queries=(MemoryQuery(OWNER, "silver compass observatory", 5),),
        ),
    )

    with new_runtime.write_fence.operation():
        decision_context, _ = turn.prepare_decision_context(agent, context)

    assert old_observation.has_trusted_provenance()
    assert decision_context.long_term_memories == ()
    assert any(
        "Event-linked Memory retrieval was unavailable" in cue
        for cue in decision_context.metacognitive_feedback.review_cues
    )


def test_observation_cannot_be_reused_after_runtime_fence_generation_advances():
    from cognitive_world.cognition import Memory
    from cognitive_world.cognition.metacognition import MetacognitiveFeedback

    runtime, turn, agent, _, _, observations, _ = _runtime_with_trusted_dialogue(
        event_id="event-stale-generation",
        timeline_id="timeline:stale-generation",
    )
    memory = Memory(
        "m-stale-generation", OWNER, "experience", "librarian ceremony ledger",
        0.5, "event-stale-generation",
    )
    memory_store = MemoryStore()
    memory_store._commit_memory(memory)
    context = CognitionContext.from_character(
        Character("character-index", OWNER, "personality-index", memory_ids=[memory.id]),
        CognitionContainer(), memory_store,
        observation_store=observations,
        metacognitive_feedback=MetacognitiveFeedback(
            OWNER, memory_queries=(MemoryQuery(OWNER, "silver compass observatory", 5),),
        ),
    )

    with runtime.write_fence.operation():
        before_advance, _ = turn.prepare_decision_context(agent, context)
    assert tuple(item.id for item in before_advance.long_term_memories) == (memory.id,)

    runtime.write_fence.freeze_and_advance()
    runtime.write_fence.unfreeze()
    with runtime.write_fence.operation():
        after_advance, _ = turn.prepare_decision_context(agent, context)
    assert after_advance.long_term_memories == ()
    assert any(
        "Event-linked Memory retrieval was unavailable" in cue
        for cue in after_advance.metacognitive_feedback.review_cues
    )


def test_agent_turn_falls_back_to_lexical_results_if_runtime_generation_changes_mid_query():
    from cognitive_world.cognition import Memory
    from cognitive_world.cognition.metacognition import MetacognitiveFeedback

    runtime, turn, agent, history, _, observations, _ = _runtime_with_trusted_dialogue()
    associated = Memory(
        "m-generation-associated", OWNER, "experience",
        "an unrelated account of an old observance", 0.7, "event-dialogue",
    )
    lexical = Memory(
        "m-generation-lexical", OWNER, "experience",
        "silver cup market", 0.6, "event-not-used-as-anchor",
    )
    memory_store = _CountingStore()
    memory_store._commit_memory(associated)
    memory_store._commit_memory(lexical)
    context = CognitionContext.from_character(
        Character(
            "character-index", OWNER, "personality-index",
            memory_ids=[associated.id, lexical.id],
        ),
        CognitionContainer(), memory_store,
        observation_store=observations,
        metacognitive_feedback=MetacognitiveFeedback(
            OWNER,
            memory_queries=(MemoryQuery(OWNER, "silver cup market", 5),),
        ),
    )
    retriever = _CountingRetriever(memory_store)
    context.memory_retriever = retriever

    def advance_runtime_generation():
        runtime.write_fence.freeze_and_advance()
        runtime.write_fence.unfreeze()

    retriever.after_retrieve = advance_runtime_generation
    decision = _CaptureDecision()
    loop = _CaptureProposalLoop(agent_turn=turn)
    with runtime.write_fence.operation():
        loop.run_turn_with_result(agent, context, decision)

    assert decision.context is not None
    assert tuple(item.id for item in decision.context.long_term_memories) == (lexical.id,)
    assert associated.id not in {item.id for item in decision.context.long_term_memories}
    assert any(
        "Event-linked Memory retrieval became unavailable" in cue
        for cue in decision.context.metacognitive_feedback.review_cues
    )


def test_memory_event_index_fixed_size_scaling_measurement():
    from statistics import median
    from time import perf_counter_ns
    import json
    from cognitive_world.cognition import Memory

    repetitions = 7
    warmups = 2
    event_counts = (128, 512)
    memory_counts = (32, 128)
    histories = {
        count: _verified_history(*(
            f"bench-event-{count}-{index}" for index in range(count)
        ))
        for count in event_counts
    }
    measurements = []
    for event_count in event_counts:
        history, trust = histories[event_count]
        event_ids = tuple(event.id for event in history.get_events())
        for memory_count in memory_counts:
            memories = tuple(
                Memory(
                    f"bench-memory-{event_count}-{memory_count}-{index}",
                    OWNER, "experience", f"record {index}", 0.5,
                    event_ids[index % min(event_count, 8)],
                )
                for index in range(memory_count)
            )
            context, store = _context(
                memories,
                refs=tuple(memory.id for memory in memories),
                store_type=_CountingStore,
            )
            samples = {
                "complete_history_verification": [],
                "authorized_memory_scan": [],
                "index_build": [],
                "full_history_fingerprint": [],
                "candidate_link_lookup": [],
                "canonical_store_recheck": [],
            }
            last_index = None

            def measure(operation, *, reads_expected=None):
                store.read_ids.clear()
                started = perf_counter_ns()
                result = operation()
                elapsed_ms = (perf_counter_ns() - started) / 1_000_000
                if reads_expected is not None:
                    assert len(store.read_ids) == reads_expected
                return result, elapsed_ms

            def verify_history():
                return history.verify_persisted_lineage(codec=CODEC, trust=trust)

            def scan_authorized_memories():
                return tuple(
                    memory
                    for memory_id in dict.fromkeys(context._memory_ids)
                    if (memory := store.get_memory(memory_id)) is not None
                    and memory.owner_id == OWNER
                    and MemoryStore.is_semantically_retrievable(memory)
                )

            build = lambda: MemoryEventIndex.rebuild_for_context(
                context, history, codec=CODEC, trust=trust,
            )
            fingerprint = lambda: MemoryEventIndex._fingerprint_history(history)
            link_lookup = lambda: last_index.candidate_links(
                context, event_ids[0], limit=5,
            )
            canonical_resolve = lambda: last_index.resolve_event_candidates(
                context, event_ids[0], limit=5,
            )

            for repetition in range(warmups + repetitions):
                _, verify_ms = measure(verify_history)
                _, scan_ms = measure(
                    scan_authorized_memories, reads_expected=memory_count,
                )
                current_index, build_ms = measure(
                    build, reads_expected=memory_count,
                )
                _, fingerprint_ms = measure(fingerprint)
                last_index = current_index
                links, lookup_ms = measure(link_lookup, reads_expected=0)
                candidates, recheck_ms = measure(canonical_resolve)

                expected_candidates = min((memory_count + 7) // 8, 5)
                assert len(current_index.verified_event_ids) == event_count
                assert len(links) == expected_candidates
                assert len(candidates) == expected_candidates
                assert len(store.read_ids) == expected_candidates
                assert all(
                    item.memory.owner_id == OWNER
                    and item.memory.id in context._memory_ids
                    for item in candidates
                )
                if repetition >= warmups:
                    samples["complete_history_verification"].append(verify_ms)
                    samples["authorized_memory_scan"].append(scan_ms)
                    samples["index_build"].append(build_ms)
                    samples["full_history_fingerprint"].append(fingerprint_ms)
                    samples["candidate_link_lookup"].append(lookup_ms)
                    samples["canonical_store_recheck"].append(recheck_ms)

            def summarize(values):
                ordered = sorted(values)
                p90 = ordered[(9 * len(ordered) + 9) // 10 - 1]
                return {
                    "median_ms": round(median(ordered), 4),
                    "p90_ms": round(p90, 4),
                }

            measurements.append({
                "events_verified_per_build": event_count,
                "authorized_memory_ids_scanned_per_build": memory_count,
                "warmups": warmups,
                "repetitions": repetitions,
                "timings": {
                    name: summarize(values) for name, values in samples.items()
                },
                "canonical_store_rechecks_per_query": len(candidates),
                "returned_candidates": len(candidates),
                "permission_violations": 0,
            })

    print("MEMORY_EVENT_INDEX_BENCH " + json.dumps(measurements, sort_keys=True))
    assert len(measurements) == 4
