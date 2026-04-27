"""
SettingsOptimizer — translates a VideoScanner record into ffmpeg encoding settings.

Video  : encoder selected in config.json (AMD / NVIDIA / CPU).
         Transparent quality for x264/other sources; slightly more aggressive for HEVC.
         10-bit when source is 10-bit or HDR.

Audio  : Passthrough lossy (AC3, EAC3, AAC, MP3, Opus, Vorbis, DTS core).
         Convert lossless (TrueHD, DTS-MA, DTS-HD HRA, FLAC, PCM) → EAC3 640k/192k.

Subs   : Copy all. mov_text (MP4) converted to srt for MKV compatibility.
"""

import logging

import config as cfg
import encoders as enc

logger = logging.getLogger(__name__)

# ── audio codec tables ────────────────────────────────────────────────────────

_LOSSLESS_CODECS = {"truehd", "mlp", "flac", "pcm_s16le", "pcm_s24le", "pcm_s32le",
                    "pcm_s20le", "pcm_bluray", "pcm_dvd"}
_DTS_LOSSLESS_PROFILES = {"dts-hd ma", "dts-hd hra"}
_PASSTHROUGH_CODECS = {"ac3", "eac3", "aac", "mp3", "opus", "vorbis", "dts",
                       "ac4", "mp2", "wmav2"}
_MKV_INCOMPATIBLE_SUBS = {"mov_text"}
# Broadcast-only formats that cannot be usefully muxed into MKV — drop them.
_DROP_SUBS = {"dvb_teletext", "teletext", "eia_608"}


class SettingsOptimizer:
    """Return a complete ffmpeg settings dict for a scanned file record."""

    def __init__(self, encoder: str | None = None) -> None:
        conf = cfg.load()
        self.encoder = encoder or conf["encoder"]
        if self.encoder not in enc.PROFILES:
            raise ValueError(
                f"Unknown encoder '{self.encoder}' — valid options: {', '.join(enc.PROFILES)}"
            )
        self.profile = enc.PROFILES[self.encoder]

    def get_settings(self, file_info: dict) -> dict:
        video_info = file_info["video"]
        is_hevc_reencode = video_info["codec"] in ("hevc", "h265")

        return {
            "path":                 file_info["path"],
            "action":               file_info["action"],
            "size_gb":              file_info["size_gb"],
            "estimated_saving_gb":  file_info["estimated_saving_gb"],
            "resolution_tier":      video_info["resolution_tier"],
            "video":                self._video_settings(video_info, is_hevc_reencode),
            "crop":                 file_info.get("crop"),   # "W:H:X:Y" or None
            "audio":                self._audio_settings(file_info["audio_tracks"]),
            "subtitles":            self._subtitle_settings(file_info["subtitle_tracks"]),
            "container":            "mkv",
        }

    # ── video ─────────────────────────────────────────────────────────────────

    def _video_settings(self, video: dict, is_hevc_reencode: bool) -> dict:
        bit_depth = video.get("bit_depth", 8)
        hdr       = video.get("hdr", False)
        use_10bit = bit_depth == 10 or hdr

        quality = (
            self.profile["quality_efficient"]
            if is_hevc_reencode
            else self.profile["quality_transparent"]
        )

        # Colour primaries / transfer / matrix
        if hdr:
            primaries  = video.get("color_primaries") or "bt2020"
            trc        = video.get("color_transfer")  or "smpte2084"
            colorspace = video.get("color_space")     or "bt2020nc"
        else:
            primaries  = video.get("color_primaries") or "bt709"
            trc        = video.get("color_transfer")  or "bt709"
            colorspace = video.get("color_space")     or "bt709"

        # Only set color_range when the source declares it (or HDR which is always limited).
        # Forcing "tv" on an untagged source triggers a range conversion that crushes blacks.
        color_range = "tv" if hdr else (video.get("color_range") or None)

        # Cap output at source bitrate so we never produce a file larger than the original.
        source_bitrate_kbps = video.get("bitrate_kbps", 0)

        return {
            "encoder_profile":  self.encoder,
            "codec":            self.profile["codec"],
            "quality":          quality,
            "quality_label":    f"{self.profile['quality_label']} {quality}",
            "maxrate_kbps":     source_bitrate_kbps,
            "bitdepth":         10 if use_10bit else 8,
            "color_primaries":  primaries,
            "color_trc":        trc,
            "colorspace":       colorspace,
            "color_range":      color_range,
        }

    # ── audio ─────────────────────────────────────────────────────────────────

    def _audio_settings(self, tracks: list[dict]) -> list[dict]:
        result = []
        for track in tracks:
            codec   = track["codec"].lower()
            profile = track.get("profile", "").lower()
            channels = track.get("channels", 2)

            is_dts_lossless = codec == "dts" and any(p in profile for p in _DTS_LOSSLESS_PROFILES)

            if codec in _LOSSLESS_CODECS or is_dts_lossless:
                bitrate = "640k" if channels >= 6 else "192k"
                result.append({
                    "stream_index": track["stream_index"],
                    "lang":         track["lang"],
                    "action":       "encode",
                    "codec":        "eac3",
                    "bitrate":      bitrate,
                    "reason":       f"lossless {codec} ({profile}) → eac3 {bitrate}",
                })
            elif codec in _PASSTHROUGH_CODECS:
                result.append({
                    "stream_index": track["stream_index"],
                    "lang":         track["lang"],
                    "action":       "copy",
                    "reason":       f"passthrough {codec}",
                })
            else:
                logger.warning(f"  Unknown audio codec '{codec}' (lang={track['lang']}) — will copy")
                result.append({
                    "stream_index": track["stream_index"],
                    "lang":         track["lang"],
                    "action":       "copy",
                    "reason":       f"unknown codec {codec} — copy",
                })

        return result

    # ── subtitles ─────────────────────────────────────────────────────────────

    def _subtitle_settings(self, tracks: list[dict]) -> list[dict]:
        result = []
        for track in tracks:
            codec  = track["codec"].lower()
            if codec in _DROP_SUBS:
                target = "drop"
                reason = f"drop {codec} (not compatible with MKV)"
            elif codec in _MKV_INCOMPATIBLE_SUBS:
                target = "srt"
                reason = f"convert {codec} → srt (MKV compat)"
            else:
                target = "copy"
                reason = f"passthrough {codec}"
            result.append({
                "stream_index": track["stream_index"],
                "lang":         track["lang"],
                "codec":        target,
                "reason":       reason,
            })
        return result
