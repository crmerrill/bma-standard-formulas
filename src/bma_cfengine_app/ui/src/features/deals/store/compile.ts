import fieldOrder from "../field_order.json";
import type { DealState } from "./useDealStore";

type Manifest = Record<string, string[]>;

const manifest = fieldOrder as Manifest;

const FLOAT_FIELDS: Record<string, Set<string>> = {
  DealDefinition: new Set(["discount_factor_pct"]),
  BondDef: new Set([
    "coupon",
    "margin",
    "notional",
    "notional_pct_of_collateral",
    "nla_starting_balance",
    "required_subordination_pct",
    "cap",
    "floor",
    "inverse_multiplier",
    "schedule_speed_low",
    "schedule_speed_high",
    "pac_lower_psa",
    "pac_upper_psa",
    "tac_pricing_psa",
    "schedule_tolerance_bps",
  ]),
  AccountDef: new Set([
    "starting_amount",
    "starting_pct",
    "minimum_amount",
    "minimum_pct",
  ]),
  FeeDef: new Set(["amount", "rate", "minimum"]),
  TriggerNode: new Set(["threshold_value"]),
  RuleNode: new Set(["max_amount_fixed"]),
  TrancheRelation: new Set(["leverage", "cap", "floor"]),
  RateScheduleEntry: new Set(["rate"]),
  AccountMinimumScheduleEntry: new Set(["minimum_balance"]),
};

const LIST_CHILD_MODEL: Record<string, Record<string, string>> = {
  DealDefinition: {
    bonds: "BondDef",
    accounts: "AccountDef",
    fees: "FeeDef",
    triggers: "TriggerNode",
    calculations: "CalculationNode",
    waterfall_rules: "RuleNode",
    collateral_groups: "CollateralGroupDef",
  },
  BondDef: {
    relations: "TrancheRelation",
  },
  AccountDef: {
    minimum_schedule: "AccountMinimumScheduleEntry",
  },
  TriggerNode: {
    threshold_schedule: "RateScheduleEntry",
  },
};

const RATE_OR_SCHEDULE_FIELDS = new Set(["coupon", "margin", "cap", "floor"]);

const FLOAT_ARRAY_FIELDS: Record<string, Set<string>> = {
  RuleNode: new Set(["target_weights"]),
  TrancheRelation: new Set(["weights"]),
};

const RAW_DICT_INT_KEYS = new Set(["period"]);

function formatFloat(n: number): string {
  if (Number.isInteger(n) && Number.isFinite(n)) {
    return n.toFixed(1);
  }
  return JSON.stringify(n);
}

function serializeModel(
  obj: Record<string, unknown>,
  indent: number,
  modelName: string,
): string {
  const fields = manifest[modelName];
  if (!fields) {
    throw new Error(`Field order manifest missing model: ${modelName}`);
  }

  const present = new Set(Object.keys(obj));
  const orderedKeys: string[] = [];
  for (const key of fields) {
    if (present.has(key)) orderedKeys.push(key);
  }
  for (const key of Object.keys(obj)) {
    if (!fields.includes(key)) orderedKeys.push(key);
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

  if (typeof value === "number") {
    const isFloat = FLOAT_FIELDS[parentModel]?.has(fieldName) ?? false;
    return isFloat ? formatFloat(value) : JSON.stringify(value);
  }

  if (Array.isArray(value)) {
    return serializeFieldArray(value, indent, parentModel, fieldName);
  }

  if (typeof value === "object") {
    return serializeGenericObject(value as Record<string, unknown>, indent);
  }

  return JSON.stringify(value);
}

function serializeFieldArray(
  arr: unknown[],
  indent: number,
  parentModel: string,
  fieldName: string,
): string {
  if (arr.length === 0) return "[]";

  const ci = indent + 2;
  const pad = " ".repeat(ci);
  const cp = " ".repeat(indent);

  const childModel = LIST_CHILD_MODEL[parentModel]?.[fieldName] ?? null;
  const isFloatArr = FLOAT_ARRAY_FIELDS[parentModel]?.has(fieldName) ?? false;
  const isRateOrSchedule = RATE_OR_SCHEDULE_FIELDS.has(fieldName);
  const isScheduleContract = fieldName === "schedule_contract";

  let scUsesFloat = false;
  if (isScheduleContract) {
    for (const item of arr) {
      if (typeof item === "object" && item !== null) {
        for (const [k, v] of Object.entries(item as Record<string, unknown>)) {
          if (
            !RAW_DICT_INT_KEYS.has(k) &&
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
    } else if (isScheduleContract && typeof item === "object" && item !== null) {
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
      if (RAW_DICT_INT_KEYS.has(key)) {
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
