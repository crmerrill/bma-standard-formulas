/**
 * QuickFix registry — maps action_id strings to typed QuickFix descriptors (ve-5 fix-pass).
 *
 * A QuickFixDescriptor carries enough metadata for Phase 2's Problems Panel to
 * determine at runtime whether a given quick-fix is:
 *
 * - `"dispatch"`: a fully-typed DealAction the store can dispatch automatically.
 * - `"manual"`: a human-directed instruction the user must resolve themselves.
 *
 * Adding a new quick-fix:
 * 1. Define a DispatchQuickFix or ManualQuickFix object below.
 * 2. Insert it into _REGISTRY keyed by action_id.
 * 3. Add a test to quickFixRegistry.test.ts.
 */

export type DispatchQuickFix = {
  kind: "dispatch";
  /** Maps to a DealAction.type in the TS store. */
  actionType: string;
  description: string;
};

export type ManualQuickFix = {
  kind: "manual";
  /** Hint text rendered in the Problems Panel. */
  description: string;
};

export type QuickFixDescriptor = DispatchQuickFix | ManualQuickFix;

export class UnknownQuickFixError extends Error {
  readonly actionId: string;

  constructor(actionId: string) {
    super(`No QuickFix registered for action_id=${JSON.stringify(actionId)}`);
    this.name = "UnknownQuickFixError";
    this.actionId = actionId;
  }
}

const _REGISTRY: Record<string, QuickFixDescriptor> = {
  manual_resolve_duplicate_bond_name: {
    kind: "manual",
    description:
      "Two or more bonds share the same name. " +
      "Rename one of the duplicates to make all bond names unique.",
  },
};

/**
 * Return the QuickFixDescriptor registered for `actionId`.
 *
 * @throws {UnknownQuickFixError} if `actionId` has no registered descriptor.
 */
export function getQuickFix(actionId: string): QuickFixDescriptor {
  const descriptor = _REGISTRY[actionId];
  if (descriptor === undefined) {
    throw new UnknownQuickFixError(actionId);
  }
  return descriptor;
}
