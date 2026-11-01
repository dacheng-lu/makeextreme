"""Stage 6: assemble brief.md from the transcript and the OCR text. Deterministic: no model, no clock.

Every line says where it came from (speech recognition vs on-screen text), because the two are different kinds
of evidence and neither is the video's own caption track.
"""
import os
import re

segs = []
for line in open("asr.txt", encoding="utf-8"):
    m = re.match(r"\[([\d.]+)-([\d.]+)\] (.*)$", line.rstrip("\n"))
    if m:
        segs.append((float(m.group(1)), float(m.group(2)), m.group(3)))

label = open("input.label", encoding="utf-8").read().strip()
out = ["# Video brief (machine-assembled, not edited)", "",
       "- source: %s" % label,
       "- speech: Whisper small, ASR cached by audio hash (not the video's captions)",
       "- on-screen text: tesseract chi_sim+eng, one frame every 2 s", ""]
for i, name in enumerate(sorted(os.listdir("frames"))):
    t0 = 2.0 * i
    out.append("## t=%ds (%s)" % (t0, name))
    ocr = open(os.path.join("ocr", name[:-4] + ".txt"), encoding="utf-8", errors="replace").read()
    lines = [x.strip() for x in ocr.splitlines() if x.strip()]
    out.append("on screen (OCR): " + (" / ".join(lines) if lines else "(no text)"))
    said = [s[2] for s in segs if s[0] < t0 + 2 and s[1] > t0]
    out.append("spoken (ASR): " + (" ".join(said) if said else "(none)"))
    out.append("")

with open("brief.part.md", "w", encoding="utf-8") as f:
    f.write("\n".join(out))
os.replace("brief.part.md", "brief.md")
