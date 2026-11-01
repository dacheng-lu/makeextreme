import sys

from . import core

USAGE = ("usage: python -m makeextreme run <task_dir>\n"
         "       python -m makeextreme approve <task_dir> <stage>\n"
         "       python -m makeextreme resolve <task_dir> <stage> (--done | --retry)")


def main(argv):
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
