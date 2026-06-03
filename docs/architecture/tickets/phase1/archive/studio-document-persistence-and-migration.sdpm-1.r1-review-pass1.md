# R1 Review (Pass 1) — `sdpm-1-sidecar-schema` implementation

**Reviewer**: gpt-5.5-medium (R1 tier; separate invocation; read-only; cross-family from claude-4.6-sonnet implementer + Claude parent + gpt codex T1 author)
**Date**: 2026-06-03
**Implementation under review**: commit `4e26f25` (test commit `351743c`)
**Verdict**: APPROVE-WITH-CHANGES (parent-verified)

## Summary

The implementation satisfies the top-level sidecar contract: `StudioSidecar` has the three required fields, uses `extra="forbid"`, and supports round-trip serialization. R1 found one Major: the `layout_overrides` validator only checked key presence, not inner value types per AC 1.

## Findings

### Major

**M1** — `layout_overrides` validator only checked `x`/`y` presence; AC 1 requires `x: float`, `y: float`, optional `collapsed: bool | None` with proper type enforcement. Payloads like `{"x": "left", "y": "top", "collapsed": "yes"}` would have validated.

## What Landed Well

- `schema_version: str = "1.0.0"`, `layout_overrides: dict[str, dict[str, Any]]`, `ui_preferences: dict[str, Any]` exactly per AC 1.
- `extra="forbid"` correctly rejects ai_provenance, notes, tags, scratchwork.
- Round-trip JSON serialization preserves all permitted fields.
- T1 tests cover required `x`/`y` presence + optional `collapsed`.

## Verdict Rationale

Localized validator gap. Fix is straightforward.

## Sign-off Recommendation

APPROVE-WITH-CHANGES — parent-direct fix to validator + add negative tests for invalid x/y/collapsed types.

---

## Parent-verify fix-pass applied (2026-06-03)

**Parent agent (Claude Opus 4.7)** applied the validator tightening directly per Major-only fold-back protocol.

**Fix**: `_validate_layout_entries` validator now checks:
- `x` and `y`: must be present AND must be `int` or `float` (bool excluded since bool is int subtype). Strings, lists, etc. are rejected.
- `collapsed`: when present, must be `bool` or `None`. Strings, ints, etc. are rejected.

**New test**: `test_studio_sidecar_rejects_invalid_layout_field_types` exercises invalid x (string), invalid y (list), invalid collapsed (string), and bool-as-x rejection. Plus a valid baseline.

3/3 tests pass; suite remains green.

**Verdict after parent-verify**: APPROVE — sdpm-1 closed.
