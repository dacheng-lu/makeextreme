# First recovery: a deleted output

This standalone example needs Linux and Python 3. Run from the repository root;
the package is not installed. It uses a temporary directory and performs no
network calls. It demonstrates output deletion and rerun, not crash recovery.

```bash
workdir=$(mktemp -d)
cat > "$workdir/stages.json" <<'JSON'
[{"id":"hello","run":"echo hello > out.txt","check":"test -s out.txt","outputs":["out.txt"]}]
JSON
python3 -m makeextreme run "$workdir"
python3 -m makeextreme run "$workdir"  # skip: output matches
rm "$workdir/out.txt"
python3 -m makeextreme run "$workdir"  # changed output: execute again
test "$(cat "$workdir/out.txt")" = hello
python3 - "$workdir" <<'PY'
import json, sys
from pathlib import Path
task = Path(sys.argv[1])
events = [json.loads(line) for line in (task / 'journal.jsonl').read_text().splitlines()]
names = [event['ev'] for event in events]
assert names.count('start') == 2 and names.count('skip') == 1, names
print('Verified: two starts, one skip, and output restored.')
PY
printf 'Example files: %s\n' "$workdir"
```

The content check verifies only this example. A stage without declared
`outputs` is not rechecked before a skip. Approval cannot establish who approved,
and a real external effect may be uncertain after interruption; see the
[README boundaries](../README.md#english) before using it for such work.
