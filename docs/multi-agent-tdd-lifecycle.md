# Multi-Agent TDD Lifecycle — Plan → Tickets → Code → Review → Commit

A reusable methodology for driving non-trivial implementation work through a coordinated set of specialized agents. Designed for cases where you want strong correctness guarantees, an audit trail, and bounded cost.

This document is portable: it does not reference any specific project, codebase, or task. Copy it verbatim and hand to another agent (or human) as the methodology contract.

---

## The pattern at a glance

A single human (or lead agent) authors a plan. The plan is decomposed into atomic tickets by a **fresh agent of a different model family** from the plan author. Each ticket then goes through this strict lifecycle:

```
T1 (write failing tests)
   → I (implement until tests pass + full suite green)
       → R1 (review the diff; structured findings)
           → Fix pass (if findings) → R1 pass-2 (only if non-trivial findings)
               → Sign off → next ticket
```

Tests are written FIRST. Implementation is written to make those tests pass. Review is performed by a DIFFERENT agent than the implementer. Each step commits independently with a conventional-commit prefix (`test(...)`, `feat(...)`, `fix(...)`, `docs(...)`).

---

## Why it works

- **TDD-first prevents implementation-driven test scope creep.** The implementer cannot make the tests easier because the tests were committed before they touched code.
- **Cross-family review catches family-specific blind spots.** If GPT-family wrote the implementation, a Claude-family reviewer (or vice versa) sees the code with different priors and finds bugs the implementer's family tends to miss. Same-family review is detectably less effective.
- **Bounded review passes prevent infinite-loop perfectionism.** Two review passes max per ticket; tactical findings get parent-applied + parent-verified instead of a third review.
- **Per-ticket atomicity keeps regressions tractable.** When something breaks two weeks later, `git bisect` lands on a single ticket's commit set, not a ten-ticket mega-commit.
- **Audit trail by construction.** Every review writes to disk; every commit is a small atomic change with a structured message. The work is reviewable AFTER the fact without reconstructing context.

---

## Roles + capability tiers

Pick model families that are genuinely different (e.g., GPT family ≠ Claude family ≠ Gemini family). Same-model-different-version doesn't count as cross-family.

| Tier | Role | Typical model class | When |
|---|---|---|---|
| D1 | Decomposer — turns plan into atomic tickets | Strong reasoning model from a different family than the plan author | Once per todo, before any code is written |
| T1 | Test author — writes failing tests against the ticket spec | Fast capable code-generation model (cheap and fast matters here) | First step of every ticket |
| I1 | Implementer (high-capability) | Strongest reasoning model from the implementer's family | Tickets with novel architecture, concurrency, tricky algorithms, multi-system integration |
| I2 | Implementer (routine) | Mid-tier reasoning model from the implementer's family | Routine refactoring, CRUD, CLI scripts, well-defined transformations |
| I3 | Implementer (mechanical) | Fast model | Pure mechanical edits — formatting, renames, lint fixes. Optional |
| R1 | Reviewer | Strong reasoning model from a DIFFERENT family than the implementer; read-only mode | After every implementation; after every fix-pass IF non-trivial findings |

**Independence contract** (the non-negotiable):
- Each subagent invocation is a fresh transcript. No agent reviews its own output.
- Reviewers run read-only — they cannot modify code; they only produce structured findings.
- Cross-family preference is a hard preference; log an exception when not satisfied (e.g., "all R1-tier alternatives unavailable due to rate limits, fell back to same-family").

---

## Per-ticket lifecycle (the dance)

For each ticket in dependency order:

### Step 1 — T1 authors failing tests

Spawn a fresh agent. Give it: the ticket spec, the architectural-intent doc, any prior-art tests in the repo to mimic.

It must:
- Author every test file listed in the ticket's Test plan.
- Map each test function to one or more acceptance criteria (in the docstring).
- Test bodies must assert real behavior — no `assert True`, no `pytest.skip` to mask absent implementation, no stub assertions.
- Run the test suite and CONFIRM every new test FAILS (because the implementation doesn't exist). The failure mode is the TDD signal.
- Run the FULL repo suite to confirm existing tests still pass (the new tests should be the only failures).
- Commit with `test(<ticket-id>): failing tests for <short name>`.

T1 must NOT write any production code. If T1 finds a place where the test is not falsifiable, it surfaces that as an open question rather than relaxing the assertion.

### Step 2 — Implementer turns tests green

Spawn a fresh agent (different transcript than T1). Tier: **I1** if the ticket has novel architecture, concurrency, or tricky algorithms; **I2** otherwise.

Give it: the ticket spec, the T1 commit's diff (the tests pin the public API exactly), any architectural-intent docs, the relevant existing-code modules.

It must:
- Implement until all T1 tests pass.
- Run the FULL repo test suite (not just the new tests) to verify no regressions.
- NOT modify the T1 commit's tests. If a test is genuinely wrong, surface it; don't silently rewrite it.
- Commit with `feat(<ticket-id>): <short name>`.

### Step 3 — R1 reviews the implementation

Spawn a fresh agent in **read-only** mode. Cross-family from the implementer (and from prior R1 reviewers if pass-2).

Give it: the ticket spec, the implementation diff (`git show <impl-sha>` or `git diff <T1-sha>..<impl-sha>`), the architectural-intent doc.

R1 applies a structured reviewer checklist:
- **Test-to-acceptance mapping** — every AC has at least one test; no vacuous tests.
- **Public API stability** — no internal types leaking into caller code paths; public function signatures match what the tests imply.
- **Out-of-scope respected** — no scope creep; nothing the ticket explicitly excluded leaked in.
- **Phase / dependency correctness** — no forward references to unbuilt work; ticket's declared dependencies honored.
- **Code-quality** — type hints, no `print` statements in production code, no `shell=True` in subprocess calls, no proactive narration comments, errors normalized at module boundaries.
- **Edge cases** specific to the ticket (concurrency, idempotency, error handling, etc.).
- **Cross-cutting hygiene** — does it accidentally break invariants from prior tickets? Does it leak filesystem artifacts? Does it expose data that should be hidden?

Findings categorized as:
- **Blocking** — must fix before merge. AC violations, security holes, correctness bugs.
- **Critical** — should fix in same fix-pass. Architectural concerns explicitly required by the plan.
- **Major** — should fix; if not in this fix-pass, must be tracked.
- **Minor** — worth fixing for hygiene.
- **Nit** — optional.

Verdict thresholds:
- **APPROVE**: zero Blocking, zero Critical, zero Major.
- **APPROVE-WITH-CHANGES**: zero Blocking, zero Critical; ≥1 Major / Minor.
- **RETURN-FOR-REVISION**: ≥1 Blocking OR ≥1 Critical.

R1 must **write the review to disk** at a predictable path (e.g., `docs/<ticket-id>.r1-review-pass1.md`). The audit trail is only useful if the artifacts are discoverable. Do not rely on chat history.

### Step 4 — Fix pass (only if findings)

Spawn a fresh implementer (or resume the prior one — tradeoff: resumed agents have context cheaply, but fresh agents are independent of prior implementer reasoning). Give it: the R1 review on disk, the existing implementation, the existing tests.

Apply ALL Blocking + Critical + Major + Minor fixes. Nits are optional.

If the R1 review surfaced architectural ambiguity (a finding whose fix touches multiple tickets or rewrites public APIs), STOP and surface to the user with the trade-off — don't silently widen scope.

If you opt to apply small fixes parent-direct (without spawning an implementer subagent — appropriate for ≤10-line tactical patches), you must STILL parent-verify against the R1 findings checklist before committing.

Commit with `fix(<ticket-id>): apply R1 review findings`. Use HEREDOC for multiline messages so each finding is itemized.

Add regression tests for each non-Nit finding. The tests pin the closure so a future regression resurfaces the original concern.

### Step 5 — Final verification

Branch on the severity of the original R1 pass-1 findings:

- **Non-trivial findings** (≥1 Blocking OR ≥2 Critical): spawn a **fresh R1** (different transcript than pass-1) for a pass-2 review on the fix-pass diff only. The pass-2 review verifies each pass-1 finding is genuinely closed AND checks for new findings introduced by the fix-pass. Write the pass-2 review to disk too.
- **Otherwise** (R1 pass-1 had only Major / Minor findings, or pass-1 returned APPROVE): parent-verify the fix-pass diff yourself against the R1 findings checklist and proceed. No third agent.

If R1 pass-2 returns RETURN-FOR-REVISION:
- If the finding is tactical (a sibling-endpoint miss, a 5-line fix, a small additional pattern), apply directly + parent-verify.
- If the finding indicates the ticket spec is genuinely flawed, STOP and surface to the user with the option to re-decompose or scope down.

### Step 6 — Sign off + move to next ticket

Update any tracking (TodoWrite or equivalent). Move to the next ticket in dependency order.

If the entire todo's ticket set is now merged, perform the closure protocol (below) before starting the next todo.

---

## Decomposition protocol (start of each todo)

Before any T1 fires, decompose the todo into 3-7 atomic tickets.

1. Spawn D1 (cross-family from the plan author and from anticipated implementers).
2. Give D1: the plan's section on this todo, the broader architectural docs, any cross-todo dependency hints, the canonical ticket envelope shape (Scope / Files affected / Dependencies / User journeys / Acceptance criteria / Test plan / Out-of-scope notes), and a reference ticket from a prior todo if one exists.
3. D1 produces a single markdown file with:
   - A title and parent-todo identifier.
   - A TDD-note at the top stating tests are authored first.
   - A mermaid dependency graph of the tickets.
   - Each ticket in the standard envelope.
   - A sequencing-impact section explaining what merge order is required and what cross-todo dependencies exist.
   - A flags-for-the-reviewer section noting non-obvious decisions or tuning knobs.
4. **Architecturally heavy todos**: D1 + R1 review of the decomposition itself, iterate ≤2 R1 passes, then approve.
5. **Routine todos**: D1 once + parent-verify against the same objective reviewer checklist; no R1 review of the decomposition.

Commit the decomposition file as `docs(<phase>): decompose <todo>` BEFORE starting T1 on the first ticket. The decomposition is durable; the work depends on it.

---

## Cost discipline

- ONE D1 per todo + ≤2 R1 review passes per ticket + ONE fix-pass per R1 finding-set + parent-verify = the budget. Beyond that, surface.
- For routine R1 findings post-implementation, parent-verify the fix-pass diff rather than spawning a third R1.
- Cache prompt prefixes where possible (resume parameter on the same ticket's same agent preserves context cheaply when continuing a multi-step task).
- Do not re-read the entire plan every turn. Load it once at session start and keep relevant excerpts in working memory.
- If you find yourself in a third+ review-pass loop, that's a strong signal the ticket spec is wrong — surface to the user with a re-decomposition proposal.

---

## Stop conditions (surface to user — and ONLY these)

1. **Architectural ambiguity that touches multiple tickets** — present the trade-off and recommend one option; ask the user to confirm or override.
2. **Contradiction with a previously-locked design decision** — stop and surface; do not unilaterally re-open settled architecture.
3. **R1 pass-2 still RETURN-FOR-REVISION on a ticket** — signals the ticket spec is flawed; surface with the R1 findings and propose either re-decomposing the ticket, scoping down, or applying a parent-direct tactical fix if the finding is genuinely sibling-endpoint-style not spec-flawed.
4. **Subagent infrastructure failure** that can't be worked around with capability-tier fallbacks (rate limits across all alternatives; model unavailability blocking the workflow).
5. **Completion of each ticket** — brief 1-2 sentence status note, NOT a question, continue immediately to the next ticket.
6. **Completion of each todo** (all tickets merged + closure artifact written + reviews archived) — summary update + ASK user whether to continue to the next todo or pause.
7. **Discovery of work outside the plan** — if you encounter something that isn't in the plan or contradicts it, stop and surface; do not silently extend scope.

### Do NOT surface

- Tactical implementation choices the implementer subagent can make.
- R1 findings that are tactical (apply via fix pass + parent-verify).
- Subagent prompt details, model substitutions within a tier, or routine commit messages.
- Sequencing reshuffles within a ticket set — the dependency graph governs.

---

## Commit discipline

- One logical change per commit. T1 tests = one commit. Implementation = one commit. Fix pass = one commit. Decomposition = one commit. Closure = one commit.
- Conventional-commit-style prefixes: `test(<scope>):`, `feat(<scope>):`, `fix(<scope>):`, `docs(<scope>):`, `chore(<scope>):`.
- Use HEREDOC for multiline commit messages so they survive shell escaping.
- Do NOT push without explicit user instruction.
- Do NOT amend commits — use a follow-up commit if a small correction is needed (amends destroy audit trail).

---

## Closure protocol (after every todo completes)

When all tickets in a todo are merged:

1. Write a single-page closure summary at `docs/<phase>/<todo>.closure.md` capturing:
   - Status, date, branch, final commit, test-suite count.
   - Decomposition lifecycle audit (decomposer, reviewer, verdicts, output).
   - Per-ticket lifecycle table (T1 commit, implementer + tier, R1 pass-1 verdict + findings count, R1 pass-2 verdict if applicable, final commit, notes).
   - Independence-contract attestations (cross-family preserved, separate invocations, read-only reviewers, parent-direct fix log).
   - Architectural decisions made during execution (pattern: trigger → decision → where it now lives in code).
   - Cost-discipline tally (number of D1/T1/I/R1 dispatches; parent-direct fixes; stop-condition surfaces).
   - Outstanding work captured separately (or "None").

2. Move all the todo's R1 review files into `docs/<phase>/archive/` via `git mv` (preserves blame).

3. Keep in the active directory: the ticket spec, the closure doc, optionally a handoff doc if pausing mid-phase.

4. Commit with `docs(<phase>): closure summary + archive R1 reviews after <todo> close`.

5. Surface to the user (stop condition 6) with a brief summary and ask which todo to take on next.

---

## Anti-patterns (don't do these)

- **Skipping T1.** Tempting when a ticket feels "obvious." Don't. The TDD signal is what proves the implementer didn't shortcut.
- **Reviewing your own code.** Even with a fresh transcript, same-family-same-context reviewing produces detectably worse findings. Cross-family or skip the review entirely (better to skip than to fake independence).
- **Letting the reviewer write code.** R1 is read-only. If R1 starts proposing patches, you're conflating roles and you'll lose the independence guarantee.
- **Amending commits.** The atomic-per-step commit log is the audit trail. Amend = audit gap.
- **Silently widening scope on a fix-pass.** If R1's finding requires touching a sibling ticket's code, surface and ask. Don't quietly rewrite the public API of an already-merged ticket.
- **Reading the plan every turn.** Costs token budget for no incremental information. Load once.
- **Forgetting to write the review to disk.** If the audit trail isn't on disk, it doesn't exist. The closure doc relies on review files being discoverable.
- **Resumed agent reviewing fresh agent's output.** Fine for sequential implementer steps; NOT fine for review independence. R1 must be a fresh transcript.

---

## Worked example sketch (illustrative, not prescriptive)

Suppose the plan calls for "add a payment-processing module with retry semantics." A todo `payments` decomposes into 4 atomic tickets:

```
pay-1 (data model + persistence)
   → pay-2 (idempotency keys + dedup)
       → pay-3 (retry / backoff state machine)
           → pay-4 (HTTP API surface)
```

For `pay-3` (the architecturally interesting one — retry semantics, race conditions):

```
T1 (gpt-5.3-codex-high-fast)
  writes tests/test_retry_state_machine.py asserting:
    - exponential backoff with jitter bounds
    - max-attempts honored
    - state machine transitions are idempotent on duplicate events
    - 12 assertions across 6 test functions
  commits "test(pay-3): failing tests for retry state machine"

I1 (claude-4.6-opus-high-thinking)
  reads ticket + T1 diff
  implements retry_state_machine.py
  runs full suite → all green
  commits "feat(pay-3): retry state machine with bounded backoff"

R1 (gpt-5.5-extra-high, readonly, fresh)
  reviews the diff
  writes docs/pay-3.r1-review-pass1.md
  verdict RETURN-FOR-REVISION
    Blocking: race between retry-counter increment and state-write
    Major: backoff jitter not seeded deterministically (test fragility)

I1 fix-pass (claude-4.6-opus-high-thinking, fresh)
  applies both fixes + adds 2 regression tests
  commits "fix(pay-3): apply R1 review findings"

R1 pass-2 (gpt-5.5-extra-high, fresh, different transcript)
  reviews fix-pass diff only
  writes docs/pay-3.r1-review-pass2.md
  verdict APPROVE
  Both findings closed; no new findings.

Sign off. Move to pay-4.
```

After all 4 payment tickets merge, write `docs/payments.closure.md`, archive the 8 review files, ask user whether to continue to the next todo.

---

## TL;DR cheat sheet

| Phase | Who | Mode | Deliverable | Commit prefix |
|---|---|---|---|---|
| Plan → tickets | D1 (cross-family from plan author) | write | `<todo>.md` ticket envelope | `docs(<phase>): decompose <todo>` |
| Failing tests | T1 (fast code-gen model) | write | failing tests, full suite still mostly green | `test(<ticket>): failing tests for ...` |
| Implementation | I1 / I2 (implementer family, capability-tiered) | write | tests green, full suite green | `feat(<ticket>): ...` |
| Code review | R1 (cross-family from implementer) | read-only | `<ticket>.r1-review-pass1.md` with structured findings | (no commit by R1; parent commits) |
| Fix pass | I1 / I2 (fresh) or parent-direct for tactical | write | review findings closed + regression tests | `fix(<ticket>): apply R1 review findings` |
| Final verification | R1 pass-2 (fresh) for non-trivial findings; parent-verify otherwise | read-only or parent | pass-2 review on disk OR parent-verify note | (commit only if pass-2 finds new issues) |
| Todo closure | parent | write + archive | `<todo>.closure.md` + `git mv` reviews to `archive/` | `docs(<phase>): closure summary + archive R1 reviews after <todo> close` |

---

## How to give this to another agent

Hand them:
1. This document (verbatim).
2. The plan / spec they're driving from.
3. Their starting state (branch, last commit, test baseline).
4. A pointer to whatever ticket/decomposition framework you're using.
5. The list of stop conditions specific to your project (the seven above are a portable starting set).

The agent should ASK once at session start which todo to take on (don't silently pick architecturally-heavy work), then proceed autonomously through the lifecycle reporting only at the stop-condition cadence.
