import os
import sys

USAGE = ("usage: python -m makeextreme run <task_dir>\n"
         "       python -m makeextreme approve <task_dir> <stage>\n"
         "       python -m makeextreme resolve <task_dir> <stage> (--done | --retry)")

# Duplicated from core on purpose: on a non-POSIX platform `core` cannot even be
# imported (fcntl, /proc, process groups), so the guard has to run before that import.
EX_SPEC = 64

PLATFORM_REFUSAL = ("makeextreme is Linux-only: this platform has no fcntl, /proc or process "
                    "groups, so a stage could be left half-run. Nothing was started.")


def platform_refusal():
    """The refusal text for a platform the runner cannot support, else None."""
    return None if os.name == "posix" else PLATFORM_REFUSAL


def main(argv):
    refusal = platform_refusal()
    if refusal is not None:
        print(refusal, file=sys.stderr)
        return EX_SPEC
    from . import core
    if len(argv) == 2 and argv[0] == "run":
        return core.run(argv[1])
    if len(argv) == 3 and argv[0] == "approve":
        return core.approve(argv[1], argv[2])
    if len(argv) == 4 and argv[0] == "resolve" and argv[3] in ("--done", "--retry"):
        return core.resolve(argv[1], argv[2], argv[3])
    print(USAGE, file=sys.stderr)
    return core.EX_SPEC


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
