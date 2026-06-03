// Vendored from src/bma_standard_formulas/deals/schemas/field_order.json
// Sync command: npm run sync:field-order
import fieldOrder from "../field_order.json";
import type { DealState } from "./useDealStore";

type FieldEntry = { name: string; type: string };
type ModelEntry = { fields: FieldEntry[] };
type Manifest = Record<string, ModelEntry>;

const manifest = fieldOrder as Manifest;

function formatFloat(n: number): string {
  if (Number.isInteger(n) && Number.isFinite(n)) {
    return n.toFixed(1);
  }
  return JSON.stringify(n);
}

function getFieldNames(modelName: string): string[] {
  const entry = manifest[modelName];
  if (!entry) throw new Error(`Field order manifest missing model: ${modelName}`);
  return entry.fields.map((f) => f.name);
}

function getFieldType(modelName: string, fieldName: string): string | null {
  const entry = manifest[modelName];
  if (!entry) return null;
  const field = entry.fields.find((f) => f.name === fieldName);
  return field ? field.type : null;
}

function isFloatType(typeStr: string): boolean {
  return typeStr === "float" || typeStr === "Optional[float]";
}

function isListOfFloat(typeStr: string): boolean {
  return (
    typeStr === "list[float]" ||
    typeStr === "Optional[list[float]]"
  );
}

function getListChildModel(typeStr: string): string | null {
  const m = typeStr.match(/^(?:Optional\[)?list\[(\w+)\](?:\])?$/);
  if (m && m[1][0] === m[1][0].toUpperCase() && m[1][0] !== m[1][0].toLowerCase()) {
    return m[1];
  }
  return null;
}

function isRateOrScheduleType(typeStr: string): boolean {
  return typeStr === "Union[float, list[RateScheduleEntry], None]";
}

function isScheduleContractType(typeStr: string): boolean {
  return typeStr === "list[dict[str, Union[float, int]]]";
}

function isDictType(typeStr: string): boolean {
  return typeStr.startsWith("dict[") || typeStr.startsWith("Optional[dict[");
}

const SCHEDULE_CONTRACT_INT_KEYS = new Set(["period"]);

function serializeModel(
  obj: Record<string, unknown>,
  indent: number,
  modelName: string,
): string {
  const fieldNames = getFieldNames(modelName);
  const fieldNameSet = new Set(fieldNames);

  const present = Object.keys(obj);
  for (const key of present) {
    if (!fieldNameSet.has(key)) {
      throw new Error(
        `compileToIR: model "${modelName}" has field "${key}" not present in manifest. ` +
          `Manifest may be stale — regenerate with: python scripts/emit_field_order.py`,
      );
    }
  }

  const orderedKeys: string[] = [];
  const presentSet = new Set(present);
  for (const key of fieldNames) {
    if (presentSet.has(key)) orderedKeys.push(key);
  }

  if (orderedKeys.length === 0) return "{}";

  const ci = indent + 2;
  const pad = " ".repeat(ci);
  const cp = " ".repeat(indent);
  const lines: string[] = [];

  for (const key of orderedKeys) {
    const vs = serializeFieldValue(obj[key], ci, modelName, key);
    lines.push(`${pad}${JSON.stringify(key)}: ${vs}`);
  }

  return `{\n${lines.join(",\n")}\n${cp}}`;
}

function serializeFieldValue(
  value: unknown,
  indent: number,
  parentModel: string,
  fieldName: string,
): string {
  if (value === null) return "null";
  if (typeof value === "boolean") return value ? "true" : "false";
  if (typeof value === "string") return JSON.stringify(value);

  const typeStr = getFieldType(parentModel, fieldName) ?? "";

  if (typeof value === "number") {
    if (isFloatType(typeStr) || isRateOrScheduleType(typeStr)) {
      return formatFloat(value);
    }
    return JSON.stringify(value);
  }

  if (Array.isArray(value)) {
    return serializeFieldArray(value, indent, parentModel, fieldName, typeStr);
  }

  if (typeof value === "object") {
    if (isDictType(typeStr)) {
      return serializeGenericObject(value as Record<string, unknown>, indent);
    }
    return serializeGenericObject(value as Record<string, unknown>, indent);
  }

  return JSON.stringify(value);
}

function serializeFieldArray(
  arr: unknown[],
  indent: number,
  parentModel: string,
  fieldName: string,
  typeStr: string,
): string {
  if (arr.length === 0) return "[]";

  const ci = indent + 2;
  const pad = " ".repeat(ci);
  const cp = " ".repeat(indent);

  const childModel = getListChildModel(typeStr);
  const isFloatArr = isListOfFloat(typeStr);
  const isRateOrSchedule = isRateOrScheduleType(typeStr);
  const isSchedContract = isScheduleContractType(typeStr);

  // CONTRACT: schedule_contract is typed as list[dict[str, float | int]].
  // After JSON.parse, TS cannot distinguish 100 from 100.0. We use a
  // heuristic: if ANY non-period value in the array has a fractional part,
  // treat all non-period values as float. This is the ONLY allowed heuristic
  // in the serializer; all other type dispatch is manifest-driven.
  let scUsesFloat = false;
  if (isSchedContract) {
    for (const item of arr) {
      if (typeof item === "object" && item !== null) {
        for (const [k, v] of Object.entries(item as Record<string, unknown>)) {
          if (
            !SCHEDULE_CONTRACT_INT_KEYS.has(k) &&
            typeof v === "number" &&
            !Number.isInteger(v)
          ) {
            scUsesFloat = true;
            break;
          }
        }
      }
      if (scUsesFloat) break;
    }
  }

  const items: string[] = [];
  for (const item of arr) {
    let s: string;
    if (
      childModel &&
      typeof item === "object" &&
      item !== null &&
      !Array.isArray(item)
    ) {
      s = serializeModel(item as Record<string, unknown>, ci, childModel);
    } else if (
      isRateOrSchedule &&
      typeof item === "object" &&
      item !== null &&
      !Array.isArray(item)
    ) {
      s = serializeModel(
        item as Record<string, unknown>,
        ci,
        "RateScheduleEntry",
      );
    } else if (isSchedContract && typeof item === "object" && item !== null) {
      s = serializeScheduleContractEntry(
        item as Record<string, unknown>,
        ci,
        scUsesFloat,
      );
    } else if (isFloatArr && typeof item === "number") {
      s = formatFloat(item);
    } else if (typeof item === "string") {
      s = JSON.stringify(item);
    } else if (typeof item === "number") {
      s = JSON.stringify(item);
    } else if (item === null) {
      s = "null";
    } else if (typeof item === "boolean") {
      s = item ? "true" : "false";
    } else {
      s = JSON.stringify(item);
    }
    items.push(pad + s);
  }

  return `[\n${items.join(",\n")}\n${cp}]`;
}

function serializeScheduleContractEntry(
  obj: Record<string, unknown>,
  indent: number,
  useFloat: boolean,
): string {
  const keys = Object.keys(obj);
  if (keys.length === 0) return "{}";

  const ci = indent + 2;
  const pad = " ".repeat(ci);
  const cp = " ".repeat(indent);
  const lines: string[] = [];

  for (const key of keys) {
    const val = obj[key];
    let vs: string;
    if (val === null) {
      vs = "null";
    } else if (typeof val === "number") {
      if (SCHEDULE_CONTRACT_INT_KEYS.has(key)) {
        vs = JSON.stringify(val);
      } else {
        vs = useFloat ? formatFloat(val) : JSON.stringify(val);
      }
    } else if (typeof val === "string") {
      vs = JSON.stringify(val);
    } else if (typeof val === "boolean") {
      vs = val ? "true" : "false";
    } else {
      vs = JSON.stringify(val);
    }
    lines.push(`${pad}${JSON.stringify(key)}: ${vs}`);
  }

  return `{\n${lines.join(",\n")}\n${cp}}`;
}

function serializeGenericObject(
  obj: Record<string, unknown>,
  indent: number,
): string {
  const keys = Object.keys(obj);
  if (keys.length === 0) return "{}";

  const ci = indent + 2;
  const pad = " ".repeat(ci);
  const cp = " ".repeat(indent);
  const lines: string[] = [];

  for (const key of keys) {
    const val = obj[key];
    let vs: string;
    if (val === null) {
      vs = "null";
    } else if (typeof val === "boolean") {
      vs = val ? "true" : "false";
    } else if (typeof val === "string") {
      vs = JSON.stringify(val);
    } else if (typeof val === "number") {
      vs = JSON.stringify(val);
    } else if (Array.isArray(val)) {
      if (val.length === 0) {
        vs = "[]";
      } else {
        const ai = ci + 2;
        const ap = " ".repeat(ai);
        const ac = " ".repeat(ci);
        const ai2 = val.map((v) => {
          if (typeof v === "object" && v !== null && !Array.isArray(v)) {
            return ap + serializeGenericObject(v as Record<string, unknown>, ai);
          }
          return ap + JSON.stringify(v);
        });
        vs = `[\n${ai2.join(",\n")}\n${ac}]`;
      }
    } else if (typeof val === "object") {
      vs = serializeGenericObject(val as Record<string, unknown>, ci);
    } else {
      vs = JSON.stringify(val);
    }
    lines.push(`${pad}${JSON.stringify(key)}: ${vs}`);
  }

  return `{\n${lines.join(",\n")}\n${cp}}`;
}

export function compileToIR(working_tree: DealState): string {
  return serializeModel(
    working_tree as unknown as Record<string, unknown>,
    0,
    "DealDefinition",
  );
}
