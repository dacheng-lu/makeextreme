# Asset-pack stage template

A pack of generated assets fits Makeextreme's model when the stages are known
before the run and each stage can be checked on the real output. The model
calls are nondeterministic, so the runner cannot decide quality; it can decide
whether the contract artifacts exist and parse.

## Stages

```json
[
  {
    "id": "prompt",
    "run": "python3 bin/write_prompt.py > prompt.txt",
    "check": "test -s prompt.txt && grep -q 'OUTPUT CONTRACT' prompt.txt",
    "outputs": ["prompt.txt"]
  },
  {
    "id": "build",
    "run": "bin/build_assets.sh prompt.txt raw",
    "check": "test $(ls raw/*.svg | wc -l) -eq 8",
    "deps": ["prompt.txt", "bin/build_assets.sh"],
    "outputs": ["raw"]
  },
  {
    "id": "normalize",
    "run": "python3 bin/normalize_pack.py raw pack",
    "check": "test -s pack/manifest.json && test $(ls pack/*.svg | wc -l) -eq 8",
    "deps": ["raw", "bin/normalize_pack.py"],
    "outputs": ["pack"]
  },
  {
    "id": "verify",
    "run": "python3 bin/validate_svg_pack.py pack --manifest manifest.json --width 96 --height 64",
    "check": "test -s verify.json",
    "deps": ["pack", "bin/validate_svg_pack.py"],
    "outputs": ["verify.json"]
  },
  {
    "id": "publish",
    "run": "bin/copy_pack_to_ui.sh pack",
    "check": "test -d ../app/assets/cyberpunk-pack",
    "deps": ["pack", "verify.json"],
    "approval": "required",
    "outputs": ["../app/assets/cyberpunk-pack"]
  }
]
```

## What each check proves

- `prompt`: the prompt file exists and contains the output contract marker. It
  does not prove the prompt is good.
- `build`: the requested number of raw SVG files exists. It does not prove they
  parse or share a palette.
- `normalize`: the manifest and one file per ID exist. It does not prove IDs
  match.
- `verify`: the validator exits 0 and writes a report. It does not prove the
  visuals are acceptable; inspect the contact sheet separately.
- `publish`: an approval bound to the pack hash. Any later asset edit makes the
  approval stale.

## Recovery rules

- A rejected model output is not a failed stage unless the stage's own `check`
  fails. Do not auto-retry a nondeterministic builder in a loop.
- If the builder output is unstable, keep the approved pack and change one
  prompt variable at a time; record the rejected pass outside the task dir.
- Do not put credentials or model keys in `stages.json`, the prompt, or the
  output paths. Use the host's existing authenticated CLI.
- Human approval is required before publishing into a UI or any external target.

## Why this is only a template

The actual prompt and builder commands depend on the model host. This file
shows the stage shape and the checks; it is not a bundled generator. A real
task must provide `bin/` scripts and a pinned asset contract.
