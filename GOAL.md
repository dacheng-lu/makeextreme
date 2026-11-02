# Goal: reliable execution, understandable from the first visit

Status: working goal, not a release claim or schedule. [ROADMAP.md](ROADMAP.md)
distinguishes released, owed and candidate work; [ARCHITECTURE.md](ARCHITECTURE.md)
records the design and known limitations.

## Outcome

Run known-stage tasks with checks against real outputs, recover after interruption,
and refuse to silently repeat or claim completion for an uncertain irreversible
action. Makeextreme remains independently usable; the host supplies identity,
permissions, scheduling and isolation.

## Acceptance targets

| Dimension | Target | Evidence needed |
| --- | --- | --- |
| Quality | Detect damaged declared outputs and recover without silently repeating uncertain actions. | Reproducible crash, changed-output, weak-check and approval cases; report failures and limits. |
| Content | A new visitor understands the purpose, setup, current behavior and limits. | Reproducible commands; working links and consistent English, Chinese and German entry points. |
| Function | Add capabilities for real execution failures, preserving standalone use. | A failing case, regression checks, compatibility and cost analysis for each change. |
| Browsing | The project is legible and navigable on mobile and desktop. | Inspect rendered pages at both widths, including logo framing, links and overflow. |

Time targets to test with first-time users, not measured claims: 30 seconds to
understand which project fits, 3 minutes to assess a case and limitations, and
10 minutes to run a minimal example after prerequisites are met. Record sample,
observations, failures and environment; do not claim success from maintainer trials.

## First milestone

1. Provide a standalone example that declares an output and demonstrates initial
   execution, a skip and recovery after output deletion. State precisely what it
   demonstrates; it is not an interruption or irreversible-action test.
2. Compare stage execution evidence with Longhaul's acceptance semantics. A
   shared versioned exchange and an end-to-end integration are candidates, not
   implemented capabilities. Both projects must continue to work separately.
3. Exercise success, interruption, changed output and uncertain external effects;
   never claim that checks or approvals establish identity or sandbox isolation.
4. Test onboarding and browsing with first-time users; log unresolved gaps.

## Improvement loop

Record a problem and a minimal reproduction, add a regression case, make the
smallest change, compare results and costs with the previous version, then review
and publish the evidence. Keep observed failures separate from assumptions, and
do not let model-written task records alter trusted execution or approval policy.

Stop a milestone when its cases pass and remaining gaps are documented; do not
add capabilities merely to increase scope. Human approval and host permissions
remain authoritative for consequential actions.
