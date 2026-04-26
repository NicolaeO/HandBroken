# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this project does

Batch AV1 transcoder ("HandBroken") for a large media library. Scans folders recursively, decides which files need transcoding, and re-encodes them to AV1 using ffmpeg. Supports AMD AMF (`av1_amf`), NVIDIA NVENC (`av1_nvenc`), and CPU (`libsvtav1`) encoders selected via `config.json`. Originals are moved to `.originals/` and kept until verified.

## How to run

```bash
# Verify environment
python check_env.py          # or: make check

# Scan a folder (writes results/<name>.json)
python run.py scan "K:/Media/TV Series/Ozark"

# Pick a scan file and encode
python run.py encode

# One-step scan + encode
python run.py run "K:/Media/TV Series/Ozark"

# Quality calibration clips
python run.py preview "K:/Media/Movie.mkv"

# Dry-run
python run.py run "K:/Media/TV Series" --dry-run
```

Logs go to `{action}_{folder}_{YYYY-MM-DD_HH-MM-SS}.log` and stdout simultaneously.

## Architecture

```
scanner.py    VideoScanner      ffprobe each file → metadata + crop detection → results/<name>.json
optimizer.py  SettingsOptimizer per-file metadata dict → ffmpeg settings dict
transcoder.py Transcoder        ffmpeg settings dict → runs encode → safe file replacement
encoders.py   PROFILES + build_video_flags()  encoder-specific ffmpeg flags
config.py     load()            merges config.json defaults
preview.py    run_preview()     encodes short clips at every quality level for visual comparison
run.py                          CLI entry point (scan / encode / run / preview / clean / revert)
```

### scanner.py — VideoScanner

- Recursively finds video files, skips files prefixed with `_TEMP_`.
- Uses `ffprobe -print_format json -show_format -show_streams` to extract codec, bitrate, resolution, bit depth, HDR flags, audio/subtitle tracks.
- **Skip decision** — HEVC or AV1 files already within size/bitrate limits for their tier:

| Tier  | Size limit | Bitrate limit |
|-------|-----------|---------------|
| 4K    | 10 GB     | 12 Mbps       |
| 1080p | 6 GB      | 3,500 kbps    |
| 720p  | 3 GB      | 2,000 kbps    |
| SD    | 1.5 GB    | 1,200 kbps    |

- Crop detection: `cropdetect` filter on a 2-minute sample starting at 25% in; most common `crop=W:H:X:Y` value wins. Returns `None` if no actual crop needed.

### optimizer.py — SettingsOptimizer

- Reads encoder from `config.json` via `config.load()`; selects `enc.PROFILES[encoder]`
- Uses `quality_transparent` for normal sources (H.264, MPEG-2, etc.) and `quality_efficient` for HEVC/AV1 re-encodes
- `color_range` only set when source explicitly declares it or HDR — avoids full→limited range crush
- maxrate capped at source video bitrate to prevent output growing larger than source

**Audio:** passthrough lossy (AC3, EAC3, AAC, MP3, Opus, Vorbis, DTS core); convert lossless (TrueHD, DTS-MA, FLAC, PCM) → EAC3 (`640k` ≥6ch / `192k` stereo).

**Subtitles:** copy all; `mov_text` → `srt` for MKV compatibility.

### transcoder.py — Transcoder

1. Encodes to `_TEMP_<stem>.mkv` in source folder.
2. Video filter chain: optional `crop=W:H:X:Y`, then `setparams=colorspace=...:color_primaries=...:color_trc=...` (writes color metadata into AV1 bitstream OBU — required for hardware decoders).
3. **Size guard**: if output > 110% of input size → discard temp, keep original (bypass with `--keep-larger`).
4. On success: original moves to `.originals/<original_filename>`, temp renamed to `<stem>.mkv`.

### encoders.py

`PROFILES` dict contains per-encoder quality labels, defaults, and `preview_qualities` list.
`build_video_flags(encoder, vs)` returns the ffmpeg video encoder argument list including maxrate if set.

Key encoder notes:
- **AMD `av1_amf` QVBR**: scale is INVERTED vs CRF — **higher = better quality** (e.g., QVBR 45 transparent, QVBR 33 efficient)
- **NVIDIA `av1_nvenc` CQ**: lower = better (CQ 26 transparent, CQ 33 efficient)
- **CPU `libsvtav1` CRF**: lower = better (CRF 30 transparent, CRF 38 efficient)

## Configuration

`config.json` — encoder choice and ffmpeg paths:
```json
{"encoder": "amd", "ffmpeg_path": "ffmpeg", "ffprobe_path": "ffprobe"}
```

Quality defaults and preview ranges live in `encoders.py` → `PROFILES`.

## Dependencies

- **ffmpeg / ffprobe** in PATH — gyan.dev full build includes AMF and libsvtav1
- Python 3.10+ (uses `str | None` union type syntax)
- No pip packages required
