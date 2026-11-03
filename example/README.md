# example: reference audio, samples and scripts

Everything here is generated with **IndexTTS-2.5** and `ref_vertin_7s.wav`.
Full audiobooks and resumable chapter checkpoints go to `../audiobook/` (not tracked).

## Files

| File | Duration | Sample rate | What it is |
|---|---|---|---|
| `ref_vertin_7s.wav` | 7.10 s | 32 kHz | **reference audio** (343.86–350.71 s of BV1w64y1j7HT) |
| `ref_vertin_20s.wav` | 20.0 s | 32 kHz | longer reference from the same source |
| [00_audition_A_original.wav](00_audition_A_original.wav) | 20.56 s | 22.05 kHz | freshly generated speech without pitch shifting or smoothing |
| [00_audition_B_smoothed.wav](00_audition_B_smoothed.wav) | 20.56 s | 22.05 kHz | the same generation, with optional de-click and mild treble reduction |
| `01_indextts_en.wav` | 5.22 s | 22.05 kHz | one English sentence |
| `02_indextts_zh.wav` | 4.95 s | 22.05 kHz | one Chinese sentence |
| `03_indextts_read_en.wav` | 22.71 s | 22.05 kHz | paragraph, per-sentence synthesis with pauses |
| `04_indextts_read_zh.wav` | 20.44 s | 22.05 kHz | same in Chinese |
| `book_demo_ch01-02.flac` | 10.1 min | 22.05 kHz | **audiobook demo: chapters 1–2** (FLAC, 14 MB) |
| [book_demo_ch01-02_B_smoothed.flac](book_demo_ch01-02_B_smoothed.flac) | 11.71 min | 22.05 kHz | chapters 01–02, normal speed with B smoothing, 20.0 MB |

`00_audition_ch01.wav` is an older audition with pitch shifting and aggressive processing.
The older two-chapter demo predates the current smoothing change; use the B demo for the
current pipeline. The samples do not establish that the voice is free of audible artifacts.

## Scripts

| Script | Purpose |
|---|---|
| `tts_book.py` | EPUB → one audio file per N chapters, resumable |
| `tts_read.py` | plain text → audio, per-sentence with explicit pauses |
| `text_prep.py` | chapter cleaning: metadata, translator notes, duplicated titles, password pages |
| `segmentation.py` | punctuation-only reading units with pause lengths |
| `audio_clean.py` | optional FFmpeg de-click and gentle high-shelf cut |
| `vertin_ref.py` | single source of truth for reference audio and test text |

```bash
cd ~/Documents/GitHub/Shuukura_Vertin_IndexTTS

# two-chapter B demo; keep the completed chapter checkpoints for the full run
./bin/vertin-read --out-dir example --end 2 --keep-checkpoints
mv example/0001-0002.flac example/book_demo_ch01-02_B_smoothed.flac
mv example/0001-0002.flac.manifest.json example/book_demo_ch01-02_B_smoothed.flac.manifest.json

# the whole book, 20 chapters per file; repeat after stopping or rebooting
./bin/vertin-read
```

## Notes

* The chapter range in `audiobook/0001-0020.flac` keeps files in reading order.
* Chapters 142, 169, 229, 270, 320 and 381 contain only password/placeholder pages in this EPUB;
  there is no story text to synthesize, so the script skips them.
* The reference transcript was produced by Whisper; `tempests` is inferred (a `temp…` truncation in all
  three models tried). IndexTTS does not read this transcript, so it does not affect the audio.
