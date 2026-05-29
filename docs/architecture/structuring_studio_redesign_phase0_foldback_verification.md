# Structuring Studio Redesign — Phase 0 Pass-2 Fold-Back Verification

**Author**: parent agent (Claude Opus 4.7)
**Date**: 2026-05-29
**Plan revised**: `/Users/crmerrill/.cursor/plans/structuring_studio_redesign_ec1d8b3d.plan.md`
**Pass-2 review reviewed**: `docs/architecture/structuring_studio_redesign_phase0_review_pass2.md` (verdict: RETURN-FOR-REVISION)
**User direction**: walk-each-decision; resolve all Blocking + Critical first; parent-verify (no pass 3 required if verification is clean)

This document is the verification artifact mapping each pass-2 finding to the plan diff that addresses it. Each row cites the section + line range that now resolves the finding so you can spot-check independently.

## Summary

- All 3 Blocking findings (B5, B6, B7): RESOLVED via user-directed architectural decisions, plan revised across 6 sections.
- All 3 Critical findings (C9, C10, C11): RESOLVED via user-directed architectural decisions.
- All 5 Major findings (M12, M13, M14, M15, M16): RESOLVED. M14 by user override to "no class metadata"; M12, M13, M15 use parent-proposed sensible defaults (called out below — flag if you want them changed).
- Pass-2's 7 partial-resolution items inherited from pass 1 (B2, B3, C3, M2, M8, M11, n1) are now fully resolved as a consequence of the Blocking-finding resolutions.
- Pass-2's 1 Minor (m5) and 1 Nit (n5): RESOLVED.

## Decisions made during fold-back (user explicitly chose)

| Finding | User-selected option | Plan diff section |
|---|---|---|
| B5 | `sidecar.json` git-tracked; provenance in commit metadata only (option A) | Studio Document section, AI-off contract, projection matrix |
| B6 | Canonical-post-migration byte-identical; remove auto-canonicalization from compile (option A) | IR round-trip subsection; compile-step paragraph; `studio-document-and-store` todo |
| B7 | Application-level field merge over git's commit graph (option A) | `ir-version-control-foundation` todo; "Three-way merge specifically" paragraph; new Operational Design subsection |
| C9 | `DocumentSession` abstraction (option A) | New "Reactive store with typed actions, DocumentSession model" subsection; Patch lifecycle rewrite; Bounded non-convergence rewrite |
| C10 | Decorator + CI guard (option A) | `validation-parity-contract` todo; Validation parity contract subsection |
| C11 | Per-call commits during turn, squash on Apply, transcripts + 7d retention (option A) | `ai-pipeline-writer` todo; Bounded non-convergence rewrite |
| M14 | No class metadata; tools are class-agnostic (option C, user override) | `ai-tool-library` todo |
| M16 | `scenarios.json` peer + opt-in export bundle (option A) | `scenarios-step` todo; new `export-deal-package` todo; Studio Document section; projection matrix |

## Decisions made during fold-back (parent proposed sensible defaults — flag if you want changes)

| Finding | Parent-proposed default | Plan diff section |
|---|---|---|
| M12 (Storybook CI ops) | Pinned Chromium; Linux-only for screenshots; SHA-pinned Geist self-hosted; OKLCH compiled to sRGB at build; 0.1% pixel threshold; 14d artifact retention; auto-quarantine flaky stories for 7d; scope screenshot regression to Layer-3 core variants only; 8min p95 runtime budget | "Storybook is required, not optional" subsection (CI operational contract bullets) |
| M13 (Live-preview rejection narrative) | If the spike rejects always-on preview, the Vision narrative is amended in this plan document BEFORE `live-preview-cashflow` opens; Phase 4 acceptance gate added | "Performance spike — Phase 1 prerequisite" subsection (Decision gate paragraph); Phase 4 sequencing line |
| M15 (Phase 0 independence) | Separate invocation, read-only, R1 tier, cross-family preference with logged exception otherwise, multi-pass with closure artifact recording reviewer identity / model / family / verdict / commit SHAs | `architectural-review-pass` todo; "Phase 0 — Plan-level architectural review" subsection (new Independence criteria + Closure artifact paragraphs) |

## Audit of pass-2 findings against revised plan

### Blocking

**B5 — Sidecar / provenance / export contract inconsistency** — RESOLVED.

- Sidecar contract is now stated once and once only: `sidecar.json` next to `deal.json` in the deal git repo, git-tracked (rolls with IR on `git checkout`), NEVER part of the canonical export. Sidecar schema is exactly `schema_version` + `layout_overrides: dict[entity_id, {x, y, collapsed, ...}]` + `ui_preferences: dict[str, Any]`.
- AI provenance moved entirely to git commit metadata (author + message + machine-readable footer) plus per-turn detail in `turn_transcripts/{turn_id}.json` (git-tracked, not exported).
- AI-off contract updated: no `ai/turn-*` branches created, no `author=ai:writer:*` commits written, no `turn_transcripts/` files. Removed the "sidecar's AI provenance slot" wording.
- Field-class projection matrix rewritten to match. Per-entity notes go in IR `description` fields; provenance is its own field class living in commit metadata + transcripts; layout sidecar is its own field class; scenarios are their own field class in `scenarios.json`.
- **Plan diffs**: "Studio Document ⊋ Engine IR" intro paragraph; "What lives where" table; "Sidecar is repo-tracked but never exported" subsection; `studio-document-persistence-and-migration` todo; "AI-off isolation contract" subsection bullet on provenance.

**B6 — Byte-identical IR round-trip not implementable as written** — RESOLVED.

- Invariant scoped to canonical-post-migration: after the one-time `system:migration` commit, every subsequent open-then-save-without-edits is byte-identical to the previous `deal.json`. Pre-migration input bytes are explicitly NOT preserved — that tradeoff is now stated rather than implied.
- Multi-target consolidation REMOVED from the compile step. Canonicalization is exclusively opt-in via linter quick-fixes that produce explicit user-attributed commits.
- Test contract rewritten to cover three cases: post-migration round-trip; migration determinism across repeated runs; idempotent second load.
- **Plan diffs**: "Compile step (still present, but lighter)" subsection; "IR round-trip idempotency (canonical-post-migration)" subsection (full rewrite); `studio-document-and-store` todo.

**B7 — Real-git-per-deal foundation not operationally ticket-safe** — RESOLVED.

- Merge strategy locked in: application-level typed field merge over git's commit graph. JSON-aware gitattributes merge driver explicitly NOT pursued in v1. Conflict UX is `MERGE_CONFLICT` diagnostics with Take-ours / Take-theirs / Resolve-manually quick-fixes — no `<<<<<<<` text markers in JSON.
- pygit2 added to `pyproject.toml` as a hard dep, libgit2 CLI subprocess fallback behind the same Python interface.
- New "Operational design (Phase 1 prerequisite)" subsection added covering: dependency lock-in, scale assumptions (~10K deals/tenant; per-deal repo footprint budgets), backup/restore (`git bundle`), concurrency/locking (per-repo file lock with bounded timeout), branch GC policy (ephemeral GC on Apply/Discard; 7d retention with PII redaction at GC; `what-if/*` never auto-GC'd), export hardening (export function literally cannot reach sidecar/scenarios/transcripts), corruption recovery (`git fsck` on every load + restore-from-bundle), `.git/` size monitoring with operational alerts.
- **Plan diffs**: "Three-way merge specifically" paragraph; new "Operational design (Phase 1 prerequisite)" subsection; `ir-version-control-foundation` todo.

### Critical

**C9 — AI writer branch flow store state under-specified** — RESOLVED.

- New `DocumentSession` abstraction defined: each session carries (branch_name, base_sha, working_tree, validation_target, commit_target, zundo_history, ui_role). Sessions coexist; the user's main session is unaffected during ephemeral AI/solver sessions. Validation runs against the ACTIVE session's working_tree so repair turn N sees turns 1..N-1.
- Patch lifecycle rewritten in terms of DocumentSession + git branch. Apply creates exactly one squash-merge commit on `main` AND exactly one zundo entry in the main session.
- Test contract spells out: Discard leaves main HEAD + main session working_tree + main session zundo history unchanged; Apply creates exactly one squashed commit + one zundo entry + populated transcript; preview-mode panes render the ephemeral session without touching main session state.
- **Plan diffs**: "Reactive store with typed actions, DocumentSession model" subsection (renamed + rewritten); "Patch lifecycle for solver results and AI proposals" subsection (full rewrite); "Bounded non-convergence" subsection (full rewrite); `studio-document-and-store` and `ai-pipeline-writer` todos.

**C10 — Diagnostic catalog generator/guard deferred decision** — RESOLVED.

- Decorator + CI guard chosen. AST-based generator explicitly NOT pursued in v1.
- Mechanism specified: `@diagnostic_code(...)` decorator on Pydantic validators; typed registry on TS worker side; `pnpm diagnostic:check` enforces (a) decorated validators must have catalog entries, (b) `owner ∈ {worker, both}` codes must have TS implementations, (c) severity/path-schema divergence fails CI, (d) added validators without same-commit catalog updates fail CI.
- **Plan diffs**: "Validation parity contract" subsection (Enforcement bullet); `validation-parity-contract` todo.

**C11 — Commit-per-tool-call retention unbounded** — RESOLVED.

- During-turn behavior: one commit per validated tool call on the ephemeral branch (enables mid-turn rollback + per-call review).
- Apply behavior: squash-merge into ONE commit on `main`; per-call detail moves to `turn_transcripts/{turn_id}.json` (git-tracked, not exported).
- Discard / non-convergence behavior: branch deleted; archive in `discarded_branches/{turn_id}/` for 7d; at GC time, verbatim tool-call args are redacted to `(model, tool_name, arg_shape)` summaries; full-prompt PII NOT retained past 7d.
- Tests: discarded branches inaccessible after retention expiry; git GC does not remove applied history; export never includes discarded transcripts.
- **Plan diffs**: "Bounded non-convergence" subsection; `ai-pipeline-writer` todo; Operational Design subsection (Branch GC policy bullet); projection matrix (AI turn transcript row).

### Major

**M12 — Storybook CI cost / flakiness** — RESOLVED with parent-proposed defaults.

- Pinned browser, Linux-only screenshots, SHA-pinned fonts, OKLCH compiled to sRGB at build, explicit threshold, artifact retention, auto-quarantine, scope-limited to Layer-3 core variants, runtime budget. **Flag if you want any of these tightened or loosened.**
- **Plan diffs**: "Storybook is required, not optional" subsection (CI operational contract bullets).

**M13 — Live-preview rejection narrative conflict** — RESOLVED with parent-proposed defaults.

- Decision gate added: if the spike rejects always-on preview, the plan author MUST amend the Vision narrative and Phase 4 acceptance contract BEFORE `live-preview-cashflow` opens. The amendment becomes part of this plan document.
- **Plan diffs**: "Performance spike — Phase 1 prerequisite" subsection (Decision gate paragraph); Phase 4 sequencing line.

**M14 — Tool class-metadata** — RESOLVED via user override.

- Tools carry NO `recommended_for` metadata. Asset-class recommendation ordering is handled by the registry at the cmdk palette / AI prompt manifest level only. Layer-3 tools' class names communicate fit; validation handles structural mismatches via existing IR-consistency rules.
- **Plan diffs**: `ai-tool-library` todo.

**M15 — Phase 0 independence** — RESOLVED with parent-proposed defaults.

- Five-criteria independence contract added: separate invocation, read-only permissions, R1 tier, cross-family preference, multi-pass with closure artifact.
- Closure artifact spec added: reviewer identity per pass, model + tier per pass, family vs author, verdicts, plan-revision commit SHAs.
- **Plan diffs**: `architectural-review-pass` todo; "Phase 0 — Plan-level architectural review" subsection.

**M16 — ScenarioSet field class** — RESOLVED via user direction.

- `scenarios.json` is a peer artifact to `deal.json` in the deal git repo (git-tracked, rolls with IR, NOT exported by default).
- New `export-deal-package` Phase 4 ticket added: opt-in bundle (deal.json + user-selected reference_scenarios + computed decrement table + auto-generated README) for counterparty handoff / prospectus replication.
- Field-class matrix gains a Scenario set row.
- **Plan diffs**: `scenarios-step` todo; new `export-deal-package` todo; projection matrix; Phase 4 sequencing line.

### Pass-2 partial-resolution items now closed

| Pass-1 finding | Now | Where |
|---|---|---|
| B2 (persistence operational story) | RESOLVED by B5 + B7 fold-back (sidecar contract pinned + git ops operational design) | Operational Design subsection; `studio-document-persistence-and-migration` todo |
| B3 (projection matrix rewrite) | RESOLVED by B5 fold-back (matrix rewritten to match minimized sidecar) | Field-class projection matrix |
| C3 (parity mechanism pick) | RESOLVED by C10 fold-back (decorator + guard chosen) | Validation parity contract subsection; `validation-parity-contract` todo |
| M2 (RAG governance) | RESOLVED with parent-proposed gate (governance MUST be picked before AI writer beta release; `docs/architecture/rag_governance.md` artifact required; until then writer is internal-only behind a feature flag) | "Governance (deferred)" subsection (new gate paragraph) |
| M8 (Apply/Discard/zundo) | RESOLVED by C9 fold-back (zundo is per-session; Apply produces exactly one zundo entry on main session; Discard leaves main session zundo unchanged) | Patch lifecycle rewrite |
| M11 (AI-off provenance suppression) | RESOLVED by B5 + C11 fold-back (removed sidecar provenance references; spelled out that no ai/* branches, no ai:writer:* commits, no turn_transcripts/ in AI-off mode) | AI-off contract bullet |
| n1 (four-layer wording) | RESOLVED (replaced "four-layer" → "five-layer" in the non-negotiable principles section) | "Non-negotiable principles" section |

### Minor

**m5 — Phase 2 diagram leakage** — RESOLVED.

- Spreadsheet pane: Bonds entry split into Phase-2 fields + Phase-3-ONLY (`loss_treatment`, `writeup_enabled`); Pay Rules now explicitly Phase-2; Branches and Aggregate Groups annotated as PHASE-3-ONLY with the rationale (Proposal C / D introduces the schema).
- Graph pane: Phase-2 node types and Phase-3+ node types clearly separated; AggregateGroup wrapper marked Phase-3-only; Branch container marked Phase-3-only.
- Structure mermaid diagram: pane subgraph labels split into "Phase 2 tabs:" and "Phase 3+ tabs:" / "Phase 3+ node types:".
- **Plan diffs**: Spreadsheet pane subsection bullets; Graph pane subsection bullets; Structure diagram mermaid.

### Nit

**n5 — "filtered by asset class" wording** — RESOLVED.

- "Honored feedback" table row 3: replaced "filtered by asset class" with "ordered by asset-class recommendation; every template remains available regardless of detected class".
- **Plan diffs**: Honored feedback table row 3.

## Net effect on plan

- **New tickets added**: 1 (`export-deal-package` in Phase 4).
- **Modified ticket contracts**: 7 (`architectural-review-pass`, `studio-document-and-store`, `ir-version-control-foundation`, `studio-document-persistence-and-migration`, `validation-parity-contract`, `ai-tool-library`, `ai-pipeline-writer`, `scenarios-step`).
- **New architectural subsections**: 2 ("Operational design (Phase 1 prerequisite)" under IR version control; "Reactive store with typed actions, DocumentSession model" renamed and expanded).
- **Subsections rewritten**: 5 ("Studio Document ⊋ Engine IR" intro; "What lives where" table; "Sidecar is repo-tracked but never exported"; "IR round-trip idempotency"; "Compile step"; Field-class projection matrix; Patch lifecycle; Bounded non-convergence; Storybook CI; Phase 0 review).
- **Phase 4 sequencing**: gains `export-deal-package` between `scenarios-step` and `run-and-outputs-step`.

## What Phase 0 closure requires next

1. **You verify this artifact.** Spot-check 2-3 sections by reading the cited plan diffs. If anything reads as not actually closed, flag it now and I'll iterate.
2. **You confirm the parent-proposed defaults for M12, M13, M15** (or override them).
3. **No pass-3 review is required per your earlier direction.** Once you confirm, Phase 0 closes and I generate the closure artifact (`docs/architecture/structuring_studio_redesign_phase0_closure.md` per M15) and we open Phase 1 ticket decomposition for `architectural-review-pass` → completed, then begin the Phase 1 ticket-decomposition workflow for the foundation tickets.

## Open questions for the user

None. The six original open questions remain settled. The new questions raised in pass 2 are all resolved by user direction or parent-proposed defaults flagged above for your override.
