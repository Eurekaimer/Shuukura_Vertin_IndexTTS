# example: reference audio, samples and scripts

Everything here is generated with **IndexTTS-2.5** and `ref_vertin_7s.wav`.
Full audiobooks go to `../audiobook/` (not tracked); only the two-chapter demo is kept here.

## Files

| File | Duration | Sample rate | What it is |
|---|---|---|---|
| `ref_vertin_7s.wav` | 7.10 s | 32 kHz | **reference audio** (343.86–350.71 s of BV1w64y1j7HT) |
| `ref_vertin_20s.wav` | 20.0 s | 32 kHz | longer reference from the same source |
| `01_indextts_en.wav` | 5.22 s | 22.05 kHz | one English sentence |
| `02_indextts_zh.wav` | 4.95 s | 22.05 kHz | one Chinese sentence |
| `03_indextts_read_en.wav` | 22.71 s | 22.05 kHz | paragraph, per-sentence synthesis with pauses |
| `04_indextts_read_zh.wav` | 20.44 s | 22.05 kHz | same in Chinese |
| `book_demo_ch01-02.flac` | 10.1 min | 22.05 kHz | **audiobook demo: chapters 1–2** (FLAC, 14 MB) |

## Scripts

| Script | Purpose |
|---|---|
| `tts_book.py` | EPUB → one audio file per N chapters, resumable |
| `tts_read.py` | plain text → audio, per-sentence with explicit pauses |
| `text_prep.py` | chapter cleaning: metadata, translator notes, duplicated titles, password pages |
| `segmentation.py` | punctuation-only reading units with pause lengths |
| `audio_clean.py` | de-click + spectral-gate denoise |
| `vertin_ref.py` | single source of truth for reference audio and test text |

```bash
cd ~/Documents/GitHub/Shuukura_Vertin_IndexTTS

# two-chapter demo (what book_demo_ch01-02.flac was made from)
PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True \
index-tts/.venv/bin/python example/tts_book.py \
  --epub "buying-a-classmate-once-a-week/*.epub" \
  --out-dir audiobook --per-file 20 --start 1 --end 2 \
  --duration-factor 0.85 --device cuda:0

# the whole book, 20 chapters per file
PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True \
index-tts/.venv/bin/python example/tts_book.py \
  --epub "buying-a-classmate-once-a-week/*.epub" \
  --out-dir audiobook --per-file 20 --duration-factor 0.85 --device cuda:0
```

## Notes

* The eight-digit prefix in `audiobook/0001-0020.wav` is the chapter range, so files sort in reading order.
* Chapters 169, 229, 270, 320 and 381 in this EPUB are password pages with no body text; the script skips them.
* The reference transcript was produced by Whisper; `tempests` is inferred (a `temp…` truncation in all
  three models tried). IndexTTS does not read this transcript, so it does not affect the audio.
