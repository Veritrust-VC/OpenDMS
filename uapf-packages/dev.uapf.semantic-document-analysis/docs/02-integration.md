# Integration with UAPF-conformant runtimes

This package validates against the UAPF v1.1 SSOT schemas:
- `uapf.yaml` → `uapf-manifest.schema.json`
- `metadata/ownership.yaml` → `ownership.schema.json`
- `metadata/lifecycle.yaml` → `lifecycle.schema.json`
- `resources/mappings.yaml` → `resource-mapping.schema.json`

It conforms to UAPF Conformance Checklist §"Level 4 requirements":
- ✓ uapf.yaml present
- ✓ ≥1 BPMN file (`bpmn/semantic-document-analysis.bpmn.xml`)
- ✓ `resources/mappings.yaml` present
- ✓ `metadata/ownership.yaml` + `metadata/lifecycle.yaml` present
- ✓ Cornerstones declared correctly (bpmn + resources)

## Engine compatibility notes

`uapf-engine@1.0.0` only reads `manifest.json` (pre-v1.1 file naming).
This package ships both `uapf.yaml` (SSOT-mandated) and `manifest.json`
(byte-identical-semantics JSON copy) for compatibility until upstream
engine supports YAML.
