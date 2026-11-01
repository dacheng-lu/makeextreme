"""Stage 3: transcribe audio.wav with faster-whisper, cached by the audio's hash.

Whisper is NOT bit-deterministic on the machine this was built on (measured: the same 38 s clip gave two
different transcripts, roughly 1 run in 6-10, with default threads, with the language fixed and with one
thread; the cause was not investigated). A transcript is therefore stored under the sha256 of its audio, and
the same audio always gets the same transcript. Offline on purpose: a missing model fails, it is never
downloaded here.
"""
import hashlib
import os
import shutil
import sys

wav, out = sys.argv[1], sys.argv[2]
model_name = os.environ.get("ASR_MODEL", "small")
key = hashlib.sha256(open(wav, "rb").read()).hexdigest()[:32]
cache = os.path.join(os.environ.get("MAKEEXTREME_CACHE", os.path.expanduser("~/.cache/makeextreme")), "asr")
os.makedirs(cache, exist_ok=True)
hit = os.path.join(cache, "%s.%s.txt" % (key, model_name))

if os.path.exists(hit):
    print("asr: cache hit", file=sys.stderr)
else:
    os.environ["HF_HUB_OFFLINE"] = "1"
    from faster_whisper import WhisperModel
    model = WhisperModel(model_name, device="cpu", compute_type="int8")
    segments, _info = model.transcribe(wav, beam_size=5, temperature=0.0, condition_on_previous_text=False)
    text = "".join("[%.2f-%.2f] %s\n" % (s.start, s.end, s.text.strip()) for s in segments)
    tmp = "%s.tmp%d" % (hit, os.getpid())
    with open(tmp, "w") as f:
        f.write(text)
    os.replace(tmp, hit)
    print("asr: transcribed (cache miss)", file=sys.stderr)

shutil.copyfile(hit, out + ".part")
os.replace(out + ".part", out)
