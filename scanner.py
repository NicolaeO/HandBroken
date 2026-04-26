"""
VideoScanner — probes a folder recursively and produces a JSON scan report.

Each record contains codec, bitrate, resolution, HDR flag, audio/subtitle tracks,
and a recommended action (transcode / skip).
"""

import json
import logging
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)

FFPROBE = "ffprobe"

VIDEO_EXTENSIONS = {
    '.mkv', '.mp4', '.avi', '.m4v', '.mov', '.webm', '.flv', '.ts', '.vob', '.ogv', '.ogg', '.rrc', '.gifv',
    '.mng', '.qt', '.wmv', '.yuv', '.rm', '.asf', '.amv', '.m4p', '.mpg', '.mp2', '.mpeg', '.mpe', '.mpv',
    '.svi', '.3gp', '.3g2', '.mxf', '.roq', '.nsv', '.f4v', '.f4p', '.f4a', '.f4b', '.mod'
}


# Thresholds for re-encoding already-x265 files.
# These are calibrated to x265 expectations, not x264.
#
# MB/min = size_gb * 1024 / duration_min  (most duration-aware signal)
# bitrate = stream-level kbps             (catches high-quality encodes regardless of length)
# size    = absolute ceiling              (catches very long or very large files)
_SIZE_LIMIT_GB     = {"4k": 10.0, "1080p": 6.0,   "720p": 3.0,   "sd": 1.5  }
_BITRATE_LIMIT_KBPS= {"4k": 12_000, "1080p": 3_500, "720p": 2_000, "sd": 1_200}
_MB_PER_MIN_LIMIT  = {"4k": 100.0, "1080p": 30.0,  "720p": 15.0,  "sd": 8.0  }


# ── helpers ──────────────────────────────────────────────────────────────────

def _resolution_tier(width: int, height: int) -> str:
    if height >= 2160 or width >= 3840:
        return "4k"
    if height >= 1080 or width >= 1920:
        return "1080p"
    if height >= 720 or width >= 1280:
        return "720p"
    return "sd"


def _is_hdr(stream: dict) -> bool:
    transfer = stream.get("color_transfer", "")
    primaries = stream.get("color_primaries", "")
    return transfer in ("smpte2084", "arib-std-b67") or primaries == "bt2020"


def _bit_depth(pix_fmt: str) -> int:
    return 10 if any(x in pix_fmt for x in ("10le", "10be", "p010", "yuv420p10")) else 8


def _fps(r_frame_rate: str) -> float:
    try:
        num, den = r_frame_rate.split("/")
        return round(int(num) / int(den), 3) if int(den) else 0
    except Exception:
        return 0


def _parse_video(s: dict) -> dict:
    width = s.get("width", 0)
    height = s.get("height", 0)
    pix_fmt = s.get("pix_fmt", "")
    return {
        "codec": s.get("codec_name", "unknown"),
        "profile": s.get("profile", ""),
        "width": width,
        "height": height,
        "resolution_tier": _resolution_tier(width, height),
        "fps": _fps(s.get("r_frame_rate", "0/1")),
        "bit_depth": _bit_depth(pix_fmt),
        "pix_fmt": pix_fmt,
        "hdr": _is_hdr(s),
        "color_transfer": s.get("color_transfer", ""),
        "color_primaries": s.get("color_primaries", ""),
        "color_space": s.get("color_space", ""),
        "bitrate_kbps": int(s.get("bit_rate", 0)) // 1000,
    }


def _parse_audio(s: dict, idx: int) -> dict:
    return {
        "stream_index": idx,
        "codec": s.get("codec_name", "unknown"),
        "profile": s.get("profile", ""),
        "channels": s.get("channels", 2),
        "channel_layout": s.get("channel_layout", ""),
        "sample_rate": s.get("sample_rate", ""),
        "bitrate_kbps": int(s.get("bit_rate", 0)) // 1000,
        "lang": s.get("tags", {}).get("language", "und"),
        "title": s.get("tags", {}).get("title", ""),
    }


def _parse_subtitle(s: dict, idx: int) -> dict:
    return {
        "stream_index": idx,
        "codec": s.get("codec_name", "unknown"),
        "lang": s.get("tags", {}).get("language", "und"),
        "title": s.get("tags", {}).get("title", ""),
    }


def _estimate_saving(size_gb: float, codec: str, action: str) -> float:
    if action == "skip":
        return 0.0
    # x265 re-encode: ~25% savings; x264/other → x265: ~45% savings
    factor = 0.25 if codec in ("hevc", "h265") else 0.45
    return round(size_gb * factor, 2)


# ── main class ────────────────────────────────────────────────────────────────

class VideoScanner:
    """Scan a folder and produce a list of per-file metadata dicts."""

    def __init__(self, ffprobe_path: str = FFPROBE):
        self.ffprobe_path = ffprobe_path
        self.results: list[dict] = []

    # ── public ──────────────────────────────────────────────────────────────

    def scan_folder(self, folder: str | Path) -> list[dict]:
        folder = Path(folder)
        if not folder.exists():
            raise FileNotFoundError(f"Folder not found: {folder}")

        video_files = sorted(
            f for f in folder.rglob("*")
            if f.is_file()
            and f.suffix.lower() in VIDEO_EXTENSIONS
            and not f.name.startswith(("_ORIG_", "_TEMP_"))
        )

        logger.info(f"Found {len(video_files)} video file(s) in {folder}")
        self.results = []

        for i, path in enumerate(video_files, 1):
            logger.info(f"  [{i}/{len(video_files)}] {path.name}")
            info = self._scan_file(path)
            if info:
                self.results.append(info)

        self._log_summary()
        return self.results

    def save_json(self, output_path: str | Path) -> None:
        output_path = Path(output_path)
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(self.results, f, indent=2, ensure_ascii=False)
        logger.info(f"Saved scan results → {output_path}")

    @staticmethod
    def load_json(path: str | Path) -> list[dict]:
        with open(path, encoding="utf-8") as f:
            return json.load(f)

    # ── private ─────────────────────────────────────────────────────────────

    def _scan_file(self, path: Path) -> dict | None:
        probe = self._probe(path)
        if not probe:
            return None

        streams = probe.get("streams", [])
        fmt = probe.get("format", {})

        video_streams = [s for s in streams if s.get("codec_type") == "video"]
        audio_streams = [s for s in streams if s.get("codec_type") == "audio"]
        subtitle_streams = [s for s in streams if s.get("codec_type") == "subtitle"]

        if not video_streams:
            logger.warning(f"    No video stream — skipping")
            return None

        video = _parse_video(video_streams[0])

        # Derive video bitrate from container total when stream-level is missing
        if video["bitrate_kbps"] == 0:
            total_kbps = int(fmt.get("bit_rate", 0)) // 1000
            audio_kbps = sum(int(a.get("bit_rate", 0)) // 1000 for a in audio_streams)
            video["bitrate_kbps"] = max(0, total_kbps - audio_kbps)

        size_gb = path.stat().st_size / (1024 ** 3)
        duration_min = float(fmt.get("duration", 0)) / 60
        mb_per_min = (size_gb * 1024 / duration_min) if duration_min > 0 else 0
        action = self._decide_action(video, size_gb, duration_min)
        saving = _estimate_saving(size_gb, video["codec"], action)

        tier = video["resolution_tier"]
        reason = self._action_reason(video, size_gb, mb_per_min, action)

        logger.info(f"    {video['codec'].upper()} {video['width']}x{video['height']} "
                    f"{video['bitrate_kbps']} kbps  {size_gb:.2f} GB  {mb_per_min:.1f} MB/min"
                    f"  → {action.upper()} ({reason})")

        return {
            "path": str(path),
            "size_gb": round(size_gb, 3),
            "duration_min": round(duration_min, 1),
            "action": action,
            "action_reason": reason,
            "estimated_saving_gb": saving,
            "video": video,
            "audio_tracks": [_parse_audio(s, i) for i, s in enumerate(audio_streams)],
            "subtitle_tracks": [_parse_subtitle(s, i) for i, s in enumerate(subtitle_streams)],
        }

    def _decide_action(self, video: dict, size_gb: float, duration_min: float) -> str:
        codec = video["codec"]
        tier = video["resolution_tier"]
        bitrate = video["bitrate_kbps"]

        if codec in ("hevc", "h265"):
            mb_per_min = (size_gb * 1024 / duration_min) if duration_min > 0 else 0
            over_size     = size_gb  > _SIZE_LIMIT_GB[tier]
            over_bitrate  = bitrate  > 0 and bitrate > _BITRATE_LIMIT_KBPS[tier]
            over_density  = mb_per_min > 0 and mb_per_min > _MB_PER_MIN_LIMIT[tier]
            return "transcode" if (over_size or over_bitrate or over_density) else "skip"
    
        return "transcode"

    def _action_reason(self, video: dict, size_gb: float, mb_per_min: float, action: str) -> str:
        codec = video["codec"]
        tier = video["resolution_tier"]
        bitrate = video["bitrate_kbps"]

        if action == "skip":
            return "already x265, within limits"
        if codec not in ("hevc", "h265"):
            return f"{codec} → x265"
        if size_gb > _SIZE_LIMIT_GB[tier]:
            return f"x265 but {size_gb:.1f} GB > {_SIZE_LIMIT_GB[tier]} GB limit"
        if bitrate > 0 and bitrate > _BITRATE_LIMIT_KBPS[tier]:
            return f"x265 but {bitrate} kbps > {_BITRATE_LIMIT_KBPS[tier]} kbps limit"
        if mb_per_min > _MB_PER_MIN_LIMIT[tier]:
            return f"x265 but {mb_per_min:.1f} MB/min > {_MB_PER_MIN_LIMIT[tier]} MB/min limit"
        return "x265 re-encode"

    def _probe(self, path: Path) -> dict | None:
        cmd = [
            self.ffprobe_path, "-v", "quiet",
            "-print_format", "json",
            "-show_format", "-show_streams",
            str(path),
        ]
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
            if r.returncode != 0:
                logger.error(f"    ffprobe error: {r.stderr.strip()}")
                return None
            return json.loads(r.stdout)
        except subprocess.TimeoutExpired:
            logger.error(f"    ffprobe timeout for {path.name}")
            return None
        except Exception as e:
            logger.error(f"    ffprobe exception: {e}")
            return None

    def _log_summary(self) -> None:
        to_transcode = [r for r in self.results if r["action"] == "transcode"]
        total_saving = sum(r["estimated_saving_gb"] for r in to_transcode)
        total_size = sum(r["size_gb"] for r in self.results)
        logger.info("─" * 60)
        logger.info(f"Total files : {len(self.results)}  ({total_size:.1f} GB)")
        logger.info(f"To transcode: {len(to_transcode)}")
        logger.info(f"To skip     : {len(self.results) - len(to_transcode)}")
        logger.info(f"Est. savings: ~{total_saving:.1f} GB")
        logger.info("─" * 60)
