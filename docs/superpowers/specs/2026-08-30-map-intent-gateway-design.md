# Map Agent Intent Gateway Design

## Goal

Provide one production intent-recognition path for map creation, map modification,
map queries, and task controls. The path must prefer deterministic rules, use an
LLM only for semantic completion, and never allow recognition to choose data
sources, spatial extents, or task completion.

## Scope and Boundary

- One request has one primary location and one map extent. Multiple unrelated
  locations require clarification.
- The supported layer roles are the registry roles: `boundary`, `road`,
  `railway`, `river`, `school`, `primary_school`, `university`, `hospital`,
  `park`, and `poi`.
- Intent recognition is side-effect free. Location resolution, source planning,
  data fetching, rendering, and finalization remain downstream services.
- Existing callers remain compatible during migration, but production callers
  must converge on `recognize_intent()`.

## Invariants

1. User text is parsed into a finite semantic contract, never into arbitrary tool
   arguments.
2. Explicit user fields and high-confidence rule fields cannot be overwritten by
   LLM output.
3. The LLM can fill missing or ambiguous semantic fields, but cannot emit
   `dataset_id`, `provider`, `source_url`, `cache_path`, `bbox`, or final status.
4. A syntactically valid parser response is not semantic success. Required-field,
   conflict, confidence, and domain checks determine whether execution is allowed.
5. Missing required information produces `needs_clarification`; it never uses a
   global default extent or an arbitrary dataset.
6. Every result records field provenance, evidence, issues, and the next action.

## Pipeline

```text
request
  -> control-command rules
  -> semantic rules
  -> rule decision
       complete/no-conflict -> schema/domain validation
       partial/unsupported  -> LLM Function Calling
       conflict             -> clarification
  -> merge locked rule fields with LLM completion
  -> schema validation
  -> domain validation against current map state
  -> location resolution
  -> SourcePlan
  -> execution and Finalizer
```

The rule parser is a high-precision extractor, not a collection of complete
sentence templates. It uses the role registry, explicit-file recognition,
generic location candidates, and control-command rules. It must handle changes in
politeness words, word order, and layer order without prompt-specific branches.

The LLM parser calls only `parse_map_intent`. The function has no side effects and
is constrained by a Pydantic/JSON Schema contract. It must return `null` for an
unknown required field rather than inventing a value.

## Contracts

`Intent` contains `task`, `location`, `layers`, `operations`, `style`, and
`explicit_sources`. `IntentRecognitionResult` contains the Intent plus
`status`, per-field evidence, missing fields, conflicts, structured issues, and
attempt metadata. Source and execution models remain separate.

Recognition statuses are:

```text
accepted
partial
needs_llm
needs_clarification
schema_invalid
domain_invalid
failed
```

Execution statuses are not recognition statuses. Trace must report the distinction
so `intent_rule_parse: partial` is never shown as `intent_parse: success`.

## Error Policy

- Rule partial result: preserve recognized fields and invoke one LLM completion.
- Function-call absence or schema error: retry once with the exact validation
  issue; then return a structured failure or clarification.
- Rule/LLM conflict: do not choose automatically; ask the user.
- Missing location for a location-dependent create: do not call geocoding or data
  tools; ask for a city, district, or place.
- A geocoder failure is `location_not_resolved`, not an intent success.
- A user correction starts a new execution run and preserves the old trace.
- Tool and source failures are handled downstream and cannot be reclassified as
  successful intent recognition.

## Observability

The parent `intent_parse` span has child spans:

```text
intent_rule_parse
intent_llm_parse
intent_merge
intent_validate
```

Each span records the attempt, field provenance, missing fields, conflicts,
validation errors, and next action. Payloads are redacted and large details are
loaded through Trace REST rather than broadcast in the SSE summary.

## Acceptance

- All production entry points use one gateway and parse a request once.
- Rule-only complete requests do not incur an LLM call.
- Rule-partial requests use one constrained LLM completion.
- Unknown, conflicting, or unverifiable locations never trigger data execution.
- Creation, modification, and query requests produce different finite task values.
- Metamorphic variants of the same request produce equivalent normalized Intent.
- The original `给我天津市...` regression is fixed by generic extraction and is
  not represented by a production special case.
