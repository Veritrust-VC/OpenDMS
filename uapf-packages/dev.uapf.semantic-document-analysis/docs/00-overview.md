# dev.uapf.semantic-document-analysis — Overview

**UAPF v1.1 SSOT-conformant** Level 4 process package providing
reusable semantic document analysis.

## What

A 3-step BPMN process that, given free-text document content:

1. Redacts PII via `ai.redact@1`
2. Extracts VDVC v1.1 structured semantic metadata via `ai.extract@1`
3. Emits `document.semantic-analysis.completed.v1` CloudEvent via `event.emit@1`

## What's portable

The package ships:
- The BPMN flow (the algorithm shape)
- The VDVC output JSON Schema (the output contract)
- The resource mapping (input/output contracts, timeouts, retries)
- The guardrails policy (GDPR + EU AI Act constraints)

The host system supplies the actual AI agent that fulfils the three
capabilities. Multiple hosts can implement the same capabilities;
multiple packages can require the same capabilities.

## How to consume

Drop this `.uapf` into any UAPF-conformant runtime. The runtime
exposes `uapf.run_process` (per UAPF-specification §6.3.1) targeting
`Process_SemanticDocumentAnalysis`. The runtime resolves the resource
mapping to find a target with the three required capabilities and
invokes them in order per the BPMN flow.
