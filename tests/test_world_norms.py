import pytest

from cognitive_world.core.event import Event
from cognitive_world.core.world_state import WorldState
from cognitive_world.event.factory import SystemEventFactory
from cognitive_world.event.history import EventHistory
from cognitive_world.event.processor import EventProcessor
from cognitive_world.safety.governance import UniversalSafetyGovernance
from cognitive_world.world_norms.models import (
    GovernanceStatus,
    NormRule,
    NormVersion,
    WorldNorms,
    WorldNormsGenerationPipeline,
    parse_world_norms,
    project_public_norms,
    applicable_norm_rules,
)
from cognitive_world.runtime.clock import SimulationClock


def make_norms(*, hidden=False):
    public = NormRule("law:entry", "Entry hours", "The gate closes at dusk.", "Entry is restricted after dusk.", ("district",))
    private = NormRule("law:hidden", "Secret rule", "Hidden summary", "Hidden details.", ("district",), is_public=False)
    social = NormRule("custom:greeting", "Greeting custom", "Residents exchange greetings.", "A customary greeting is expected.", ("district",))
    version = NormVersion("v1", 0, None, (public, private), (social,))
    return WorldNorms(
        "world-a", GovernanceStatus.FORMAL_LAW, "Harbor Council",
        (("district", "Old Harbor"),), "Review before penalty.",
        ("Harbor Watch",), "Law and morality are distinct.", (version,),
        "v1", "This world includes legal and social conflict.",
    )


def test_public_projection_is_read_only_foldable_structured_and_hides_private_rules():
    projection = project_public_norms(make_norms(), safety_governance=UniversalSafetyGovernance())
    assert projection.world_notice
    assert projection.version_id == "v1"
    assert [rule.stable_id for rule in projection.legal_rules] == ["law:entry"]
    assert projection.legal_rules[0].applicable_regions == (("district", "Old Harbor"),)
    assert projection.social_norms[0].stable_id == "custom:greeting"
    assert not hasattr(projection, "expanded_rule_ids")


def test_world_without_formal_law_is_explicit_and_does_not_force_judicial_system():
    norms = WorldNorms(
        "village", GovernanceStatus.NO_FORMAL_LAW, None, (),
        "Disputes are handled through local mediation.", (),
        "Custom and moral expectations are not formal law.",
        (NormVersion("v1", 0, None, (), ()),), "v1", "No formal legal code exists.",
    )
    assert project_public_norms(norms, safety_governance=UniversalSafetyGovernance()).legal_rules == ()


def test_no_formal_law_rejects_invented_formal_rules():
    rule = NormRule("law", "Rule", "Summary", "Detail")
    with pytest.raises(ValueError, match="no-formal-law"):
        WorldNorms(
            "village", GovernanceStatus.NO_FORMAL_LAW, None, (), "Process", (), "Difference",
            (NormVersion("v1", 0, None, (rule,), ()),), "v1", "Notice",
        )


def test_generation_pipeline_rejects_unknown_schema_fields_and_world_identity():
    pipeline = WorldNormsGenerationPipeline(UniversalSafetyGovernance())
    with pytest.raises(ValueError, match="schema"):
        pipeline.generate({"world_id": "world-a", "safety_disabled": True}, world_id="world-a")


def test_structured_generation_creates_world_norms_after_validation():
    pipeline = WorldNormsGenerationPipeline(UniversalSafetyGovernance())
    source = {
        "world_id": "world-a",
        "governance_status": "formal_law",
        "lawmaking_authority": "Harbor Council",
        "jurisdictions": [{"id": "district", "name": "Old Harbor"}],
        "responsibility_and_process": "A review precedes penalties.",
        "enforcement_or_governance_bodies": ["Harbor Watch"],
        "law_morality_distinction": "Legality and morality are distinct.",
        "versions": [{
            "version_id": "v1", "effective_from_tick": 0, "effective_until_tick": None,
            "legal_rules": [{
                "rule_id": "entry-hours", "title": "Entry hours", "summary": "The gate closes at dusk.",
                "detail": "Entry is restricted after dusk.", "jurisdiction_ids": ["district"],
                "status": "active", "is_public": True, "children": [],
                "conduct_scope": "after-dusk entry", "normative_force": "regulate",
            }],
            "social_norms": [],
        }],
        "active_version_id": "v1",
        "player_notice": "This world contains legal and social conflict.",
        "content_hints": [],
    }
    norms = pipeline.generate(source, world_id="world-a")
    assert norms.active_version_id == "v1"
    assert applicable_norm_rules(norms, jurisdiction_id="district", simulation_tick=0)[0][0].rule_id == "entry-hours"


def test_norm_query_observes_effective_version_and_never_assigns_global_knowledge():
    old = make_norms()
    first = old.active_version
    previous = NormVersion(first.version_id, first.effective_from_tick, 10, first.legal_rules, first.social_norms)
    second = NormVersion("v2", 10, None, (), first.social_norms)
    changed = WorldNorms(
        old.world_id, old.governance_status, old.lawmaking_authority, old.jurisdictions,
        old.responsibility_and_process, old.enforcement_or_governance_bodies,
        old.law_morality_distinction, (previous, second), "v2", old.player_notice,
    )
    assert applicable_norm_rules(changed, jurisdiction_id="district", simulation_tick=9)[0]
    assert applicable_norm_rules(changed, jurisdiction_id="district", simulation_tick=10)[0] == ()
    # This query returns world rule records only. Agent knowledge still requires
    # the normal Observation and Cognition path.


def test_public_projection_does_not_disclose_hidden_nested_rules():
    parent = NormRule(
        "public", "Public", "Summary", "Details", children=(
            NormRule("secret-child", "Hidden child", "Private", "Secret", is_public=False),
        ),
    )
    norms = WorldNorms(
        "world-a", GovernanceStatus.CUSTOMARY_GOVERNANCE, None, (), "Process", (), "Difference",
        (NormVersion("v1", 0, None, (), (parent,)),), "v1", "Notice",
    )
    projection = project_public_norms(norms, safety_governance=UniversalSafetyGovernance())
    assert projection.social_norms[0].children == ()


def test_public_projection_requires_explicit_safety_governance():
    with pytest.raises(TypeError):
        project_public_norms(make_norms())


def test_world_norms_system_event_updates_active_version_through_event_processor():
    old = make_norms()
    previous = old.active_version
    closed = NormVersion(previous.version_id, previous.effective_from_tick, 10, previous.legal_rules, previous.social_norms)
    next_version = NormVersion("v2", 10, None, previous.legal_rules, previous.social_norms)
    new = WorldNorms(
        old.world_id, old.governance_status, old.lawmaking_authority, old.jurisdictions,
        old.responsibility_and_process, old.enforcement_or_governance_bodies,
        old.law_morality_distinction, (closed, next_version), "v2", old.player_notice,
    )
    world = WorldState()
    world.load_world_norms(old)
    event = SystemEventFactory().create(
        event_id="norms-v2", event_type="world_norms_updated", timestamp="t10",
        changes=[{"expected_version_id": "v1", "world_norms": new}], simulation_tick=10,
    )
    processor = EventProcessor(event_history=EventHistory(), world_state=world, simulation_clock=SimulationClock(10))
    processor.dispatch_with_evidence(event)
    assert world.world_norms.active_version_id == "v2"
    assert project_public_norms(
        world.world_norms, "v1", safety_governance=UniversalSafetyGovernance()
    ).version_id == "v1"


def test_untrusted_or_stale_norms_change_cannot_update_world_state():
    world = WorldState()
    old = make_norms()
    world.load_world_norms(old)
    processor = EventProcessor(event_history=EventHistory(), world_state=world)
    manual = Event("manual", "world_norms_updated", "t", changes=[])
    with pytest.raises(ValueError):
        processor.dispatch_with_evidence(manual)
    assert world.world_norms == old
