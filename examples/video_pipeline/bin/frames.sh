#!/bin/sh
# Stage 4: one frame every 2 seconds (frame f_NNN is nominally at t = 2*(NNN-1) s).
set -eu
rm -rf frames frames.part
mkdir frames.part
ffmpeg -nostdin -v error -y -i src.mp4 -vf fps=1/2 -fflags +bitexact -flags:v +bitexact frames.part/f_%03d.png
mv frames.part frames
