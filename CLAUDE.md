# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this project does

Batch HEVC re-encoder for a large media library. Scans folders recursively, decides which files need transcoding, and re-encodes them using ffmpeg with the AMD AMF hardware encoder (`hevc_amf`). Originals are kept with an `_ORIG_` prefix for verification.

## How to run

```bash
# Scan a folder (writes scan_results.json)
python run.py scan "K:/Media/TV Series/Ozark"

# Review scan_results.json, then encode
python run.py encode

# One-step scan + encode
python run.py run "K:/Media/TV Series/Ozark"

# Dry-run (shows plan, no encoding)
python run.py run "K:/Media/TV Series" --dry-run
```

Logs go to `transcode.log` and stdout simultaneously.

## Architecture

```
scanner.py    VideoScanner      ffprobe each file → list of metadata dicts → scan_results.json
optimizer.py  SettingsOptimizer per-file metadata dict → ffmpeg settings dict
transcoder.py Transcoder        ffmpeg settings dict → runs encode → renames files
run.py                          CLI entry point tying the three classes together
```

### scanner.py — VideoScanner

- Recursively finds video files, skips `_ORIG_` and `_TEMP_` prefixed files.
- Uses `ffprobe -print_format json -show_format -show_streams` to extract codec, bitrate, resolution, bit depth, HDR flags, audio/subtitle tracks.
- **Transcode decision** (for x265 files, skip unless over limit):

| Tier  | Size limit | Bitrate limit |
|-------|-----------|---------------|
| 4K    | 10 GB     | 40 Mbps       |
| 1080p | 8 GB      | 15 Mbps       |
| 720p  | 4 GB      | 8 Mbps        |
| SD    | 2 GB      | 4 Mbps        |

- Non-x265 files (x264, mpeg2, etc.) are always transcoded.

### optimizer.py — SettingsOptimizer

**Video:**
- Encoder: `hevc_amf` (AMD VCE), CQP mode, `-quality quality -preanalysis 1 -vbaq 1`
- QP for x264→x265: `20/22/24` (I/P/B) — transparent quality
- QP for x265→x265 re-encode: `22/24/26` — slightly more aggressive
- Profile `main10` if source is 10-bit or HDR; `main` (8-bit) otherwise
- HDR: passes `color_primaries`, `color_trc`, `colorspace` through to output

**Audio (Option B — passthrough lossy, convert lossless):**
- Copy: AC3, EAC3, AAC, MP3, Opus, Vorbis, DTS (lossy core)
- Convert → EAC3: TrueHD, DTS-MA, DTS-HD HRA, FLAC, PCM (`640k` for ≥6ch, `192k` for stereo)

**Subtitles:** copy all; `mov_text` (MP4 format, incompatible with MKV) converted to `srt`.

### transcoder.py — Transcoder

1. Encodes to `_TEMP_<stem>.mkv` in source folder.
2. **Size guard**: if output > 110% of input size, discards temp and keeps original untouched (handles already-optimal SD content).
3. On success: renames original to `_ORIG_<original_filename>`, renames temp to `<stem>.mkv`.

## File layout

| File | Role |
|------|------|
| `scanner.py` | `VideoScanner` class — ffprobe wrapper + decision logic |
| `optimizer.py` | `SettingsOptimizer` class — produces ffmpeg settings dict |
| `transcoder.py` | `Transcoder` class — builds and runs ffmpeg command |
| `run.py` | CLI: `scan` / `encode` / `run` subcommands |
| `Handbrake_Claude.json` | Legacy HandBrake preset (AMD VCE H.265 8-bit, QP 22) |
| `custom_handbrake.json` | Legacy HandBrake preset (AMD VCE H.265 10-bit, CQ 22) |
| `main.py` | Legacy HandBrake-based batch script (superseded by run.py) |

## Dependencies

- **ffmpeg / ffprobe** in PATH — gyan.dev full build includes AMD AMF support
- Python 3.10+ (uses `str | Path` union type syntax)
- No pip packages required
