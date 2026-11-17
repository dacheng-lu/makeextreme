# GitHub Action: an explicit same-job retry

The root `action.yml` is a small composite action for Linux runners with Python 3.
It runs the repository's own Python module on a caller-supplied task directory;
it does not install a package, fetch a dependency, retry, approve, or persist state.
`task-dir` can be absolute or relative to `GITHUB_WORKSPACE`. The task must already
contain a valid `stages.json` and everything those stages need.

The [example workflow](../.github/workflows/action-smoke.yml) runs a local action
from a checkout, fails one stage deliberately, repairs its prerequisite, then
invokes the action again in the **same job**. Both calls use the same temporary task
directory; the second skips the checked first output and completes the report.
`continue-on-error` is only for the deliberately failed demonstration; it is not
an automatic recovery policy. The [fixtures](../examples/github-action/) are
local files, not an external user's pipeline or evidence of adoption.

To use the action from another repository, check out the caller's files, select a
trusted task directory, and replace `<reviewed-full-commit-sha>` with an actual
commit containing `action.yml`:

```yaml
steps:
  - uses: actions/checkout@v4
  - uses: dacheng-lu/makeextreme@<reviewed-full-commit-sha>
    with:
      task-dir: path/to/task
```

The first release/tag is not created by this example. A GitHub-hosted runner normally
uses a fresh machine per job; this action does **not** restore the task directory
across jobs or workflow runs. Resuming there needs an explicitly designed, trusted
storage and concurrency strategy for the entire task directory and its inputs and
outputs. That strategy is not supplied or verified here; do not use a mutable cache
as an approval or effect-safety guarantee. Within an intact task directory,
`task.json` is authoritative; the journal can lag it after a crash.

Normal interrupted or failed stages may be retried and may repeat their side
effects. A stage explicitly marked `approval: required` becomes `uncertain` after
failure or interruption and is not automatically retried; an operator must inspect
the external outcome and resolve it. Approval binds content, not a proven identity.
Even this rule is not an exactly-once guarantee for an external system. Read the
[runner contract](../README.md#english) before using external effects.

`stages.json` contains shell commands: use only trusted tasks and sources. Do not
run untrusted pull-request code with secrets, write tokens, or other privileges.
This action inherits the workflow's environment and permissions and does not grant
or restrict them. Exit codes, including failure, waiting for approval and uncertain
state, are passed through; the caller must decide what to do next.
