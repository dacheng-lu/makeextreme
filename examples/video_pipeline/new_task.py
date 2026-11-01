"""Create a video-brief task directory for makeextreme.

    python new_task.py <task_dir> <url-or-local-file> [--label TEXT] [--asr-python PATH]

Writes bin/ (the six stage scripts), input.url, input.label and stages.json. Then:

    python -m makeextreme run <task_dir>        # runs until `deliver` waits for approval (exit 4)
    python -m makeextreme approve <task_dir> deliver
    python -m makeextreme run <task_dir>        # delivers (exit 0)

`input.label` is what the brief says about its source; keep it the same when you compare two runs of the same
video fetched from different places.
"""
import argparse
import json
import os
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
DUR = "ffprobe -v error -show_entries format=duration -of csv=p=0"


def stages(asr_python):
    return [
        {"id": "fetch", "run": "sh bin/fetch.sh",
         "check": "test -s src.mp4 && %s src.mp4 | awk '{exit !($1>1)}'" % DUR,
         "deps": ["input.url", "bin/fetch.sh"]},
        {"id": "audio", "run": "sh bin/audio.sh",
         "check": "test -s audio.wav && awk -v a=\"$(%s src.mp4)\" -v b=\"$(%s audio.wav)\" "
                  "'BEGIN{d=a-b; exit !(d<1 && d>-1)}'" % (DUR, DUR),
         "deps": ["src.mp4", "bin/audio.sh"]},
        {"id": "asr", "run": "%s bin/asr.py audio.wav asr.txt" % asr_python,
         "check": "test \"$(grep -c '^\\[' asr.txt)\" -ge 1",
         "deps": ["audio.wav", "bin/asr.py"]},
        {"id": "frames", "run": "sh bin/frames.sh",
         "check": "awk -v n=\"$(ls frames | wc -l)\" -v d=\"$(%s src.mp4)\" "
                  "'BEGIN{e=int(d/2); exit !(n>=e && n<=e+2)}'" % DUR,
         "deps": ["src.mp4", "bin/frames.sh"]},
        {"id": "ocr", "run": "sh bin/ocr.sh",
         "check": "test \"$(ls ocr | wc -l)\" -eq \"$(ls frames | wc -l)\" && test \"$(ls ocr | wc -l)\" -ge 1",
         "deps": ["frames", "bin/ocr.sh"]},
        {"id": "assemble", "run": "%s bin/assemble.py" % asr_python,
         "check": "test \"$(grep -c '^## t=' brief.md)\" -eq \"$(ls frames | wc -l)\"",
         "deps": ["asr.txt", "ocr", "input.label", "bin/assemble.py"]},
        {"id": "deliver",
         "run": "mkdir -p deliver && cp brief.md deliver/brief.part && mv deliver/brief.part deliver/brief.md",
         "check": "cmp -s brief.md deliver/brief.md",
         "deps": ["brief.md"], "approval": "required"},
    ]


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument("task_dir")
    ap.add_argument("source")
    ap.add_argument("--label")
    ap.add_argument("--asr-python", default=sys.executable)
    a = ap.parse_args(argv)
    os.makedirs(a.task_dir, exist_ok=True)
    shutil.copytree(os.path.join(HERE, "bin"), os.path.join(a.task_dir, "bin"), dirs_exist_ok=True)
    url = a.source if "://" in a.source else "file://" + os.path.abspath(a.source)
    with open(os.path.join(a.task_dir, "input.url"), "w") as f:
        f.write(url + "\n")
    with open(os.path.join(a.task_dir, "input.label"), "w") as f:
        f.write((a.label or a.source) + "\n")
    with open(os.path.join(a.task_dir, "stages.json"), "w") as f:
        json.dump(stages(a.asr_python), f, indent=2)
        f.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
