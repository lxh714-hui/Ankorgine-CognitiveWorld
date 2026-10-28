# Contributing to CognitiveWorld

Read the architecture before changing code. This is a developer preview;
interfaces, tests and proposed designs do not imply complete product acceptance.

## Issues, PRs and verification

Check existing issues and [roadmap task IDs](docs/DEVELOPMENT_ROADMAP.md). Provide
reproduction steps, expected/actual behavior, environment and code identity.
Remove secrets, private prompts and cognitive data from public reports.

Discuss authority, persistence, safety and contract changes before implementation.
Keep unrelated changes out of PRs. Explain the change, evidence, limitations,
compatibility and relevant task ID; update authoritative docs when needed.
Never weaken assertions or delete safety tests to obtain green results.

Use the README's private environment setup. Test tools currently require explicit
`python -m pip install pytest pytest-qt`; there is no test extra or CI dependency
lock. Run focused regressions and, where possible:

```text
python -m pytest -q -ra
python -m compileall -q src tests
git diff --check
```

Record actual commands, code identity, exit codes, summaries, skips and timeouts.
Separate substitutes, real models, independent processes, offscreen Qt and visible
GUI evidence. Do not require a live model or implicitly download one for ordinary
tests. Preserve existing work and pytest configuration.

## Required boundaries

Follow [AGENTS.md](AGENTS.md), [ARCHITECTURE.md](docs/ARCHITECTURE.md),
[ENGINEERING_RULES.md](docs/ENGINEERING_RULES.md) and
[DATA_CONTRACTS.md](docs/DATA_CONTRACTS.md).

- Never bypass owner/Character authorization, Observation provenance, Resolution,
  EventFactory, EventProcessor, RuntimeWriteFence, save validation or Timeline
  isolation. No parallel canonical Stores or alternate world writer.
- LLM text and similarity do not establish facts or grants. Only the formal
  event path changes the running world; read-only views need no fabricated Event.
  Safety refusals create no punishment, NPC memory or relationship consequence.
- Keep Core independent of Qt/Web. Long work must not block UI. Asynchronous
  results retain their original session/generation/permit; do not acquire a new
  permit to legalize stale results. Presentation retries do not re-execute actions.
- UI receives only authorized whitelist DTOs through Presentation, never complete
  internals, prompts, reasoning or credentials. Do not claim complete P0 readiness
  or malicious same-process isolation beyond documented evidence.
- World-specific content belongs in validated packages/fixtures. No scene-specific
  branches, fixed outcomes or screenshot-driven production rules.

## Rights and sources

Contribute only material You own or are authorized to submit. Identify employer,
client and co-author rights. Disclose third-party code, data, models and resources:
source/version, license, notices, changes and restrictions. Disclose substantive
AI assistance: known tool/model, role, affected files and human rights, safety and
correctness review. AI output is not clearance evidence. Do not publish private
inputs as a disclosure shortcut.

Do not copy, translate, port or closely imitate third-party implementations or
prompt templates. Public research may inform independently designed ideas.
Dependencies and models retain
their own licenses; CognitiveWorld cannot license rights it does not hold.

## Public repository administration TODO

This is the record for new public-repository administration work, not a second
engine/MVP roadmap. Reference these IDs rather than duplicating their status.

| ID | Status / priority | Dependency and reason | Acceptance |
|---|---|---|---|
| PUBLIC-03 | OPEN / P0 before public release | Existing/migrated resources and dependency/model notices need review | Establish ownership/permission, required notices and approved release scope |
| PUBLIC-04 | DEFERRED / P2 | Competition-specific restrictions would require independent legal/license strategy | If pursued, separately assess AGPL incompatibility; never disguise non-compete terms as unchanged AGPL |

Engine changes retain existing roadmap IDs. Public preparation does not close
Timeline ancestry debt or unfreeze D3.2.4.

## Licensing and identity

The selected code license is **AGPL-3.0-only**, with the unchanged GNU text in
[LICENSE](LICENSE). Opening a PR does not transfer copyright.

Contact: ankorgine@outlook.com
