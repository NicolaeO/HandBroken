"""
SettingsOptimizer — translates a VideoScanner record into ffmpeg encoding settings.

Video: AMD av1_amf, QVBR mode.
  - x264/other → AV1 : QVBR quality 20  (transparent quality)
  - HEVC re-encode    : QVBR quality 25  (slightly more aggressive to reclaim space)
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

# AV1 AMF QVBR quality levels (1–51, HIGHER = better quality / more bits).
# NOTE: scale is opposite to CRF — higher value = better quality, not lower.
# CQP mode was tested and produced wildly inconsistent bitrates (77 Mbps!) — QVBR is stable.
# Tested on 1080p Ozark dark scene: Q40 → ~900 kbps, Q45 → ~1.3 Mbps, Q51 → ~2 Mbps.
# Adjust upward (+3) if quality looks soft; downward (-3) if files are too large.
_QVBR_TRANSPARENT = 40   # x264/other → AV1 (transparent quality)
_QVBR_EFFICIENT   = 33   # HEVC → AV1 re-encode (reclaim space)


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

        qvbr = _QVBR_EFFICIENT if is_hevc_reencode else _QVBR_TRANSPARENT

        # Always pass colour metadata — without it the encoder defaults to unspecified
        # and players render colours incorrectly (wrong gamma / colour shift).
        if hdr:
            primaries  = video.get("color_primaries") or "bt2020"
            trc        = video.get("color_transfer")  or "smpte2084"
            colorspace = video.get("color_space")     or "bt2020nc"
        else:
            primaries  = video.get("color_primaries") or "bt709"
            trc        = video.get("color_transfer")  or "bt709"
            colorspace = video.get("color_space")     or "bt709"

        # Preserve colour range (tv = limited 16-235, pc = full 0-255)
        color_range = video.get("color_range") or "tv"

        # Cap output at source bitrate so we never produce a larger file.
        # QVBR still drives quality — this only kicks in when the source is already compact.
        source_bitrate_kbps = video.get("bitrate_kbps", 0)

        out = {
            "encoder": "av1_amf",
            "usage": "high_quality",      # AMD high quality transcoding mode
            "quality_preset": "quality",  # AMD quality/balanced/speed
            "rc": "qvbr",
            "qvbr_quality_level": qvbr,
            "maxrate_kbps": source_bitrate_kbps,  # 0 = uncapped (unknown source bitrate)
            "bitdepth": 10 if use_10bit else 8,
            "preanalysis": True,          # works with AV1 AMF (unlike HEVC CQP)
            "aq_mode": "caq",             # context adaptive quantization — helps dark scenes
            "color_primaries": primaries,
            "color_trc": trc,
            "colorspace": colorspace,
            "color_range": color_range,
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
