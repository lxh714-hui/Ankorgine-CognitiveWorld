"""Fixed evaluation for lexical retrieval and the optional semantic channel.

The same corpus, gold labels, permissions, and top-five budget are retained.
The configured token-vector provider is test-only, not a model quality claim.
"""

import os
import re
from statistics import median
from time import perf_counter_ns

import pytest

from cognitive_world.agent import Character, CognitionContext
from cognitive_world.cognition import (
    CognitionContainer,
    Memory,
    MemoryQuery,
    MemoryRetriever,
    MemoryStore,
)
from cognitive_world.cognition.memory_semantic_retrieval import HybridMemoryRetriever
from cognitive_world.cognition.ollama_embedding import OllamaEmbeddingProvider


OWNER_ID = "agent-eval"
STANDARD_RESULT_LIMIT = 5


class CountingMemoryStore(MemoryStore):
    """Test-only read accounting; production retrieval APIs remain unchanged."""

    def __init__(self):
        super().__init__()
        self.read_ids = []

    def get_memory(self, memory_id):
        self.read_ids.append(memory_id)
        return super().get_memory(memory_id)


class CountingMemoryRetriever:
    """Records authorized candidate scans separately from context rechecks."""

    def __init__(self, store):
        self.store = store
        self._retriever = MemoryRetriever(store)
        self.candidate_scan_count = 0
        self.scan_store_read_count = 0

    def retrieve(self, query, *, allowed_memory_ids):
        before = len(self.store.read_ids)
        self.candidate_scan_count = len(dict.fromkeys(allowed_memory_ids))
        results = self._retriever.retrieve(query, allowed_memory_ids=allowed_memory_ids)
        self.scan_store_read_count = len(self.store.read_ids) - before
        return results


class ConfiguredTokenEmbedding:
    """Deterministic concept vectors with no lookup by Memory ID or gold label."""

    def __init__(self):
        self.vectors = {
            "watchman": (3.0, 0.0, 0.0),
            "sentry": (3.0, 0.0, 0.0),
            "north": (0.0, 2.0, 0.0),
            "northern": (0.0, 2.0, 0.0),
            "gate": (0.0, 0.0, 1.0),
            "entry": (0.0, 0.0, 1.0),
        }

    def embed(self, text):
        result = [0.0, 0.0, 0.0]
        for token in re.findall(r"[a-z]+", text.casefold()):
            vector = self.vectors.get(token)
            if vector is not None:
                result = [a + b for a, b in zip(result, vector, strict=True)]
        return tuple(result)


def _context(memories, *, refs=None, store_type=MemoryStore):
    store = store_type()
    for memory in memories:
        store._commit_memory(memory)
    character = Character(
        id="character-eval",
        agent_id=OWNER_ID,
        personality_id="personality-eval",
        memory_ids=(
            [memory.id for memory in memories if memory.owner_id == OWNER_ID]
            if refs is None else list(refs)
        ),
    )
    return CognitionContext.from_character(character, CognitionContainer(), store), store


def _recall_at_k(results, relevant_ids, k):
    relevant = set(relevant_ids)
    if not relevant:
        return 0.0
    found = {result.id for result in results[:k]} & relevant
    return len(found) / len(relevant)


def _reciprocal_rank(results, relevant_ids):
    relevant = set(relevant_ids)
    return next(
        (1.0 / rank for rank, result in enumerate(results, start=1) if result.id in relevant),
        0.0,
    )


def _fixed_evaluation_setup():
    memories = (
        Memory("m-key", OWNER_ID, "experience", "brass key under the map in the study", 0.7, "e-key"),
        Memory("m-door", OWNER_ID, "experience", "red door stuck in north corridor", 0.6, "e-door"),
        Memory("m-door-distractor", OWNER_ID, "experience", "red door above the corridor opened easily", 0.8, "e-door-distractor"),
        Memory("m-watchman", OWNER_ID, "experience", "watchman at north gate observed a traveler", 0.7, "e-gate-watch"),
        Memory("m-gate-dawn", OWNER_ID, "experience", "at dawn north gate was open", 0.5, "e-gate-dawn"),
        Memory("m-gate-dusk", OWNER_ID, "experience", "at dusk north gate was sealed", 0.8, "e-gate-dusk"),
        Memory("m-bridge-safe", OWNER_ID, "experience", "bridge was safe after storm inspection", 0.4, "e-bridge-a"),
        Memory("m-bridge-collapsed", OWNER_ID, "experience", "bridge collapsed after storm inspection", 0.9, "e-bridge-b"),
        Memory("m-token", OWNER_ID, "experience", "a bronze disk was logged beside the archive ledger", 0.6, "e-token-handoff"),
        Memory("m-ferry", OWNER_ID, "experience", "the harbor ferry departed before dawn", 0.5, "e-ferry"),
        # Deliberately similar, but absent from this Character's authorized links.
        Memory("m-unlinked", OWNER_ID, "experience", "sentry at the northern entry saw a traveler", 1.0, "e-private-unlinked"),
        Memory("m-other-owner", "agent-private", "experience", "sentry at the northern entry saw a traveler", 1.0, "e-private-owner"),
    )
    authorized_ids = tuple(memory.id for memory in memories if memory.id != "m-unlinked"
                          and memory.owner_id == OWNER_ID)
    context, store = _context(memories, refs=authorized_ids, store_type=CountingMemoryStore)
    retriever = CountingMemoryRetriever(store)
    context.memory_retriever = retriever
    cases = (
        {
            "case_id": "exact-lexical",
            "query": "brass key study",
            "relevant_ids": {"m-key"},
            "authorized_ids": authorized_ids,
            "association_note": None,
        },
        {
            "case_id": "paraphrase-shared-anchor",
            "query": "red entrance jammed",
            "relevant_ids": {"m-door"},
            "authorized_ids": authorized_ids,
            "association_note": None,
        },
        {
            "case_id": "paraphrase-single-overlap",
            "query": "stuck crimson doorway",
            "relevant_ids": {"m-door"},
            "authorized_ids": authorized_ids,
            "association_note": None,
        },
        {
            "case_id": "alias",
            "query": "sentry northern entry",
            "relevant_ids": {"m-watchman"},
            "authorized_ids": authorized_ids,
            # Gold annotation for a future entity-alias channel; not runtime data.
            "association_note": "sentry→watchman; northern entry→north gate",
        },
        {
            "case_id": "time-varying-state",
            "query": "at dusk north gate sealed",
            "relevant_ids": {"m-gate-dusk"},
            "authorized_ids": authorized_ids,
            "association_note": "same gate; e-gate-dawn precedes e-gate-dusk",
        },
        {
            "case_id": "conflicting-reports",
            "query": "bridge condition after storm",
            "relevant_ids": {"m-bridge-safe", "m-bridge-collapsed"},
            "authorized_ids": authorized_ids,
            "association_note": "retain both claims and source Event IDs; no truth label",
        },
        {
            "case_id": "indirect-event-association",
            "query": "librarian missing token",
            "relevant_ids": {"m-token"},
            "authorized_ids": authorized_ids,
            # Evaluation-only gold path, not an implemented graph or authority.
            "association_note": "entity:librarian→event:e-token-handoff→memory:m-token",
        },
    )
    no_answer_case = {
        "case_id": "no-answer",
        "query": "silver compass observatory roof",
        "relevant_ids": set(),
        "authorized_ids": authorized_ids,
    }

    return context, store, retriever, authorized_ids, cases, no_answer_case


def test_current_lexical_retrieval_has_reproducible_recall_at_five_and_ranking_baseline():
    context, store, retriever, authorized_ids, cases, no_answer_case = _fixed_evaluation_setup()
    results_by_query = {}
    metrics_by_query = {}
    for case in cases:
        store.read_ids.clear()
        started = perf_counter_ns()
        result = context.get_relevant_memories(
            MemoryQuery(OWNER_ID, case["query"], STANDARD_RESULT_LIMIT)
        )
        elapsed_ns = perf_counter_ns() - started
        results_by_query[case["case_id"]] = result
        metrics_by_query[case["case_id"]] = {
            "candidate_scan_count": retriever.candidate_scan_count,
            "candidate_scan_store_read_count": retriever.scan_store_read_count,
            "returned_count": len(result),
            "canonical_store_recheck_count": (
                len(store.read_ids) - retriever.scan_store_read_count
            ),
            "store_read_ids": tuple(store.read_ids),
            "elapsed_ns": elapsed_ns,
        }
    recall_at_5 = sum(
        _recall_at_k(results_by_query[case["case_id"]], case["relevant_ids"], 5)
        for case in cases
    ) / len(cases)
    mean_reciprocal_rank = sum(
        _reciprocal_rank(results_by_query[case["case_id"]], case["relevant_ids"])
        for case in cases
    ) / len(cases)

    assert results_by_query["exact-lexical"][0].id == "m-key"
    assert tuple(item.id for item in results_by_query["paraphrase-shared-anchor"][:2]) == (
        "m-door-distractor", "m-door",
    )
    assert results_by_query["paraphrase-single-overlap"][0].id == "m-door"
    assert results_by_query["alias"] == ()
    assert tuple(item.id for item in results_by_query["time-varying-state"])[0] == "m-gate-dusk"
    conflict_results = results_by_query["conflicting-reports"]
    assert {item.id for item in conflict_results} == {"m-bridge-safe", "m-bridge-collapsed"}
    assert {item.source_event for item in conflict_results} == {"e-bridge-a", "e-bridge-b"}
    assert results_by_query["indirect-event-association"] == ()
    assert all(len(result) <= STANDARD_RESULT_LIMIT for result in results_by_query.values())
    assert all(
        item.id in case["authorized_ids"]
        for case in cases
        for item in results_by_query[case["case_id"]]
    )

    store.read_ids.clear()
    started = perf_counter_ns()
    no_answer_result = context.get_relevant_memories(
        MemoryQuery(OWNER_ID, no_answer_case["query"], STANDARD_RESULT_LIMIT)
    )
    no_answer_elapsed_ns = perf_counter_ns() - started
    metrics_by_query[no_answer_case["case_id"]] = {
        "candidate_scan_count": retriever.candidate_scan_count,
        "candidate_scan_store_read_count": retriever.scan_store_read_count,
        "returned_count": len(no_answer_result),
        "canonical_store_recheck_count": len(store.read_ids) - retriever.scan_store_read_count,
        "store_read_ids": tuple(store.read_ids),
        "elapsed_ns": no_answer_elapsed_ns,
    }
    assert no_answer_result == ()
    assert not (set(item.id for item in no_answer_result) & no_answer_case["relevant_ids"])

    # The no-answer query is assessed separately and is not added to the
    # answerable-query Recall/MRR denominator, preserving the prior definition.
    returned_permission_violations = sum(
        item.id not in case["authorized_ids"]
        for case in cases
        for item in results_by_query[case["case_id"]]
    )
    permission_violations = returned_permission_violations + sum(
        memory_id not in authorized_ids
        for metrics in metrics_by_query.values()
        for memory_id in metrics["store_read_ids"]
    )
    assert permission_violations == 0
    assert all(
        metrics["candidate_scan_count"] == len(authorized_ids)
        for metrics in metrics_by_query.values()
    )
    assert all(
        metrics["candidate_scan_store_read_count"] == metrics["candidate_scan_count"]
        for metrics in metrics_by_query.values()
    )
    assert all(
        metrics["canonical_store_recheck_count"] == metrics["returned_count"]
        for metrics in metrics_by_query.values()
    )
    assert all(
        set(metrics["store_read_ids"]) <= set(authorized_ids)
        for metrics in metrics_by_query.values()
    )
    assert {
        case_id: metrics["returned_count"]
        for case_id, metrics in metrics_by_query.items()
    } == {
        "exact-lexical": 1,
        "paraphrase-shared-anchor": 2,
        "paraphrase-single-overlap": 1,
        "alias": 0,
        "time-varying-state": 4,
        "conflicting-reports": 2,
        "indirect-event-association": 0,
        "no-answer": 0,
    }
    assert sum(m["candidate_scan_count"] for m in metrics_by_query.values()) == 80
    assert sum(m["returned_count"] for m in metrics_by_query.values()) == 10
    assert sum(m["canonical_store_recheck_count"] for m in metrics_by_query.values()) == 10
    assert cases[3]["association_note"] is not None
    assert cases[6]["association_note"] is not None
    assert recall_at_5 == 5 / 7
    assert mean_reciprocal_rank == 9 / 14

    # Compare the same fixed corpus and gold without changing lexical results,
    # authorization, query limit, or the no-answer denominator.
    context.memory_retriever = HybridMemoryRetriever(
        store, ConfiguredTokenEmbedding(), minimum_similarity=0.8,
    )
    hybrid_results = {}
    hybrid_metrics = {}
    for case in (*cases, no_answer_case):
        store.read_ids.clear()
        started = perf_counter_ns()
        result = context.get_relevant_memories(
            MemoryQuery(OWNER_ID, case["query"], STANDARD_RESULT_LIMIT)
        )
        elapsed_ns = perf_counter_ns() - started
        hybrid_results[case["case_id"]] = result
        hybrid_metrics[case["case_id"]] = {
            "lexical_scan": len(authorized_ids),
            "semantic_scan": len(authorized_ids),
            "canonical_rechecks": len(store.read_ids) - 2 * len(authorized_ids),
            "store_read_ids": tuple(store.read_ids),
            "returned_count": len(result),
            "elapsed_ns": elapsed_ns,
        }
        assert len(result) <= STANDARD_RESULT_LIMIT
        assert all(item.id in authorized_ids for item in result)
        assert set(store.read_ids) <= set(authorized_ids)
    hybrid_recall = sum(
        _recall_at_k(hybrid_results[case["case_id"]], case["relevant_ids"], 5)
        for case in cases
    ) / len(cases)
    hybrid_mrr = sum(
        _reciprocal_rank(hybrid_results[case["case_id"]], case["relevant_ids"])
        for case in cases
    ) / len(cases)
    lexical_top_one = sum(
        bool(results_by_query[case["case_id"]])
        and results_by_query[case["case_id"]][0].id in case["relevant_ids"]
        for case in cases
    )
    hybrid_top_one = sum(
        bool(hybrid_results[case["case_id"]])
        and hybrid_results[case["case_id"]][0].id in case["relevant_ids"]
        for case in cases
    )
    hybrid_permission_violations = sum(
        memory_id not in authorized_ids
        for metric in hybrid_metrics.values()
        for memory_id in metric["store_read_ids"]
    )
    assert hybrid_results["alias"][0].id == "m-watchman"
    assert hybrid_results["indirect-event-association"] == ()
    assert hybrid_results["no-answer"] == ()
    assert hybrid_permission_violations == 0
    assert hybrid_recall == 6 / 7
    assert hybrid_mrr == 11 / 14
    assert hybrid_top_one == lexical_top_one + 1
    print(
        "fixed-corpus lexical:"
        f" Recall@5={recall_at_5:.6f} MRR={mean_reciprocal_rank:.6f}"
        f" Top1={lexical_top_one}/{len(cases)}"
        f" returned={sum(m['returned_count'] for m in metrics_by_query.values())}"
        f" scans={sum(m['candidate_scan_count'] for m in metrics_by_query.values())}"
        f" rechecks={sum(m['canonical_store_recheck_count'] for m in metrics_by_query.values())}"
        f" permission_violations={permission_violations}"
        f" median_ms={median(m['elapsed_ns'] for m in metrics_by_query.values()) / 1_000_000:.3f}"
    )
    print(
        "fixed-corpus hybrid:"
        f" Recall@5={hybrid_recall:.6f} MRR={hybrid_mrr:.6f}"
        f" Top1={hybrid_top_one}/{len(cases)}"
        f" returned={sum(m['returned_count'] for m in hybrid_metrics.values())}"
        f" lexical_scans={sum(m['lexical_scan'] for m in hybrid_metrics.values())}"
        f" semantic_scans={sum(m['semantic_scan'] for m in hybrid_metrics.values())}"
        f" rechecks={sum(m['canonical_rechecks'] for m in hybrid_metrics.values())}"
        f" permission_violations={hybrid_permission_violations}"
        f" median_ms={median(m['elapsed_ns'] for m in hybrid_metrics.values()) / 1_000_000:.3f}"
    )


def test_one_result_budget_reads_only_authorized_candidates_and_caps_context():
    authorized = tuple(
        Memory(f"m-{index}", OWNER_ID, "experience", f"red door note {index}", index / 10, f"e-{index}")
        for index in range(8)
    )
    memories = authorized + (
        Memory("m-unlinked", OWNER_ID, "experience", "red door private note", 1.0, "e-unlinked"),
        Memory("m-other-owner", "agent-private", "experience", "red door secret", 1.0, "e-private"),
    )
    context, store = _context(
        memories,
        refs=tuple(memory.id for memory in authorized),
        store_type=CountingMemoryStore,
    )
    retriever = CountingMemoryRetriever(store)
    context.memory_retriever = retriever

    results = context.get_relevant_memories(MemoryQuery(OWNER_ID, "red door", 1))

    assert len(results) == 1
    assert len(authorized) == 8  # authorized candidate scan; query result limit is one
    assert retriever.candidate_scan_count == len(authorized)
    assert retriever.scan_store_read_count == len(authorized)
    assert len(store.read_ids) - retriever.scan_store_read_count == 1  # canonical recheck
    assert len(store.read_ids) == 9
    assert sum(item.id not in {memory.id for memory in authorized} for item in results) == 0
    assert set(store.read_ids) == {memory.id for memory in authorized}
    assert "m-unlinked" not in store.read_ids
    assert "m-other-owner" not in store.read_ids


def test_optional_real_ollama_embedding_on_unchanged_fixed_corpus():
    """Explicit local-model quality probe; never part of unattended acceptance."""
    model = os.environ.get("COGNITIVEWORLD_OLLAMA_EMBEDDING_MODEL", "").strip()
    if not model:
        pytest.skip("set COGNITIVEWORLD_OLLAMA_EMBEDDING_MODEL for the local probe")
    url = os.environ.get("COGNITIVEWORLD_OLLAMA_EMBEDDING_URL", "http://127.0.0.1:11434")
    context, store, _, authorized_ids, cases, no_answer_case = _fixed_evaluation_setup()
    provider = OllamaEmbeddingProvider(url, model)

    class CountingProvider:
        batch_size = provider.batch_size

        def __init__(self):
            self.calls = 0
            self.texts = 0

        def embed(self, text):
            self.calls += 1
            self.texts += 1
            return provider.embed(text)

        def embed_many(self, texts):
            self.calls += 1
            self.texts += len(texts)
            return provider.embed_many(texts)

    first_start = perf_counter_ns()
    provider.embed("a synthetic warmup query")
    first_ms = (perf_counter_ns() - first_start) / 1_000_000
    warm_start = perf_counter_ns()
    provider.embed("a synthetic warmup query")
    warm_ms = (perf_counter_ns() - warm_start) / 1_000_000

    def measure(retriever):
        context.memory_retriever = retriever
        results = {}
        reads = 0
        elapsed = []
        for case in (*cases, no_answer_case):
            store.read_ids.clear()
            started = perf_counter_ns()
            result = context.get_relevant_memories(
                MemoryQuery(OWNER_ID, case["query"], STANDARD_RESULT_LIMIT)
            )
            elapsed.append((perf_counter_ns() - started) / 1_000_000)
            assert len(result) <= STANDARD_RESULT_LIMIT
            assert set(store.read_ids) <= set(authorized_ids)
            assert all(item.id in authorized_ids for item in result)
            reads += len(store.read_ids)
            results[case["case_id"]] = result
        metrics = (
            sum(_recall_at_k(results[c["case_id"]], c["relevant_ids"], 5) for c in cases) / len(cases),
            sum(_reciprocal_rank(results[c["case_id"]], c["relevant_ids"]) for c in cases) / len(cases),
            sum(bool(results[c["case_id"]]) and results[c["case_id"]][0].id in c["relevant_ids"] for c in cases),
        )
        return results, metrics, reads, median(elapsed), sum(len(items) for items in results.values())

    lexical = measure(MemoryRetriever(store))
    deterministic = measure(HybridMemoryRetriever(store, ConfiguredTokenEmbedding(), minimum_similarity=0.8))
    counter = CountingProvider()
    real = measure(HybridMemoryRetriever(store, counter, minimum_similarity=0.8))
    for label, (results, metrics, reads, median_ms, count) in (
        ("lexical", lexical), ("deterministic", deterministic), ("ollama", real)
    ):
        authorized_scans = len(authorized_ids) * len(results) * (
            1 if label == "lexical" else 2
        )
        print(
            f"{label}: Recall@5={metrics[0]:.6f} MRR={metrics[1]:.6f} "
            f"Top1={metrics[2]}/{len(cases)} returned={count} store_reads={reads} "
            f"authorized_scans={authorized_scans} "
            f"canonical_rechecks={reads - authorized_scans} "
            f"no_answer={tuple(item.id for item in results['no-answer'])} "
            f"alias={tuple(item.id for item in results['alias'])} "
            f"indirect={tuple(item.id for item in results['indirect-event-association'])} "
            f"median_ms={median_ms:.3f}"
        )
    print(
        f"ollama: warmup_first_ms={first_ms:.3f} warmup_next_ms={warm_ms:.3f} "
        f"provider_calls={counter.calls} embedded_texts={counter.texts} permission_violations=0"
    )
    assert lexical[1] == (5 / 7, 9 / 14, 4)
    assert deterministic[1] == (6 / 7, 11 / 14, 5)
    assert real[0]["no-answer"] == ()
