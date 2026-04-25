---
name: Encoder settings
description: AMD AMF QP values, ffmpeg flags, and transcode decision thresholds
type: project
originSessionId: b401d7e5-676a-45cf-ad0d-e0b86509630f
---
## AMD hevc_amf settings (ffmpeg)

```
-c:v hevc_amf -quality quality -rc cqp
-preanalysis 1 -vbaq 1
```

### QP values

| Scenario | qp_i | qp_p | qp_b | Rationale |
|---|---|---|---|---|
| x264/other → x265 | 20 | 22 | 24 | Transparent quality |
| x265 → x265 re-encode | 22 | 24 | 26 | Reclaim space from bloated x265 |

### Profile
- `main` (8-bit) when source is 8-bit SDR
- `main10` when source is 10-bit or HDR

## Transcode decision thresholds

x265 files are only re-encoded if they exceed EITHER the size OR bitrate limit for their tier.
Non-x265 files are always transcoded.

| Tier | Size limit | Bitrate limit |
|---|---|---|
| 4K (≥2160p) | 10 GB | 40 Mbps |
| 1080p | 8 GB | 15 Mbps |
| 720p | 4 GB | 8 Mbps |
| SD (<720p) | 2 GB | 4 Mbps |

## Size guard

If encoded output > 110% of input size → discard output, keep original.
Handles cases where source is already very well compressed (common with SD content).

## Estimated savings (for scan report)

- x264/other → x265: ~45% of input size
- x265 → x265 re-encode: ~25% of input size

These are rough heuristics for planning purposes only.

**How to apply:** if tuning quality, adjust QP_TRANSPARENT / QP_EFFICIENT tuples in optimizer.py. If tuning thresholds, adjust _SIZE_LIMIT_GB / _BITRATE_LIMIT_KBPS dicts in scanner.py.
