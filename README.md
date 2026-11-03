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

## Repository layout

```
Shuukura_Vertin_IndexTTS/
├── README.md
├── .gitignore                     # ignores index-tts/, audiobook/, the EPUB
├── example/
│   ├── README.md                  # sample audio + how it was produced
│   ├── vertin_ref.py              # single source of truth: reference audio + test text
│   ├── text_prep.py               # chapter cleaning (metadata, notes, markers, quotes)
│   ├── segmentation.py            # reading-oriented sentence/phrase splitting + pauses
│   ├── audio_clean.py             # de-click + spectral-gate denoise (post-processing)
│   ├── tts_book.py                # EPUB -> one audio file per N chapters
│   ├── tts_read.py                # plain text -> audio, per-sentence with pauses
│   ├── texts/                     # short EN/ZH test scripts
│   ├── ref_vertin_7s.wav          # reference audio used for cloning
│   ├── ref_vertin_20s.wav         # longer reference from the same source
│   ├── 01…04_*.wav                # short samples (EN/ZH, single sentence / paragraph)
│   └── book_demo_ch01-02.flac     # two-chapter demo of the audiobook pipeline
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

### EPUB → one audio file per 20 chapters

```bash
cd ~/Documents/GitHub/Shuukura_Vertin_IndexTTS
PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True \
index-tts/.venv/bin/python example/tts_book.py \
  --epub "buying-a-classmate-once-a-week/*.epub" \
  --out-dir audiobook --per-file 20 --duration-factor 0.85 --device cuda:0
```

* Writes `audiobook/0001-0020.wav`, `0021-0040.wav`, … with 1.0 s of silence between chapters.
* Existing outputs are skipped, so an interrupted run resumes by re-running the same command.
* `--start 1 --end 2` renders a short demo; `--duration-factor 0.85` speeds speech up 15 %
  (valid range 0.5–2.0, `>1` is slower).

### Plain text with explicit pauses

```bash
index-tts/.venv/bin/python example/tts_read.py \
  --text-file example/texts/read_zh.txt --lang zh \
  --out example/04_indextts_read_zh.wav --device cuda:0
```

## Text preprocessing for reading aloud

`example/text_prep.py` keeps only what should be spoken:

* drops the table-of-contents file (it masquerades as `chapter_001.xhtml`),
  pure `Episode N` marker lines, navigation words, translator disclaimers
  (`禁止转载`, `仅供日语学习`, `侵删` …), URLs, `[图片]` placeholders and `译注` lines;
* extracts the chapter title (the short first line without sentence-final punctuation)
  and prepends a spoken `第N话。标题。` header;
* repairs the translator's broken quote pairing (many `“` are used as closing quotes,
  counts reach 41 vs 23) and collapses `。”。` to `。”`.

## Segmentation for natural pacing

`example/segmentation.py` splits by punctuation only — EPUB `<p>` boundaries are one sentence
each and would otherwise produce 500+ units per chapter with a 1 s pause after every line:

1. split at sentence-final punctuation (。！？…!?);
2. greedily merge neighbouring sentences up to `--unit-chars` (default 55) so one inference
   call covers 1–3 sentences — fewer seams, less overhead;
3. split over-long sentences at clause punctuation (，、；：) and hard-cut only when a sentence
   has no clause punctuation at all;
4. merge fragments shorter than 12 characters back into a neighbour;
5. never split inside quotes/brackets (「」『』“”‘’（）).

Pauses: 0.35 s after a sentence, 0.18 s after a clause, 1.0 s between chapters.

## Audio post-processing

The audible "impurity" turned out not to be a noise floor (−88 dB or lower) but **single-sample
jumps at segment seams** — IndexTTS inserts silence between segments and the joins click.
`example/audio_clean.py` runs on the final waveform:

| Step | Effect |
|---|---|
| high-pass 60 Hz | removes sub-bass rumble (0.7 % of total energy) |
| pop removal: zero a 1.5 ms core where the local slope exceeds 8× the ±10 ms median, with 0.7 ms cosine ramps | 13 020 spikes in 10 min → short transients drop, RMS −0.15 dB only |
| seam de-click: 3 ms splice across remaining \|Δsample\| > 0.5 | step discontinuities → 0 |
| `--pitch -1.5` (optional) | lowers pitch for a more matronly ("御姐") tone |

**Spectral-gate denoising is off by default.** `noisereduce` treated the voice itself as
noise: RMS fell from −21.3 dB to −25.3 dB and the result sounded hollow. The silence floor is
already ≈ −93 dB, so there is nothing to denoise. Pass `--denoise 0.3` only for genuinely noisy
material.

Everything runs on the CPU and costs no VRAM. `tts_book.py` and `tts_read.py` apply it automatically.

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

Measured end-to-end on `--duration-factor 0.85`, demo = chapters 1–2
(4,176 cleaned characters → 10.1 min of audio, 27 MB, 5.1 min wall, RTF 0.53):

| Scope | Audio | Wall time | Disk |
|---|---|---|---|
| 1 chapter (avg 2.8 k chars) | ~7 min | ~3.5 min | ~18 MB |
| 20 chapters (49 k chars) | ~2.0 h | ~1.05 h | ~320 MB |
| Whole book, 427 readable chapters (1.21 M chars) | ~49 h | ~26 h | ~7.7 GB |

Output is 22.05 kHz mono 16-bit, ~158 MB per hour (~2.7 MB per minute).

Where the time actually goes, per 8 s of audio in one call: GPT autoregressive decoding
1.98 s (48 %), flow-matching CFM 1.62 s (39 %), BigVGAN vocoder 0.42 s (10 %), the rest is
call overhead. The GPT is sequential by construction (25 semantic tokens per second of
audio), so batching does not apply; the only large knob left is `INDEXTTS_DIFFUSION_STEPS`.

## Known caveats

* The reference transcript was produced by Whisper; the word `tempests` in
  “the tempests blocked every signal I sent for help” came out as `temp…` in three different
  models and is inferred from context. IndexTTS does not consume this transcript, so it does
  not affect the audiobooks.
* The output is 22.05 kHz. Upsampling adds no detail; if a player handles 22.05 kHz badly,
  resample once with a good resampler (`soxr`) rather than in the player.
