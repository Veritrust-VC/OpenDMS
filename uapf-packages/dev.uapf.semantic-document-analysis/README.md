# dev.uapf.semantic-document-analysis

UAPF v1.1 SSOT-conformant Level 4 process package providing reusable
semantic document analysis as `Process_SemanticDocumentAnalysis`.

See `docs/00-overview.md` for what it does, `docs/01-eu-ai-act.md` for
the regulatory analysis, and `docs/02-integration.md` for runtime
integration notes.

## Validates against

Run `jsonschema -i <each yaml-rendered-as-json> <each schema>` against
the canonical schemas in
`github.com/UAPFormat/UAPF-specification/schemas/`:

- `uapf-manifest.schema.json` (root manifest)
- `ownership.schema.json` (metadata/ownership.yaml)
- `lifecycle.schema.json` (metadata/lifecycle.yaml)
- `resource-mapping.schema.json` (resources/mappings.yaml)
