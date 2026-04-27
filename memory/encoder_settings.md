---
name: Encoder settings
description: AMD AMF AV1 QVBR quality levels, ffmpeg flags, and transcode decision thresholds
type: project
---

## Encoder: av1_amf (AMD AV1 hardware, RX 7900 XT / RDNA 3)

Switched from hevc_amf to av1_amf. HEVC caused visible blocking in dark scenes;
AV1 with -aq_mode caq fixes this. Speed: ~120fps (vs ~400fps for HEVC) — acceptable trade-off.

```
-c:v av1_amf -usage high_quality -quality quality -rc qvbr -qvbr_quality_level <N>
-preanalysis 1 -aq_mode caq
```

**Note:** `-preanalysis` and `-vbaq` do NOT work with hevc_amf in CQP mode (encoder init fails).
Both work correctly with av1_amf. CQP mode was also tested on av1_amf and produced near-lossless
output (77 Mbps for 1080p) — do not use CQP. QVBR is the correct rate control mode.

### QVBR quality levels

Scale is **HIGHER = better quality** (opposite of CRF). Range 1–51.

| Scenario | qvbr_quality_level | Bitrate (dark 1080p scene) | Rationale |
|---|---|---|---|
| x264/other → AV1 | 40 | ~900 kbps | Transparent quality, confirmed in MPV |
| HEVC → AV1 re-encode | 33 | ~500 kbps | Reclaim space, still good quality |

Calibrated on Ozark S01E01 dark scenes (worst case). Normal content will have higher bitrates.

Scale reference (dark 1080p Ozark scene):
- Q40 → ~900 kbps, Q45 → ~1.3 Mbps, Q51 → ~2 Mbps

**How to apply:** adjust `_QVBR_TRANSPARENT` / `_QVBR_EFFICIENT` in `optimizer.py`.
Bump up by 3–5 if quality looks soft; down by 3–5 if files are too large.

### 10-bit / HDR
- AV1 AMF uses `-bitdepth 10` (not `-profile:v main10` like HEVC AMF)
- AV1 Main profile handles both 8-bit and 10-bit natively

### Color metadata
Use `-vf setparams=colorspace=...:color_primaries=...:color_trc=...:range=limited` PLUS
the output flags `-color_primaries -color_trc -colorspace -color_range`.

The `setparams` filter writes color info into the AV1 bitstream (sequence header OBU).
Hardware decoders (AMD, Intel) read from the bitstream, not the container — without
`setparams` they default to unspecified and render with wrong color (dark/blue shift).

Confirmed: PotPlayer hardware AV1 decode had color issues fixed by setparams. MPV
(software decode) always looked correct. Both look correct after the setparams fix.

- SDR defaults: bt709 / bt709 / bt709 / limited
- HDR defaults: bt2020 / smpte2084 / bt2020nc / limited

## Transcode decision thresholds

HEVC and AV1 files are skipped unless they exceed EITHER limit for their tier.
All other codecs (x264, xvid, etc.) are always transcoded.

| Tier | Size limit | Bitrate limit |
|---|---|---|
| 4K (≥2160p) | 10 GB | 12 Mbps |
| 1080p | 6 GB | 3,500 kbps |
| 720p | 3 GB | 2,000 kbps |
| SD (<720p) | 1.5 GB | 1,200 kbps |

**How to apply:** adjust `_SIZE_LIMIT_GB` / `_BITRATE_LIMIT_KBPS` dicts in `scanner.py`.

## Size guard

If encoded output > 110% of input size → discard temp, keep original untouched.

## Estimated savings (scan report heuristics only)

- x264/other → AV1: ~45% of input size
- HEVC → AV1 re-encode: ~25% of input size
