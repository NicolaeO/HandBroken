"""
SettingsOptimizer — translates a VideoScanner record into ffmpeg encoding settings.

Video: AMD av1_amf, CQP mode.
  - x264/other → AV1 : QP 20/24/28  (transparent quality)
  - HEVC re-encode    : QP 24/28/32  (slightly more aggressive to reclaim space)
  - 10-bit via -bitdepth 10 when source is 10-bit or HDR
  - pre-analysis and adaptive quantization enabled (supported by AV1 AMF unlike HEVC AMF)

Audio (Option B):
  - Passthrough: AC3, EAC3, AAC, MP3, Opus, Vorbis, DTS (lossy core)
  - Convert → EAC3: TrueHD, DTS-MA, DTS-HD HRA, FLAC, PCM  (640k ≥6ch / 192k stereo)

Subtitles: copy all; mov_text (MP4 text) converted to srt for MKV compatibility.
"""

import logging

logger = logging.getLogger(__name__)

# ── audio codec tables ────────────────────────────────────────────────────────

# Lossless codecs → always convert to EAC3
_LOSSLESS_CODECS = {"truehd", "mlp", "flac", "pcm_s16le", "pcm_s24le", "pcm_s32le",
                    "pcm_s20le", "pcm_bluray", "pcm_dvd"}

# DTS variants that are lossless (detected via profile string)
_DTS_LOSSLESS_PROFILES = {"dts-hd ma", "dts-hd hra"}

# Lossy codecs → passthrough unchanged
_PASSTHROUGH_CODECS = {"ac3", "eac3", "aac", "mp3", "opus", "vorbis", "dts",
                       "ac4", "mp2", "wmav2"}

# MKV cannot store mov_text subtitles — convert to srt
_MKV_INCOMPATIBLE_SUBS = {"mov_text"}

# AV1 AMF QP tuples: (qp_i, qp_p, qp_b)
# AV1 is more efficient than HEVC so these are slightly higher than HEVC equivalents.
# Start conservative — adjust upward if files are still too large.
_QP_TRANSPARENT = (20, 24, 28)   # x264/other → AV1 (transparent quality)
_QP_EFFICIENT   = (24, 28, 32)   # HEVC → AV1 re-encode (reclaim space)


class SettingsOptimizer:
    """Return a complete ffmpeg settings dict for a scanned file record."""

    def get_settings(self, file_info: dict) -> dict:
        video_info = file_info["video"]
        is_hevc_reencode = video_info["codec"] in ("hevc", "h265")

        return {
            "path": file_info["path"],
            "action": file_info["action"],
            "size_gb": file_info["size_gb"],
            "estimated_saving_gb": file_info["estimated_saving_gb"],
            "resolution_tier": video_info["resolution_tier"],
            "video": self._video_settings(video_info, is_hevc_reencode),
            "audio": self._audio_settings(file_info["audio_tracks"]),
            "subtitles": self._subtitle_settings(file_info["subtitle_tracks"]),
            "container": "mkv",
        }

    # ── video ─────────────────────────────────────────────────────────────────

    def _video_settings(self, video: dict, is_hevc_reencode: bool) -> dict:
        bit_depth = video.get("bit_depth", 8)
        hdr = video.get("hdr", False)
        use_10bit = bit_depth == 10 or hdr

        qp_i, qp_p, qp_b = _QP_EFFICIENT if is_hevc_reencode else _QP_TRANSPARENT

        out = {
            "encoder": "av1_amf",
            "usage": "high_quality",      # AMD high quality transcoding mode
            "quality_preset": "quality",  # AMD quality/balanced/speed
            "rc": "cqp",
            "qp_i": qp_i,
            "qp_p": qp_p,
            "qp_b": qp_b,
            "bitdepth": 10 if use_10bit else 8,
            "preanalysis": True,          # works with AV1 AMF (unlike HEVC CQP)
            "aq_mode": "caq",             # context adaptive quantization — helps dark scenes
        }

        # Pass through HDR colour metadata
        if hdr:
            out["hdr_metadata"] = {
                "color_primaries": video.get("color_primaries") or "bt2020",
                "color_trc": video.get("color_transfer") or "smpte2084",
                "colorspace": video.get("color_space") or "bt2020nc",
            }

        return out

    # ── audio ─────────────────────────────────────────────────────────────────

    def _audio_settings(self, tracks: list[dict]) -> list[dict]:
        result = []
        for track in tracks:
            codec = track["codec"].lower()
            profile = track.get("profile", "").lower()
            channels = track.get("channels", 2)

            is_dts_lossless = codec == "dts" and any(p in profile for p in _DTS_LOSSLESS_PROFILES)

            if codec in _LOSSLESS_CODECS or is_dts_lossless:
                bitrate = "640k" if channels >= 6 else "192k"
                result.append({
                    "stream_index": track["stream_index"],
                    "lang": track["lang"],
                    "action": "encode",
                    "codec": "eac3",
                    "bitrate": bitrate,
                    "reason": f"lossless {codec} ({profile}) → eac3 {bitrate}",
                })
            elif codec in _PASSTHROUGH_CODECS:
                result.append({
                    "stream_index": track["stream_index"],
                    "lang": track["lang"],
                    "action": "copy",
                    "reason": f"passthrough {codec}",
                })
            else:
                logger.warning(f"  Unknown audio codec '{codec}' (lang={track['lang']}) — will copy")
                result.append({
                    "stream_index": track["stream_index"],
                    "lang": track["lang"],
                    "action": "copy",
                    "reason": f"unknown codec {codec} — copy",
                })

        return result

    # ── subtitles ─────────────────────────────────────────────────────────────

    def _subtitle_settings(self, tracks: list[dict]) -> list[dict]:
        result = []
        for track in tracks:
            codec = track["codec"].lower()
            target = "srt" if codec in _MKV_INCOMPATIBLE_SUBS else "copy"
            result.append({
                "stream_index": track["stream_index"],
                "lang": track["lang"],
                "codec": target,
                "reason": f"convert {codec} → srt (MKV compat)" if target == "srt" else f"passthrough {codec}",
            })
        return result
