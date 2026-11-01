#!/bin/sh
# Stage 5: OCR every frame, one file per frame. Single OpenMP thread so the result does not depend on scheduling.
# Works in ocr.part and renames at the end: a kill leaves a partial ocr.part, never a partial ocr.
set -eu
export OMP_THREAD_LIMIT=1
export TESSDATA_PREFIX="${TESSDATA_PREFIX:-$HOME/.local/share/tessdata}"
rm -rf ocr ocr.part
mkdir ocr.part
for f in frames/*.png; do
  b=$(basename "$f" .png)
  tesseract "$f" "ocr.part/$b" -l chi_sim+eng --psm 6 >/dev/null 2>&1
done
mv ocr.part ocr
