# Phase 3F approved documentation link migration

## Summary

Applied 54 approved original occurrence IDs across 9 documentation files. Preserved 45 retained IDs. Applied the 14 explicitly approved link-label improvements. Existing 17 shared-destination decisions and 14 multi-anchor combinations were used without changing their mappings. No normative text, code, tests or configuration was modified by this migration.

Applied IDs: 7, 12, 13, 21, 23, 26, 27, 28, 29, 30, 33, 35, 36, 37, 39, 42, 43, 45, 47, 50, 53, 55, 56, 63, 64, 65, 66, 68, 69, 70, 71, 72, 73, 75, 76, 77, 78, 79, 80, 81, 82, 83, 84, 86, 87, 88, 89, 90, 92, 93, 94, 95, 96, 99

Preserved IDs: 1, 2, 3, 4, 5, 6, 8, 9, 10, 11, 14, 15, 16, 17, 18, 19, 20, 22, 24, 25, 31, 32, 34, 38, 40, 41, 44, 46, 48, 49, 51, 52, 54, 57, 58, 59, 60, 61, 62, 67, 74, 85, 91, 97, 98

Improved-label IDs: 21, 26, 27, 28, 29, 30, 33, 35, 43, 45, 47, 53, 55, 56

## Exact diffs and SHA-256

The exact before/after changes are in `approved_link_changes.patch`; `approved_link_changes.json` records each original ID, old syntax, new syntax and coordinates. The `before/` and `after/` snapshots preserve exact file bytes, including pre-existing edits.

| Modified file | Before SHA-256 | After SHA-256 |
| --- | --- | --- |
| docs/AI_BOUNDARY.md | `08abe94f205b6bddae4b1e092e8b757bf6b3d92346a03354921f1f4f67b92a3b` | `0cea2f2daee5da2de37275ac92722d12621caece3b0a452dd9be0d11d5821e8d` |
| docs/COGNITIVEWORLD_CORE_DOCTRINE.md | `11d4350a7e07bc9a0ff89da46bbda8400ae6948f4a3e1c3505522272cd943c5d` | `d48676e0c9b82b876d8cb01ec4c8b244cab672163e131a9cb9d9ce6b84add323` |
| docs/COGNITIVEWORLD_SYSTEM_ARCHITECTURE.md | `04a872e053db37302277e81724d5fce0e41557bf03ab16d0e8477fc97996e524` | `62f131c841e781a907113e0fbb418de7ea6b5d682ebfdd56fd75f21ca7e42129` |
| docs/DATA_CONTRACTS.md | `d2a5bc0bc7d88d9dd1364244418e1699c3e81ef897b8650259f1368804a7d3f8` | `3db9fd64624107b410d08854b5f0e60aa7c060191ef0d3b0ff89c916e7cd4916` |
| docs/DEVELOPMENT_ROADMAP.md | `675d72f676374c8c8450c69e2ec509a6a41158127e9da33ec5d29334ece27033` | `00e7b8eb24e4b830359ef5207469f89922c086e829230f39f6d2cf8f7cac24fb` |
| docs/ENGINEERING_RULES.md | `cc8a35926aa9a556af6aae08ec778285d2e43d334af9d4449c8e0faa34de584d` | `5d0e1d1491f1324a97e85e3a3080c7e72c7e189ab4ada3198c036bba7026da62` |
| docs/MEMORY_DESIGN.md | `b51315ea8f6c9418686a39b451e3ae28343669d76eab70bfbd256375ba139c27` | `ed5b74259333146a2e2dcabc74a1fad15d1ababf77745b73b27c8e9512706077` |
| docs/REPOSITORY_STATUS.md | `0b6e39d244fc44148ae8d45eab03b57b1ecacdbcb3c0fa642d91043b560f1170` | `dc83e98ac3d471ab67cfaecf09f436b389ab2f7f631cad2302ebd6598211f864` |
| docs/SOCIAL_CAUSAL_DESIGN.md | `4bd79c4419e1a3f7ab47c5d247784161067d743da844fee55e3044732a63c12e` | `e3dbd64a0b4f4706c33af1f36dc959645160fde524c6e654a28bf05f5b68269f` |

## Validation

- Applied occurrence verification: 54/54; exact replay from before snapshots matches all 9 current files.
- Retained occurrence verification: 45/45 original syntaxes unchanged at adjusted positions.
- Local destinations: 86 link targets resolved; every explicit fragment occurs exactly once.
- No duplicate destination appears inside an individual replacement; shared destinations across distinct approved occurrences are intentional.
- Focused `git diff --no-index --check` on the nine before/after pairs reported no whitespace errors. No project tests were run.
- Original Phase 3E evidence package SHA-256 manifest remains valid.

## Final Git status

```text
## main...origin/main [ahead 1]
 M .github/workflows/core-platforms.yml
 M README.md
 M docs/AI_BOUNDARY.md
 M docs/ARCHITECTURE.md
 M docs/COGNITIVEWORLD_CORE_DOCTRINE.md
 M docs/COGNITIVEWORLD_SYSTEM_ARCHITECTURE.md
 M docs/DATA_CONTRACTS.md
 M docs/DEVELOPMENT_ROADMAP.md
 M docs/ENGINEERING_RULES.md
 M docs/MEMORY_DESIGN.md
 M docs/REPOSITORY_STATUS.md
 M docs/SOCIAL_CAUSAL_DESIGN.md
 M src/cognitive_world/core/persistence.py
 M src/cognitive_world/examples/persistence_trust.py
 M src/cognitive_world/examples/social_room.py
 M tests/test_actor_result_observation.py
 M tests/test_example_trust.py
 M tests/test_item_take.py
 M tests/test_memory_retrieval.py
 M tests/test_position_observation.py
 M tests/test_save_restore_end_to_end.py
 M tests/test_social_perspective.py
 M tests/test_social_physical_slice.py
?? docs/COGNITIVE_EXECUTION_FEEDBACK_REVIEW.md
?? docs/architecture/
```

No files were staged or committed; no push occurred. Phase 3G was not started.
