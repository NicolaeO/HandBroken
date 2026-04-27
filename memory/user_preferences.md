---
name: User preferences
description: Encoding quality, audio, subtitle, and workflow preferences for this project
type: user
originSessionId: b401d7e5-676a-45cf-ad0d-e0b86509630f
---
## Quality
- No visible quality loss — priority over file size.
- For SD/sub-720p content: accept slightly larger output rather than risk quality loss.
- User has tried various QP settings in the past and gotten either bad quality or size increases; let the optimizer decide — don't ask the user to pick QP values.

## Audio — Option B (passthrough lossy, convert lossless)
- **Copy:** AC3, EAC3, AAC, MP3, Opus, Vorbis, DTS lossy core
- **Convert → EAC3:** TrueHD, DTS-MA, DTS-HD HRA, FLAC, PCM → 640k (≥6ch) / 192k (stereo)
- Keep ALL audio tracks (multiple languages, commentary, etc.)

## Subtitles
- Keep all subtitle tracks as-is (passthrough). No filtering by language.
- `mov_text` (MP4 text format) gets converted to `srt` for MKV compatibility.

## Containers & codec
- Output: always MKV (.mkv)
- Video: always x265 (HEVC)
- If file is already x265 but over size/bitrate limits → still re-encode

## 4K / HDR
- User has 4K/HDR files. Most are already well-encoded (under 10 GB).
- Re-encode 4K only if > 10 GB.
- Pass through HDR10 colour metadata (color_primaries, color_trc, colorspace).

## Hardware
- AMD GPU for encoding (hevc_amf). CPU (libx265) is ~15-40 fps; GPU is 100+ fps.
- User prefers speed from GPU even if quality is slightly below software x265.
- ffmpeg preferred over HandBrake (more control, same AMD AMF backend).

## Workflow preference
- Always keep `_ORIG_` original until user manually verifies the output looks good.
- Dry-run first is encouraged before committing a large batch.
