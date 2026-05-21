import fs from "fs";
import path from "path";
import Ajv, { type ErrorObject } from "ajv";
import Ajv2020 from "ajv/dist/2020";
import addFormats from "ajv-formats";
import { LoadedPackage } from "./UapfLoader";
import { BpmnWalker } from "../engine/BpmnWalker";

export interface ValidationIssue {
  level: "error" | "warn";
  message: string;
  path?: string;
}

type SchemaValidator = ReturnType<Ajv["compile"]>;

export class UapfValidator {
  private ajv: Ajv;
  private manifestValidator?: SchemaValidator;
  private policiesValidator?: SchemaValidator;
  private resourceBindingValidator?: SchemaValidator;
  private startupWarnings: ValidationIssue[] = [];

  constructor(private schemasDir?: string) {
    this.ajv = new Ajv2020({
      allErrors: true,
      strict: false,
    }) as unknown as Ajv;
    addFormats(this.ajv);
    this.loadValidators();
  }

  private algorithmCardValidator?: SchemaValidator;

  private loadValidators() {
    if (!this.schemasDir) {
      this.startupWarnings.push({
        level: "warn",
        message: "UAPF_SCHEMAS_DIR not set; validation will be best-effort",
      });
      return;
    }

    this.manifestValidator = this.loadSchema("manifest.schema.json");
    this.policiesValidator = this.loadSchema("policies.schema.json");
    this.resourceBindingValidator = this.loadSchema("resource-binding.schema.json");
    this.algorithmCardValidator = this.loadSchema("algorithm-card.schema.json");
  }

  private loadSchema(fileName: string): SchemaValidator | undefined {
    const schemaPath = path.join(this.schemasDir as string, fileName);
    if (!fs.existsSync(schemaPath)) {
      this.startupWarnings.push({
        level: "warn",
        message: `Schema not found: ${schemaPath}`,
        path: schemaPath,
      });
      return undefined;
    }

    try {
      const schema = JSON.parse(fs.readFileSync(schemaPath, "utf-8"));
      return this.ajv.compile(schema);
    } catch (err) {
      const message = (err as Error).message;
      this.startupWarnings.push({
        level: "warn",
        message: `Failed to load schema ${fileName}: ${message}`,
        path: schemaPath,
      });
      return undefined;
    }
  }

  private static formatErrors(
    validator: SchemaValidator,
    basePath: string
  ): ValidationIssue[] {
    if (!validator.errors) return [];
    return validator.errors.map((err: ErrorObject | any) => {
      const path = (err as any).instancePath ?? (err as any).dataPath ?? basePath ?? "";
      const semCode = UapfValidator.classifySchemaError(err, basePath);
      const prefix = semCode ? `${semCode}: ` : "";

      return {
        level: "error" as const,
        message: `${prefix}${path} ${err.message ?? "invalid"}`.trim(),
        path: basePath,
      };
    });
  }

  // v2.5.0: tag known schema-violation patterns with the SEM-* code from
  // the UAPF conformance checklist so consumers can match by code.
  private static classifySchemaError(
    err: ErrorObject | any,
    basePath: string
  ): string | null {
    if (!basePath.startsWith("algorithms/")) return null;
    // SEM-014: top-level `tests` array missing OR has fewer than 2 items.
    if (
      (err.keyword === "required" && err.params?.missingProperty === "tests") ||
      (err.keyword === "minItems" && ((err.instancePath ?? err.dataPath ?? "") as string).endsWith("/tests"))
    ) {
      return "SEM-014";
    }
    return null;
  }

  validateManifest(manifest: unknown): ValidationIssue[] {
    if (!this.manifestValidator) {
      return [...this.startupWarnings];
    }

    const valid = this.manifestValidator(manifest);
    return valid
      ? []
      : [
          ...this.startupWarnings,
          ...UapfValidator.formatErrors(this.manifestValidator, "manifest"),
        ];
  }

  validatePolicies(policies: unknown): ValidationIssue[] {
    if (!policies) return [];
    if (!this.policiesValidator) return [...this.startupWarnings];
    const valid = this.policiesValidator(policies);
    return valid
      ? []
      : [
          ...this.startupWarnings,
          ...UapfValidator.formatErrors(this.policiesValidator, "policies"),
        ];
  }

  validateResourceBindings(resourceConfig: unknown): ValidationIssue[] {
    if (!resourceConfig) return [];
    if (!this.resourceBindingValidator) return [...this.startupWarnings];
    const valid = this.resourceBindingValidator(resourceConfig);
    return valid
      ? []
      : [
          ...this.startupWarnings,
          ...UapfValidator.formatErrors(
            this.resourceBindingValidator,
            "resource-bindings"
          ),
        ];
  }

  validatePackage(pkg: LoadedPackage): ValidationIssue[] {
    const issues: ValidationIssue[] = [];
    issues.push(...this.validateManifest(pkg.manifest));
    issues.push(...this.validatePolicies(pkg.policies));
    issues.push(...this.validateResourceBindings(pkg.resources));
    issues.push(...this.validateAlgorithmCards(pkg));

    issues.push(...this.validateAlgorithmCardTestKeys(pkg));
    issues.push(...this.validateAlgorithmCardRefs(pkg));
    return issues;
  }

  // v2.4.0: validate each algorithm card against algorithm-card.schema.json.
  validateAlgorithmCards(pkg: LoadedPackage): ValidationIssue[] {
    const cards = pkg.algorithmCards;
    if (!cards) return [];
    if (!this.algorithmCardValidator) return [...this.startupWarnings];
    const issues: ValidationIssue[] = [];
    for (const [id, card] of Object.entries(cards)) {
      const valid = this.algorithmCardValidator(card);
      if (!valid) {
        issues.push(
          ...UapfValidator.formatErrors(this.algorithmCardValidator, `algorithms/${id}`)
        );
      }
    }
    return issues;
  }

  // v2.5.0 SEM-015 (WARN): each test's inputs/expected_outputs keys SHOULD
  // match the io.inputs/io.outputs ids declared on the same card. Mismatches
  // suggest the test was written against an older io shape and may give
  // misleading results in the sample browser.
  validateAlgorithmCardTestKeys(pkg: LoadedPackage): ValidationIssue[] {
    const cards = pkg.algorithmCards;
    if (!cards) return [];
    const issues: ValidationIssue[] = [];
    for (const [id, card] of Object.entries(cards)) {
      const anyCard = card as any;
      const tests = Array.isArray(anyCard?.tests) ? anyCard.tests : null;
      const ioInputs = Array.isArray(anyCard?.io?.inputs) ? anyCard.io.inputs : null;
      const ioOutputs = Array.isArray(anyCard?.io?.outputs) ? anyCard.io.outputs : null;
      if (!tests || !ioInputs || !ioOutputs) continue;
      const declaredInputIds = new Set(ioInputs.map((f: any) => f?.id).filter(Boolean));
      const declaredOutputIds = new Set(ioOutputs.map((f: any) => f?.id).filter(Boolean));
      tests.forEach((t: any, idx: number) => {
        const testInputs = t?.inputs ? Object.keys(t.inputs) : [];
        const testOutputs = t?.expected_outputs ? Object.keys(t.expected_outputs) : [];
        for (const k of testInputs) {
          if (!declaredInputIds.has(k)) {
            issues.push({
              level: "warn",
              message: `SEM-015: algorithms/${id} tests[${idx}] ("${t?.name ?? "?"}") has input key "${k}" not declared in io.inputs`,
              path: `algorithms/${id}`,
            });
          }
        }
        for (const k of testOutputs) {
          if (!declaredOutputIds.has(k)) {
            issues.push({
              level: "warn",
              message: `SEM-015: algorithms/${id} tests[${idx}] ("${t?.name ?? "?"}") has expected_outputs key "${k}" not declared in io.outputs`,
              path: `algorithms/${id}`,
            });
          }
        }
      });
    }
    return issues;
  }

  // SEM-012 (v2.4.0): every BPMN task with uapf:algorithmCardRef MUST resolve
  // to a loaded algorithm card. Reads the bpmn artifacts from the loaded
  // package, walks each task, and reports unresolved refs as ERRORs.
  validateAlgorithmCardRefs(pkg: LoadedPackage): ValidationIssue[] {
    const issues: ValidationIssue[] = [];
    if (!pkg.artifacts) return issues;
    const cards = pkg.algorithmCards || {};
    const bpmnArtifacts = pkg.artifacts.filter((a) => a.kind === "bpmn");
    if (bpmnArtifacts.length === 0) return issues;

    const walker = new BpmnWalker();
    for (const art of bpmnArtifacts) {
      let xml: string;
      try {
        xml = fs.readFileSync(art.path, "utf-8");
      } catch (err) {
        issues.push({
          level: "warn",
          message: `Could not read BPMN artifact ${art.id}: ${(err as Error).message}`,
          path: art.path,
        });
        continue;
      }
      let processes: ReturnType<BpmnWalker["parseBpmnXml"]>;
      try {
        processes = walker.parseBpmnXml(xml);
      } catch (err) {
        // Don't double-report XML parse errors here — other code paths cover that.
        continue;
      }
      for (const proc of processes) {
        for (const node of proc.nodes.values()) {
          if (!node.algorithmCardRef) continue;
          if (!cards[node.algorithmCardRef]) {
            issues.push({
              level: "error",
              message: `SEM-012: BPMN task ${proc.id}/${node.id} carries uapf:algorithmCardRef="${node.algorithmCardRef}" but no algorithm card with that id is loaded`,
              path: art.path,
            });
          }
        }
      }
    }
    return issues;
  }

  validateWorkspaceIndex(indexData: any, indexPath: string): ValidationIssue[] {
    if (!indexData) {
      return [
        ...this.startupWarnings,
        { level: "warn", message: "Workspace index missing or empty", path: indexPath },
      ];
    }

    if (typeof indexData !== "object") {
      return [
        ...this.startupWarnings,
        { level: "error", message: "Workspace index is not an object", path: indexPath },
      ];
    }

    const hasPackages = Array.isArray((indexData as any).packages);
    const hasEntries = Array.isArray((indexData as any).entries);
    if (!hasPackages && !hasEntries) {
      return [
        ...this.startupWarnings,
        {
          level: "warn",
          message: "Workspace index should include packages[] or entries[]",
          path: indexPath,
        },
      ];
    }
    return [...this.startupWarnings];
  }

  collectStartupWarnings(): ValidationIssue[] {
    return [...this.startupWarnings];
  }
}
