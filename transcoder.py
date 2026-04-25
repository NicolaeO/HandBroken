"""
Transcoder — runs ffmpeg on a single file using settings from SettingsOptimizer.

Success flow:
  1. Encode source → _TEMP_<stem>.mkv in the same folder
  2. Rename original → _ORIG_<original_filename>  (preserves original extension)
  3. Rename temp → <stem>.mkv

Size guard: if output is > 110% of input size (edge case: already well-optimised
SD content), the temp file is deleted and the original is left untouched.
"""

import logging
import subprocess
import time
from pathlib import Path

logger = logging.getLogger(__name__)

FFMPEG = "ffmpeg"

# If output exceeds input by this factor, abort replacement (keep original)
_MAX_SIZE_RATIO = 1.10


class Transcoder:
    def __init__(self, ffmpeg_path: str = FFMPEG):
        self.ffmpeg_path = ffmpeg_path

    # ── public ────────────────────────────────────────────────────────────────

    def transcode(self, settings: dict) -> bool:
        """
        Encode one file. Returns True on success (including the no-replace case
        where the output was larger than the input).
        """
        src = Path(settings["path"])
        if not src.exists():
            logger.error(f"  Source not found: {src}")
            return False

        temp_out = src.parent / f"_TEMP_{src.stem}.mkv"
        orig_out = src.parent / f"_ORIG_{src.name}"

        # Guard: if a previous failed run left a temp file, remove it
        if temp_out.exists():
            logger.warning(f"  Removing stale temp file: {temp_out.name}")
            temp_out.unlink()

        cmd = self._build_command(src, temp_out, settings)
        self._log_plan(settings, src)

        start = time.time()
        try:
            result = subprocess.run(cmd)
        except Exception as e:
            logger.error(f"  ffmpeg exception: {e}")
            self._cleanup(temp_out)
            return False

        elapsed = time.time() - start
        logger.info(f"  Encode time: {int(elapsed // 60)}m {int(elapsed % 60)}s")

        if result.returncode != 0:
            logger.error(f"  ffmpeg failed (exit {result.returncode})")
            self._cleanup(temp_out)
            return False

        # Size guard
        in_bytes = src.stat().st_size
        out_bytes = temp_out.stat().st_size
        ratio = out_bytes / in_bytes if in_bytes else 1

        if ratio > _MAX_SIZE_RATIO:
            logger.warning(
                f"  Output is {ratio:.0%} of input size — output larger than source, "
                f"keeping original and discarding encode"
            )
            self._cleanup(temp_out)
            return True  # Not an error; source is already optimal

        # Replace original
        try:
            src.rename(orig_out)
            final = src.parent / (src.stem + ".mkv")
            temp_out.rename(final)
            in_gb = in_bytes / 1024 ** 3
            out_gb = out_bytes / 1024 ** 3
            logger.info(f"  {in_gb:.2f} GB → {out_gb:.2f} GB ({ratio:.0%})  saved {in_gb - out_gb:.2f} GB")
            logger.info(f"  Original kept as: {orig_out.name}")
        except Exception as e:
            logger.error(f"  Error replacing file: {e}")
            self._cleanup(temp_out)
            return False

        return True

    # ── command builder ───────────────────────────────────────────────────────

    def _build_command(self, src: Path, out: Path, settings: dict) -> list[str]:
        vs = settings["video"]
        audio_tracks = settings["audio"]
        subtitle_tracks = settings["subtitles"]

        cmd = [self.ffmpeg_path, "-i", str(src)]

        # ── stream mapping ───────────────────────────────────────────────────
        cmd += ["-map", "0:v:0"]                    # first video stream only
        for t in audio_tracks:
            cmd += ["-map", f"0:a:{t['stream_index']}"]
        cmd += ["-map", "0:s?"]                     # all subtitle streams
        cmd += ["-map", "0:t?"]                     # attachments (e.g. MKV fonts)

        # ── video ────────────────────────────────────────────────────────────
        cmd += [
            "-c:v",        vs["encoder"],
            "-profile:v",  vs["profile"],
            "-quality",    vs["quality_preset"],
            "-rc",         vs["rc"],
            "-qp_i",       str(vs["qp_i"]),
            "-qp_p",       str(vs["qp_p"]),
            "-qp_b",       str(vs["qp_b"]),
            "-preanalysis", "1" if vs.get("preanalysis") else "0",
            "-vbaq",        "1" if vs.get("vbaq") else "0",
        ]

        # HDR colour metadata passthrough
        hdr = vs.get("hdr_metadata")
        if hdr:
            cmd += [
                "-color_primaries", hdr["color_primaries"],
                "-color_trc",       hdr["color_trc"],
                "-colorspace",      hdr["colorspace"],
            ]

        # ── audio ────────────────────────────────────────────────────────────
        cmd += ["-c:a", "copy"]   # default: copy everything
        for out_idx, t in enumerate(audio_tracks):
            if t["action"] == "encode":
                cmd += [
                    f"-c:a:{out_idx}", t["codec"],
                    f"-b:a:{out_idx}", t["bitrate"],
                ]

        # ── subtitles ────────────────────────────────────────────────────────
        cmd += ["-c:s", "copy"]   # default: copy everything
        for out_idx, t in enumerate(subtitle_tracks):
            if t["codec"] != "copy":
                cmd += [f"-c:s:{out_idx}", t["codec"]]

        # ── output ───────────────────────────────────────────────────────────
        cmd += [
            "-max_muxing_queue_size", "9999",
            "-y",
            str(out),
        ]

        return cmd

    # ── helpers ───────────────────────────────────────────────────────────────

    def _log_plan(self, settings: dict, src: Path) -> None:
        vs = settings["video"]
        logger.info(f"  File   : {src.name}  ({settings['size_gb']:.2f} GB)")
        logger.info(f"  Video  : {vs['encoder']} {vs['profile']}  "
                    f"QP {vs['qp_i']}/{vs['qp_p']}/{vs['qp_b']}")
        for t in settings["audio"]:
            logger.info(f"  Audio [{t['lang']}]: {t['reason']}")
        for t in settings["subtitles"]:
            if t["codec"] != "copy":
                logger.info(f"  Sub   [{t['lang']}]: {t['reason']}")

    def _cleanup(self, path: Path) -> None:
        if path.exists():
            try:
                path.unlink()
                logger.info(f"  Removed temp: {path.name}")
            except Exception as e:
                logger.error(f"  Could not remove temp {path.name}: {e}")
