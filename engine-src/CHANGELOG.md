# Changelog

## [1.3.0] - 2026-05-21

### Added — surface SEM-014 and SEM-015 in `UapfValidator` output
- `formatErrors()` now classifies ajv schema errors and tags them with the
  matching SEM-* code from the v2.5.0 conformance checklist. Today this
  recognises SEM-014 (algorithm card missing the top-level `tests` array,
  or `tests` array with fewer than 2 entries); the `classifySchemaError`
  hook is the place to add more codes as the checklist grows.
- New `validateAlgorithmCardTestKeys()` implements SEM-015 (WARN): for
  every test in an algorithm card, every input/expected_outputs key must
  appear in the card's declared `io.inputs` / `io.outputs` ids. Mismatches
  suggest the test was written against an older io shape and would give
  misleading results in the v2.5.0 sample browser.
- `validatePackage()` now calls the new check alongside the existing
  algorithm-card schema validation and BPMN ref resolution (SEM-012).

The v2.5.0 schema files (bind-mounted into the engine container from
`/home/OpenDMS/uapf-schemas/` as of session 426) already enforced the
required `tests` field and `minItems: 2` at the JSON Schema level — this
release adds the human-readable SEM-014 prefix so consumers parsing the
validator's output can match on the code rather than the ajv message
verbatim.

## [1.2.0] - 2026-05-20

### Added — UAPF v2.4.0 Algorithm Cards support
- New `algorithm-card` artifact kind. Packages may now ship cards under
  `algorithms/*.card.{yaml,yml,json}`. The loader discovers them and
  parses them into the package's `algorithmCards` map keyed by card id.
- BPMN walker reads the v2.4.0 `uapf:algorithmCardRef` attribute on
  service / business-rule / abstract tasks. The XML parser strips
  namespace prefixes (`removeNSPrefix: true`) so any prefix works
  — `uapf:`, `uapf24:`, `uapfa:`, etc — as long as the namespace URI is
  the v2.4.0 one or the attribute is bound under any prefix to the
  same local name.
- `RealExecutionEngine` enriches `dev.uapf.capability.invoking` and
  `dev.uapf.capability.invoked` audit events with an `algorithmCard`
  payload containing `id`, `version`, `algorithm_kind`, `determinism`,
  and `risk`. If a `uapf:algorithmCardRef` is present on the task but
  no matching card is loaded, the event carries `{ id, resolved: false }`
  instead of dropping the reference silently.
- `UapfValidator` validates each loaded card against
  `algorithm-card.schema.json` (looked up under `UAPF_SCHEMAS_DIR`).
- New SEM-012 referential-integrity check: every BPMN task with
  `uapf:algorithmCardRef` MUST resolve to a card in the same package's
  `algorithms/` folder. Unresolved refs are reported as ERROR.
- New HTTP endpoints:
  - `GET /uapf/packages/:packageId/algorithms` — list compact summaries
    of all cards in a package.
  - `GET /uapf/packages/:packageId/algorithms/:cardId` — get a single
    card's full body as JSON.
  - The existing `GET /uapf/packages/:packageId/artifacts/:kind`
    endpoint now accepts `kind=algorithm-card`.
- `PackageSummary` carries `algorithmCards` so the workspace registry
  exposes them through the standard summary path consumers already use.

### Changed
- `package.json` version 1.1.0 → 1.2.0.

### Compatibility
- Packages that do not carry algorithm cards are unaffected. Pre-v2.4.0
  packages continue to work; the BPMN walker simply observes that
  `algorithmCardRef` is undefined on their tasks and the audit events
  carry no `algorithmCard` field.

