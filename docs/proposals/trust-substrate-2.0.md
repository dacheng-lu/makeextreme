# Proposal — Makeextreme 2.0: a sandbox provider and per-stage capabilities

Status: **proposed, not decided, not scheduled.** This is a design record for discussion.
Nothing here is implemented; the current runner (1.2.0) does not have a sandbox, does not
enforce capabilities and does not know what an effect is. Do not read this page as a
release plan.

## Why

The runner already decides "done" from artifacts and refuses to repeat an uncertain
irreversible stage. What it cannot say is *where* a stage ran, *what it was allowed to
touch*, or *whether its effect can be undone*. Any higher-layer system that wants to give an
agent more autonomy needs those three answers from the execution layer, with evidence.

The north star is the same for the three projects: the least human attention for the most
value. A capability that does not reduce a human decision is not added.

## What 2.0 would add

1. **Sandbox provider interface.** `prepare(task, stage) -> handle`, `run(handle, command)`,
   `teardown(handle)`, `inspect(handle) -> facts`. The first implementation is Linux
   bubblewrap (or Landlock where bwrap is unavailable). Without a provider, the runner keeps
   today's behaviour and says so in the journal; a task that *requires* isolation refuses to
   run unisolated (exit 64) instead of silently degrading.
2. **Per-stage capability declaration.** A stage may declare: writable paths (default: its
   own outputs), readable paths, reachable hosts (default: none), environment variables it may
   receive (default: none from the host), and whether it may spawn children. A violation stops
   the stage, writes the rule to the journal, and does not retry. Unknown fields are refused
   at load, not ignored.
3. **Effect classes.** `pure`, `reversible`, `irreversible`, `unknown`; `unknown` is treated
   as irreversible. The class is declared, checked against the capabilities, and recorded with
   the evidence. An irreversible stage still requires an approval bound to its artifact hash.
4. **Credential broker.** A stage never receives a real secret. It receives a short-lived
   handle scoped to one host and one operation; the broker substitutes it at the boundary and
   records the substitution. `secret_scan` grows an outbound direction: a stage that tries to
   send a secret-shaped value fails the stage and the journal names the rule.
5. **Leases.** One stage instance holds a lease with an expiry. A second worker that finds a
   live lease refuses (exit 3); an expired lease is recovered by the existing crash path. The
   lease is in the journal, not only in memory.
6. **Shadow mode and promotion.** A new autonomous behaviour first runs in shadow: it records
   what it would have done, executes nothing, and compares with the human decision. Promotion
   to the next autonomy level is a human decision backed by that record.

## Autonomy ladder (shared with Longhaul and FlowLore)

| Level | Behaviour | Required constraint | Human involvement |
|---|---|---|---|
| L0 | record only | read-only | review afterwards |
| L1 | read/write inside the task directory | filesystem isolation, no network | none |
| L2 | whitelisted egress, read-only API | L1 + egress list + credential broker | exceptions only |
| L3 | publish, pay, message, write production | L2 + approval bound to the content hash | one concrete question each time |

Promotion is decided by a person from the shadow record; it is never automatic and never
inferred from a passing test.

## Acceptance (each with a negative control)

- A stage writes outside its declared paths → refused, journal names the rule.
- A stage connects to an undeclared host → refused, no connection attempt is retried.
- A stage reads a host secret from its environment → refused; the value never appears in a log.
- A worker whose lease expired keeps running → its next write is refused as stale.
- An `unknown`-effect stage is requested twice → the second execution is refused.
- The same task, run with and without a provider, produces the same artifacts and the same
  journal entries except the isolation facts. A missing provider is recorded, not hidden.

## Non-goals and limits

- This is not a security proof. Kernel escapes, a compromised host, side channels and a
  malicious provider are out of scope. Approval is not isolation, and neither is a sandbox
  a proof of safety.
- No identity: the host supplies identity and permissions; Makeextreme records what it was
  told and what it observed.
- No scheduler and no distributed store. One task directory, one lease, the host's filesystem.
- If a proposed capability does not remove a human decision or a demonstrated failure, it is
  not built. The v1.3 measurement in Longhaul decides whether the 2.0 direction is worth it;
  if that baseline shows no benefit, this proposal is withdrawn.

## Order

M0 finish the existing P0 items → M1 shared contract v0 and one end-to-end release-digest →
M2 provider + capability enforcement → M3 credential broker + outbound scan → M4 leases +
independent verification + cluster cases → M5 shadow mode + promotion + attention metrics →
M6 MCP surface and one framework adapter. Each milestone is a PR with evidence, failures and
limits, never a direct push to `main`.

## What must not change

The existing principles stay: a stage is done only from artifacts; an uncertain irreversible
stage is never repeated automatically; the runner writes no approvals; the host owns identity,
permissions and isolation; a failing case precedes a capability, and an unproven benefit is
not claimed.
