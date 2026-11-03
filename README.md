# Shuukura_Vertin_IndexTTS

Zero-shot voice cloning of **Vertin** (*Reverse: 1999*) with **IndexTTS-2.5**, used to turn
text and EPUB books into audiobooks. The name comes from the source novel's Japanese title,
『週に一度クラスメイトを買う話』.

## Why IndexTTS

GPT-SoVITS (both the v1 and v4 Vertin checkpoints) was wired up first and worked —
v1 at 32 kHz, v4 at 48 kHz, weights loading cleanly. After an A/B listen on identical
reference audio and text, **IndexTTS-2.5 sounded clearly better**, so it is the only engine
kept here. The GPT-SoVITS checkout, its virtualenv, base models and weights (~13.4 GB) were
deleted to reclaim disk; links to re-obtain them are kept below.

## Audition before continuing the book

Both files use the same IndexTTS generation and the original `ref_vertin_7s.wav` reference:

- [A: original output, no pitch shift](example/00_audition_A_original.wav)
- [B: same output with gentle smoothing](example/00_audition_B_smoothed.wav)

The [audition transcript](example/texts/audition_zh.txt) uses a comma in place of the
original dash to prevent the text normalizer from reading it as “减减”.

The older `00_audition_ch01.wav` used pitch shifting and aggressive processing; it is not
the reference for this comparison. New audiobook outputs use the B smoothing settings.

[Listen to chapters 01–02 with B smoothing](example/book_demo_ch01-02_B_smoothed.flac).

## Repository layout

```
Shuukura_Vertin_IndexTTS/
├── README.md
├── .gitignore                     # ignores index-tts/, audiobook/, the EPUB
├── bin/vertin-read                # repeatable, resume-safe audiobook launcher
├── example/
│   ├── README.md                  # sample audio + how it was produced
│   ├── vertin_ref.py              # single source of truth: reference audio + test text
│   ├── text_prep.py               # chapter cleaning (metadata, notes, markers, quotes)
│   ├── segmentation.py            # reading-oriented sentence/phrase splitting + pauses
│   ├── audio_clean.py             # optional FFmpeg de-click + mild treble reduction
│   ├── tts_book.py                # EPUB -> one audio file per N chapters
│   ├── tts_read.py                # plain text -> audio, per-sentence with pauses
│   ├── texts/                     # short EN/ZH test scripts
│   ├── ref_vertin_7s.wav          # reference audio used for cloning
│   ├── ref_vertin_20s.wav         # longer reference from the same source
│   ├── 00_audition_A/B_*.wav      # identical speech: raw vs. smoothed comparison
│   ├── 01…04_*.wav                # short samples (EN/ZH, single sentence / paragraph)
│   ├── book_demo_ch01-02.flac     # older two-chapter demo
│   └── book_demo_ch01-02_B_smoothed.flac  # chapters 01–02 with B smoothing
├── index-tts/                     # NOT tracked: upstream repo + .venv + checkpoints
└── buying-a-classmate-once-a-week/  # NOT tracked: source EPUB
```

## Sources

| Item | Source |
|---|---|
| **Reference voice** | [BV1w64y1j7HT](https://www.bilibili.com/video/BV1w64y1j7HT/) — Vertin solo voice cut, chapter 5. Used `343.86–350.71 s` → `example/ref_vertin_7s.wav` |
| GPT-SoVITS checkpoints (removed) | [BV1RN3gezEFQ](https://www.bilibili.com/video/BV1RN3gezEFQ/) — Baidu Netdisk link in the description |
| Audiobook text | 『一周一次买下同班同学的那些事』 by 羽田宇佐, fan translation EPUB, 433 chapters / 1.30 M characters |
| IndexTTS-2.5 | [IndexTeam/IndexTTS-2.5](https://huggingface.co/IndexTeam/IndexTTS-2.5), code: [index-tts/index-tts](https://github.com/index-tts/index-tts) |

## Environment

```bash
cd index-tts
uv sync --python 3.10            # do NOT add --all-extras: it pulls deepspeed / flash-attn source builds
uvx --with socksio --from huggingface_hub hf download IndexTeam/IndexTTS-2.5 --local-dir checkpoints
```

* This machine routes through a SOCKS proxy; `hf` uses `httpx2`, so `--with socksio` is required.
* First inference downloads w2v-bert-2.0 / MaskGCT codec / CAMPPlus / BigVGAN into `checkpoints/hf_cache/`.
* **VRAM**: ~5.3 GB peak while loading, ~5.7 GB while inferring. On an 8 GB card, close other
  GPU users first (a browser plus an editor hold ~0.8 GB and cause `CUBLAS_STATUS_ALLOC_FAILED`).
  Falling back to `--device cpu` works but RTF drops from ~0.5 to ~9.

## Usage

### Start or resume the audiobook

On this machine the launcher is registered as `vertin-read`. In a new checkout, make it
available on your PATH once:

```bash
mkdir -p ~/.local/bin
ln -s "$PWD/bin/vertin-read" ~/.local/bin/vertin-read
# Ensure ~/.local/bin is on PATH.
```

Then start or resume from a terminal:

```bash
vertin-read
```

The launcher uses the original reference, normal speed, no pitch shift, the B smoothing
filter and FLAC output. Files are saved under `audiobook/` as `0001-0020.flac`,
`0021-0040.flac`, and so on. Stop with Ctrl-C; after reboot run the same command.
Completed chapters of the unfinished group are restored from `audiobook/.checkpoints/`;
only the chapter interrupted mid-generation must be redone. Each checkpoint and output
has a checksum manifest and is committed atomically; keep the `.manifest.json` files with
their audio. A group’s chapter checkpoints are removed after its final file is safely
written. Locks prevent concurrent jobs from sharing a checkpoint or output directory.

The launcher expects exactly one EPUB in the source directory. Changing the EPUB,
reference, model, text processing or generation settings starts a separate checkpoint
set. Existing final files are skipped only when their settings and checksum match;
otherwise the command stops without overwriting them. Use a separate output directory
when intentionally generating a different version.

`./bin/vertin-read` also works without installing the symlink. Advanced options can be
passed through to `tts_book.py`; use `vertin-read --help` to see them.

### Plain text with explicit pauses

```bash
index-tts/.venv/bin/python example/tts_read.py \
  --text-file example/texts/audition_zh.txt --lang zh \
  --out example/new_audition.wav --device cuda:0
```

## Text preprocessing for reading aloud

`example/text_prep.py` keeps only what should be spoken:

* drops the table-of-contents file (it masquerades as `chapter_001.xhtml`),
  pure `Episode N` marker lines, navigation words, translator disclaimers
  (`禁止转载`, `仅供日语学习`, `侵删` …), URLs, `[图片]` placeholders and `译注` lines;
* extracts the chapter title (the short first line without sentence-final punctuation)
  and prepends a spoken `第N话。标题。` header;
* repairs the translator's broken quote pairing and collapses `。”。` to `。”`;
* replaces long dashes with a pause, so the model does not read them as “减减”.

## Segmentation for natural pacing

`example/segmentation.py` splits by punctuation only — EPUB `<p>` boundaries are one sentence
each and would otherwise produce 500+ units per chapter with a 1 s pause after every line:

1. split at sentence-final punctuation (。！？…!?);
2. greedily merge neighbouring sentences up to `--unit-chars` (book default 70) so one inference
   call covers 1–3 sentences — fewer seams, less overhead;
3. split over-long sentences at clause punctuation (，、；：);
4. merge fragments shorter than 12 characters back into a neighbour;
5. avoid splitting inside quotes/brackets where possible; for over-long passages, prefer
   punctuation even inside quotes before falling back to a hard cut.

Pauses: 0.35 s after a sentence, 0.18 s after a clause, 1.0 s between chapters.

## Audio post-processing

By default, `tts_book.py` and `tts_read.py` retain the generated waveform without pitch
shifting, spectral gating, or zeroing detected segments. Sentence and chapter pauses are
still added as requested.

The optional `--smooth` flag applies [FFmpeg's `adeclick`](https://ffmpeg.org/ffmpeg-filters.html#adeclick)
with a conservative threshold of 10 and overlap-save, followed by a high-shelf cut of
2 dB at 6.5 kHz. The filter operates on the CPU and requires FFmpeg. It may also soften
speech sibilants; it cannot reliably remove artifacts produced by the model's vocoder.
FLAC output is 16-bit, matching the source generation and avoiding unnecessary 24-bit files.
Compare the two auditions before using it on a book.

To make a separate smoothed copy of an existing file:

```bash
index-tts/.venv/bin/python example/audio_clean.py path/to/audio.wav
# Writes path/to/audio_smooth.wav; the original is unchanged.
```

## Measured performance (RTX 5060, 8 GB)

Configuration matters more than raw hardware. Measured on the same 6 reading units
(22 k chars/s setting, `--duration-factor 0.85`):

| Configuration | RTF | Peak VRAM |
|---|---|---|
| low-VRAM text re-splitting on, 25 diffusion steps (default) | 0.680 | 5.88 GB |
| re-splitting off (our units are already <= unit-chars), 25 steps | 0.519 | 5.92 GB |
| re-splitting off, 12 diffusion steps (`INDEXTTS_DIFFUSION_STEPS=12`) | 0.401 | 5.94 GB |

The scripts disable the 40-character re-splitting automatically: chunking an already-correct
reading unit breaks the pacing and adds calls. Diffusion steps stay at 25 for quality;
`INDEXTTS_DIFFUSION_STEPS` is available if you want the extra ~23 %.

Running two workers in parallel is **not** possible on this card: peak is ~5.9 GB of 7.58 GB,
so a second instance (5.3 GB) does not fit, and GPU utilisation already reaches 100 % with one
worker — the headroom is VRAM, not compute.

The normal-speed B demo produced 11.71 minutes for chapters 01–02 in roughly 6 minutes of
inference (RTF ~0.5). Extrapolations are approximate:

| Scope | Audio | Inference | 16-bit FLAC |
|---|---|---|---|
| Chapters 01–02, measured | 11.71 min | ~6 min | 20.0 MB |
| First 20 chapters, estimated | ~2.4 h | ~1.2 h | ~250 MB |
| 427 readable chapters, estimated | ~60 h | ~30 h | ~6.1 GB |

Actual runtime depends on chapter length, hardware load, restarts and post-processing. Temporary
checkpoints and assembly require additional space; uncompressed WAV takes ~158 MB per hour.

Where the time actually goes, per 8 s of audio in one call: GPT autoregressive decoding
1.98 s (48 %), flow-matching CFM 1.62 s (39 %), BigVGAN vocoder 0.42 s (10 %), the rest is
call overhead. The GPT is sequential by construction (25 semantic tokens per second of
audio), so batching does not apply; the only large knob left is `INDEXTTS_DIFFUSION_STEPS`.

## Known caveats

* The EPUB contains no story text for chapters 142, 169, 229, 270, 320 and 381; these are
  password/placeholder pages and are skipped. A complete audiobook needs those texts.
* One observed startup crashed in NVIDIA `libcuda` while loading a kernel; the cause was not
  established. Restart `vertin-read` if it exits; completed chapter checkpoints are retained.

* The reference transcript was produced by Whisper; the word `tempests` in
  “the tempests blocked every signal I sent for help” came out as `temp…` in three different
  models and is inferred from context. IndexTTS does not consume this transcript, so it does
  not affect the audiobooks.
* The output is 22.05 kHz. Upsampling adds no detail; if a player handles 22.05 kHz badly,
  resample once with a good resampler (`soxr`) rather than in the player.
