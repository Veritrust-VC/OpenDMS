# EU AI Act analysis

**Classification:** Annex III §5(a) and §8(a) — high-risk AI system
under Regulation 2024/1689 when used for triage in public-service or
justice-administration contexts.

**Operator obligations** (the deploying organisation, not this package):

- Art. 13 transparency — output records `summarySource`, `aiConfidenceScore`, `aiModelVersion`
- Art. 14 human oversight — `humanValidationStatus` blocks consequential action
- Art. 9 risk management — see `resources/guardrails.yaml`
- Art. 12 logging — host MUST log invocation with package version + model id

See `resources/guardrails.yaml` for the machine-readable policy.
