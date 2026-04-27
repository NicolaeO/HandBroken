---
name: Project overview
description: Architecture, file layout, and how to run the batch HEVC transcoder
type: project
originSessionId: b401d7e5-676a-45cf-ad0d-e0b86509630f
---
Batch video re-encoder at D:\filme\handbrake_tc. Uses ffmpeg (gyan.dev full build, in PATH) with AMD AMF hardware encoder to transcode a large media library to x265/MKV.

**Why:** library has mixed codecs (x264, x265, AVI, etc.) at various sizes; goal is to reduce storage while keeping transparent quality.

## Files

| File | Role |
|---|---|
| scanner.py | VideoScanner class — ffprobe each file → metadata list → JSON |
| optimizer.py | SettingsOptimizer class — metadata dict → ffmpeg settings dict |
| transcoder.py | Transcoder class — ffmpeg settings → runs encode → renames files |
| run.py | CLI entry point: `scan` / `encode` / `run` subcommands |

## How to run

```bash
python run.py run "K:/Media/TV Series/Ozark" --dry-run   # preview
python run.py run "K:/Media/TV Series/Ozark"             # encode
python run.py scan "K:/Media/TV Series" --out scan.json  # scan only
python run.py encode scan.json                           # encode from saved JSON
```

Logs → transcode.log + stdout.

## File rename flow (transcode.py)

1. Encode → `_TEMP_<stem>.mkv` (same folder as source)
2. Rename original → `_ORIG_<original_filename>` (keeps original extension)
3. Rename temp → `<stem>.mkv`
4. Size guard: if output > 110% of input, discard temp, keep original untouched

Skips files already prefixed `_ORIG_` or `_TEMP_`.

**How to apply:** when modifying any of these files, read them first — they are lean and self-contained. No external pip packages needed (Python 3.10+).
