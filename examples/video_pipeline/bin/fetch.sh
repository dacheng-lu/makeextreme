#!/bin/sh
# Stage 1: fetch the source video. input.url holds either file:///abs/path.mp4 (copied) or a URL (yt-dlp).
set -eu
url=$(cat input.url)
rm -f src.mp4 src.part.mp4
case "$url" in
  file://*) cp "${url#file://}" src.part.mp4 ;;
  *) yt-dlp -q --no-playlist -f 'bv*+ba/b' --merge-output-format mp4 -o src.part.mp4 "$url" ;;
esac
mv src.part.mp4 src.mp4
