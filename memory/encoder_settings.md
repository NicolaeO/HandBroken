---
name: Encoder settings
description: AMD AMF AV1 QP values, ffmpeg flags, and transcode decision thresholds
type: project
---

## Encoder: av1_amf (AMD AV1 hardware, RX 7900 XT / RDNA 3)

Switched from hevc_amf to av1_amf. HEVC caused visible blocking in dark scenes;
AV1 with -aq_mode caq fixes this. Speed: ~120fps (vs ~400fps for HEVC) — acceptable trade-off.

```
-c:v av1_amf -usage high_quality -quality quality -rc cqp
-preanalysis 1 -aq_mode caq
```

**Note:** `-preanalysis` and `-vbaq` do NOT work with hevc_amf in CQP mode (encoder init fails).
Both work correctly with av1_amf.

### QP values

| Scenario | qp_i | qp_p | qp_b | Rationale |
|---|---|---|---|---|
| x264/other → AV1 | 20 | 24 | 28 | Transparent quality, confirmed working |
| HEVC → AV1 re-encode | 24 | 28 | 32 | Reclaim space, still good quality |

**How to apply:** adjust `_QP_TRANSPARENT` / `_QP_EFFICIENT` tuples in `optimizer.py`.
Bump up by 4 if files are too large; drop by 4 if artifacts appear.

### 10-bit / HDR
- AV1 AMF uses `-bitdepth 10` (not `-profile:v main10` like HEVC AMF)
- AV1 Main profile handles both 8-bit and 10-bit natively

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
