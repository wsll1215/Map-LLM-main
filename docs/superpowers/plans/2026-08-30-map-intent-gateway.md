# Map Agent Intent Gateway Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the project’s independent intent parsers with one rule-first gateway that uses constrained LLM Function Calling only for semantic completion and produces auditable clarification results.

**Architecture:** A side-effect-free `IntentGateway` runs control and semantic rules first, calls a Pydantic-backed `parse_map_intent` function only when rules are incomplete, merges locked rule fields with LLM output, and validates the result before any location or source operation. Existing planner and modification models remain compatibility adapters until all production callers migrate.

**Tech Stack:** Python 3.9+, Pydantic 2, LangChain 0.3, ChatOpenAI, Django, pytest, existing Trace/SSE infrastructure.

**Spec:** `docs/superpowers/specs/2026-08-30-map-intent-gateway-design.md`

## Global Constraints

- One request has one primary location and one map extent; multiple unrelated locations require clarification.
- Intent recognition must not choose `dataset_id`, `provider`, `source_url`, `cache_path`, `bbox`, or final status.
- User prompts are regression data only; no production branch may match a complete prompt.
- Production callers must parse each request once through `recognize_intent()`.
- A Function Call schema error receives at most one automatic correction attempt.
- Existing uncommitted work outside this feature must remain untouched.

---

### Task 1: Add Intent Contracts and Role Registry Adapter

**Files:**
- Create: `gis_mapping_agent/specs/intent.py`
- Modify: `gis_mapping_agent/specs/__init__.py`
- Modify: `gis_mapping_agent/data_sources/planner.py`
- Modify: `gis_mapping_agent/data_sources/__init__.py`
- Test: `tests/test_intent_contracts.py`

**Interfaces:**
- Produces `Intent`, `LocationSlot`, `LayerSlot`, `OperationSlot`, `FieldEvidence`, `IntentIssue`, and `IntentRecognitionResult`.
- `planner.py` re-exports compatibility names but no longer owns new semantic fields.

- [ ] **Step 1: Write failing contract tests** for finite task values, registered layer roles, field provenance, missing fields, conflicts, and JSON serialization.
- [ ] **Step 2: Run `pytest tests/test_intent_contracts.py -q` and verify the new contract imports fail.**
- [ ] **Step 3: Implement Pydantic v2 models with strict role/task literals and structured issue fields.**
- [ ] **Step 4: Re-export compatibility types and run `pytest tests/test_intent_contracts.py tests/test_data_source_contracts.py -q`.**
- [ ] **Step 5: Review the contract for source-planning fields and reject any leakage into Intent.**

### Task 2: Implement Generic RuleParser

**Files:**
- Create: `gis_mapping_agent/agent/intent_rules.py`
- Modify: `gis_mapping_agent/data_sources/planner.py`
- Test: `tests/test_intent_rules.py`
- Modify: `tests/test_data_source_contracts.py`

**Interfaces:**
- `RuleParser.parse(text: str, current_state: Optional[MapState]) -> RuleParseResult`.
- `RuleParseResult` contains partial Intent fields, `FieldEvidence`, `missing_fields`, `conflicts`, and a decision of `complete`, `partial`, `conflict`, or `unknown`.

- [ ] **Step 1: Add failing tests** for control commands, role synonyms, explicit files, generic location extraction, layer-order changes, and the `给我天津市...` regression.
- [ ] **Step 2: Run `pytest tests/test_intent_rules.py -q` and verify the parser is absent or fails the new cases.**
- [ ] **Step 3: Implement registry-driven role extraction, entity/gazetteer-aware location candidates, explicit-source extraction, and conflict detection without full-prompt branches.**
- [ ] **Step 4: Make rule fields carry evidence and `locked=True` only for unambiguous matches; return `partial` when a required field is absent.**
- [ ] **Step 5: Run the focused tests and review for hard-coded user sentence fragments.**

### Task 3: Implement Constrained LLM Function Parser

**Files:**
- Create: `gis_mapping_agent/agent/intent_llm.py`
- Modify: `gis_mapping_agent/utils/intent_classifier_v2.py`
- Test: `tests/test_intent_llm_parser.py`

**Interfaces:**
- `LlmIntentParser.parse(text: str, rule_result: RuleParseResult, current_state: Optional[MapState]) -> LlmParseResult`.
- The only semantic function is `parse_map_intent`; it returns schema arguments and never executes a data tool.

- [ ] **Step 1: Add Fake LLM tests** for a valid Function Call, no Function Call, invalid role, missing location, and one schema-correction retry.
- [ ] **Step 2: Run `pytest tests/test_intent_llm_parser.py -q` and verify the tests fail before implementation.**
- [ ] **Step 3: Bind the Pydantic schema, constrain task and role values, pass rule-locked fields as immutable context, and reject ordinary free-text output as semantic success.**
- [ ] **Step 4: Implement exactly one validation retry and structured `schema_invalid` output after the retry is exhausted.**
- [ ] **Step 5: Run the focused tests and review that no source, bbox, or final-status field is accepted.**

### Task 4: Implement Merge and Domain Validation

**Files:**
- Create: `gis_mapping_agent/agent/intent_gateway.py`
- Modify: `gis_mapping_agent/agent/intent_rules.py`
- Test: `tests/test_intent_gateway.py`
- Test: `tests/test_intent_error_recovery.py`

**Interfaces:**
- `recognize_intent(text: str, current_state: Optional[MapState], llm: Optional[Any] = None) -> IntentRecognitionResult`.
- Merge order is explicit user evidence, locked rule evidence, LLM completion, then non-semantic defaults.

- [ ] **Step 1: Add failing tests** for complete rule acceptance without LLM, partial rule plus LLM completion, rule/LLM conflict, missing required location, invalid task, and modify-without-current-state.
- [ ] **Step 2: Run `pytest tests/test_intent_gateway.py tests/test_intent_error_recovery.py -q` and verify failures.**
- [ ] **Step 3: Implement the gateway, merge policy, required-field policy, conflict policy, and structured next actions.**
- [ ] **Step 4: Ensure the gateway is side-effect free and does not call geocoding, source planning, or map tools.**
- [ ] **Step 5: Run focused tests and review the state transitions against the design spec.**

### Task 5: Migrate Production Callers

**Files:**
- Modify: `gis_mapping_agent/agent/thinking.py`
- Modify: `gis_mapping_agent/agent/conversational.py`
- Modify: `gis_mapping_agent/adjustment/engine.py`
- Modify: `gis_mapping_agent/data_sources/coordinator.py`
- Modify: `mapping/views.py`
- Modify: `gis_mapping_agent/data_sources/__init__.py`
- Test: `tests/test_intent_routing.py`
- Test: `tests/test_source_coordinator.py`
- Test: `tests/test_thinking_loop_completion.py`

**Interfaces:**
- Agent entry points consume `IntentRecognitionResult.intent` only after status `accepted`.
- `build_source_plan(intent, ...)` receives an already-validated Intent and never reparses request text.
- `parse_intent()` remains a compatibility wrapper for isolated legacy callers and is not used by production task orchestration.

- [ ] **Step 1: Add failing integration tests** proving creation, modification, and query paths call the gateway once and that missing location stops before SourcePlan.
- [ ] **Step 2: Run the focused integration tests and record existing duplicate-parser failures.**
- [ ] **Step 3: Replace direct parser calls and LLM-first task routing with the gateway while preserving adjustment patch conversion.**
- [ ] **Step 4: Thread the single Intent object through SourcePlan and remove repeated calls at the later thinking-agent helpers.**
- [ ] **Step 5: Run focused backend tests and inspect the call count and side-effect boundaries.**

### Task 6: Add Recognition Trace and Clarification Events

**Files:**
- Modify: `mapping/trace.py`
- Modify: `mapping/realtime.py`
- Modify: `mapping/views.py`
- Test: `tests/test_trace_events.py`
- Test: `tests/test_realtime_contract.py`

**Interfaces:**
- Parent event: `intent_parse`.
- Child events: `intent_rule_parse`, `intent_llm_parse`, `intent_merge`, `intent_validate`.

- [ ] **Step 1: Add failing tests** for partial recognition, LLM schema failure, conflict clarification, and the distinction between parser execution status and semantic status.
- [ ] **Step 2: Run the trace tests and verify missing child events or incorrect success statuses.**
- [ ] **Step 3: Publish redacted summaries with `attempt`, `missing_fields`, `conflicts`, `error_code`, and `next_action`; keep large details in REST trace storage.**
- [ ] **Step 4: Map `needs_clarification` to the existing REST/SSE state without emitting a completed event.**
- [ ] **Step 5: Run focused trace tests and review event ordering and parent IDs.**

### Task 7: Add Metamorphic and Fault-Injection Coverage

**Files:**
- Create: `tests/test_intent_metamorphic.py`
- Create: `tests/test_intent_failure_injection.py`
- Modify: `docs/失败案例记录.md`

**Interfaces:**
- Metamorphic tests call `recognize_intent()` with equivalent surface forms and compare normalized Intent.
- Failure tests inject parser, LLM, schema, location, and state failures and compare structured next actions.

- [ ] **Step 1: Add tests** for synonym, politeness, word-order, layer-order, missing-location, conflict, malformed Function Call, and no-tool-call variants.
- [ ] **Step 2: Run them and confirm any current failures are recorded with request/run/trace identifiers when available.**
- [ ] **Step 3: Fix only generic parser or gateway behavior, never add a prompt-specific production branch.**
- [ ] **Step 4: Update the failure log with the root cause, recurrence count, fix, and residual gap.**
- [ ] **Step 5: Run the full intent, source-planning, routing, and trace test subsets.**

### Task 8: Final Verification and Review

**Files:**
- Review all files changed by Tasks 1-7.
- Update: `docs/superpowers/specs/2026-08-30-map-intent-gateway-design.md` only if verified behavior requires a clarified invariant.

- [ ] **Step 1: Run `pytest tests/test_intent_contracts.py tests/test_intent_rules.py tests/test_intent_llm_parser.py tests/test_intent_gateway.py tests/test_intent_error_recovery.py tests/test_intent_metamorphic.py tests/test_intent_failure_injection.py tests/test_intent_routing.py tests/test_data_source_contracts.py tests/test_source_coordinator.py tests/test_trace_events.py -q`.**
- [ ] **Step 2: Run `python manage.py check` in the configured project environment.**
- [ ] **Step 3: Run `git diff --check` and inspect the production call graph for remaining duplicate parsing.**
- [ ] **Step 4: Perform a code review focused on silent fallback, LLM override of locked fields, source leakage, and false completed states.**
- [ ] **Step 5: Report passed tests, known environment failures, and the exact commit containing this round.**
