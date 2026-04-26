# HandBroken

Batch video transcoder that converts your media library to AV1 using ffmpeg. Supports AMD, NVIDIA, and CPU encoding. Born from the frustration that HandBrake couldn't quite cut it.

## Features

- **AMD / NVIDIA / CPU** — switchable encoder via `config.json`
- **AV1 output** — better compression than H.264/H.265 at the same quality
- **Auto-crop** — detects and removes black bars (letterboxing) during scan
- **Smart audio** — passthrough lossy tracks (AC3, EAC3, AAC, DTS), convert lossless (TrueHD, DTS-MA, FLAC, PCM) → EAC3
- **Subtitle passthrough** — all tracks kept; `mov_text` converted to SRT for MKV compatibility
- **Color accuracy** — writes color metadata into the AV1 bitstream so hardware decoders render correctly
- **Size guard** — never replaces the original with a larger file
- **Safe** — originals moved to `.originals/`, fully revertable
- **Resume-aware** — skips already-encoded files when restarting an interrupted batch

## Requirements

| Dependency | Notes |
|---|---|
| Python 3.10+ | |
| ffmpeg + ffprobe | [gyan.dev full build](https://www.gyan.dev/ffmpeg/builds/) recommended — includes AMF and libsvtav1 |
| **AMD encoder** | Adrenalin drivers 23.x+ · any RDNA GPU |
| **NVIDIA encoder** | Drivers 522+ · RTX 3000+ (Ada Lovelace for AV1) |
| **CPU encoder** | ffmpeg full build with `libsvtav1` (no extra drivers needed) |

## Quick start

```bash
# 1. Clone
git clone https://github.com/NicolaeO/HandBroken
cd handbroken

# 2. Configure your encoder (edit config.json)
#    "encoder": "amd" | "nvidia" | "cpu"

# 3. Verify everything is set up correctly
make check          # Linux / macOS / Git Bash on Windows
python check_env.py # Windows without make

# 4. Scan your library
make scan FOLDER="K:/Media/Folder"

# 5. Review the scan, then encode
make encode
```

## Configuration

Edit `config.json` before running:

```json
{
  "encoder":      "amd",     // "amd" | "nvidia" | "cpu"
  "ffmpeg_path":  "ffmpeg",  // full path if not in PATH
  "ffprobe_path": "ffprobe"
}
```

### Encoder quality defaults

| Encoder | Mode | Transparent | Efficient (HEVC re-encode) |
|---|---|---|---|
| AMD `av1_amf` | QVBR (higher = better) | 40 | 33 |
| NVIDIA `av1_nvenc` | CQ (lower = better) | 26 | 33 |
| CPU `libsvtav1` | CRF (lower = better) | 30 | 38 |

To adjust quality, edit the values in `encoders.py` (`quality_transparent` / `quality_efficient`).

## Commands

```bash
# Scan a folder recursively — writes results/<folder>.json
python run.py scan "K:/Media/TV Series/Ozark/Season 1"

# Pick a scan file and encode
python run.py encode

# One step: scan + encode
python run.py run "K:/Media/TV Series/Ozark"

# Verify your encodes look good, then permanently delete originals
python run.py clean

# Something went wrong — restore originals and delete encodes
python run.py revert
```

### Flags

| Flag | Commands | Description |
|---|---|---|
| `--dry-run` | encode, run, clean, revert | Show what would happen, do nothing |
| `--clean` | encode, run | Delete `.originals/` automatically after encoding |
| `--keep-larger` | encode, run | Keep encoded file even if it's larger than the source |

### Makefile shortcuts (Git Bash / Linux / macOS)

```bash
make check
make scan   FOLDER="K:/Media/TV Series/Ozark"
make encode
make run    FOLDER="K:/Media/TV Series/Ozark" KEEP_LARGER=1
make clean
make revert
```

## Quality calibration (preview)

Before encoding your library, run a preview to find the quality level that looks right to you:

```bash
# Auto-picks a start point 30% into the file
python run.py preview "K:/Media/Movie.mkv"

# Or specify a start time and clip length
python run.py preview "K:/Media/Movie.mkv" --start 120 --duration 15

# Makefile shortcut
make preview FILE="K:/Media/Movie.mkv"
make preview FILE="K:/Media/Movie.mkv" START=120 DURATION=15
```

This encodes a short clip at every quality level in the encoder's `preview_qualities` range, plus a stream-copied reference (no re-encode). Output goes to `.preview/<filename>/`:

```
.preview/Movie/
  00_source.mkv          ← original, untouched
  01_amd_qvbr30.mkv
  02_amd_qvbr35.mkv
  03_amd_qvbr40.mkv      ← efficient default
  04_amd_qvbr45.mkv      ← transparent default
  05_amd_qvbr50.mkv
```

> **Note:** `.preview` is a hidden folder (the leading dot hides it by default).
> - **Windows** — Explorer → View → Show → Hidden items
> - **macOS** — Finder → Cmd+Shift+. to toggle hidden files
> - **Linux** — `ls -a` or your file manager's "show hidden" option

Open the clips side-by-side in MPV or another player. Once you've picked your preferred level, update `encoders.py`:

```python
"quality_transparent": 45,   # for normal sources (H.264, MPEG-2, etc.)
"quality_efficient":    33,   # for HEVC sources that are already small
```

## How it works

```
scan     VideoScanner     ffprobe each file → metadata + crop detection → results/<name>.json
optimize SettingsOptimizer metadata dict → ffmpeg settings dict (encoder, audio, subs)
encode   Transcoder        ffmpeg settings → encode → safe file replacement
```

### Scan decisions

- **Skip** — HEVC or AV1 files already within size/bitrate limits for their tier
- **Transcode** — everything else

| Tier | Size limit | Bitrate limit |
|---|---|---|
| 4K (≥2160p) | 10 GB | 12 Mbps |
| 1080p | 6 GB | 3,500 kbps |
| 720p | 3 GB | 2,000 kbps |
| SD | 1.5 GB | 1,200 kbps |

### File handling

1. Encodes to `_TEMP_<stem>.mkv` in the same folder
2. If output > 110% of input size → discard temp, keep original (unless `--keep-larger`)
3. On success → original moves to `.originals/<original_filename>`, temp renamed to `<stem>.mkv`

### Audio

| Source codec | Action |
|---|---|
| AC3, EAC3, AAC, MP3, Opus, Vorbis, DTS (core) | Passthrough |
| TrueHD, DTS-MA, DTS-HD HRA, FLAC, PCM | Convert → EAC3 (640k ≥6ch / 192k stereo) |

## Player recommendation

[MPV](https://mpv.io) or [MPV.net](https://github.com/mpvnet-player/mpv.net) — handles AV1 color metadata correctly. PotPlayer can be configured to use software decode for AV1 (Preferences → Filter/Decoder → Video Decoder → AV1 → Software) to avoid hardware decoder color issues.

## Project structure

| File | Role |
|---|---|
| `scanner.py` | `VideoScanner` — ffprobe wrapper, crop detection, transcode decision |
| `optimizer.py` | `SettingsOptimizer` — produces ffmpeg settings dict |
| `transcoder.py` | `Transcoder` — builds and runs ffmpeg command, manages file replacement |
| `encoders.py` | Encoder profiles (AMD / NVIDIA / CPU) and ffmpeg flag builder |
| `config.py` | Config loader |
| `config.json` | User config — encoder choice and paths |
| `run.py` | CLI entry point |
| `check_env.py` | Dependency and encoder availability checker |
| `one_off.py` | Utility scripts (e.g. strip `_ORIG_` prefix from legacy files) |
