#!/bin/sh
# Stage 2: 16 kHz mono wav (what Whisper wants). Bit-exact flags so the same video gives the same bytes.
set -eu
rm -f audio.part.wav audio.wav
ffmpeg -nostdin -v error -y -i src.mp4 -vn -ar 16000 -ac 1 -c:a pcm_s16le -map_metadata -1 \
  -fflags +bitexact -flags:a +bitexact -f wav audio.part.wav
mv audio.part.wav audio.wav
