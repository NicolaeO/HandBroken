"""
Transcoder — runs ffmpeg on a single file using settings from SettingsOptimizer.

Success flow:
  1. Encode source → _TEMP_<stem>.mkv in the same folder
  2. Move original → <same_folder>/.originals/<original_filename>
  3. Rename temp → <stem>.mkv

Size guard: if output is > 110% of input size (edge case: already well-optimised
SD content), the temp file is deleted and the original is left untouched.
"""

import logging
import subprocess
import threading
import time
from pathlib import Path

import encoders

logger = logging.getLogger(__name__)

FFMPEG = "ffmpeg"

# If output exceeds input by this factor, abort replacement (keep original)
_MAX_SIZE_RATIO = 1.10

# Sanity check: if temp file exceeds this size after _SANITY_CHECK_AFTER seconds,
# abort — encoder is likely running near-lossless due to bad QP settings.
# Set relative to source size: abort if temp > source * this factor mid-encode.
_SANITY_CHECK_AFTER_SEC = 120    # start checking after 2 minutes
_SANITY_MAX_RATIO       = 2.0    # abort if temp is already 2x the source size


class Transcoder:
    def __init__(self, ffmpeg_path: str = FFMPEG):
        self.ffmpeg_path = ffmpeg_path

    # ── public ────────────────────────────────────────────────────────────────

    def transcode(self, settings: dict, keep_larger: bool = False) -> bool:
        """
        Encode one file. Returns True on success (including the no-replace case
        where the output was larger than the input).

        keep_larger: if True, skip the size guard and always replace the original.
        """
        src = Path(settings["path"])
        if not src.exists():
            logger.error(f"  Source not found: {src}")
            return False

        temp_out  = src.parent / f"_TEMP_{src.stem}.mkv"
        orig_dir  = src.parent / ".originals"
        orig_out  = orig_dir / src.name

        # Guard: if a previous failed run left a temp file, remove it
        if temp_out.exists():
            logger.warning(f"  Removing stale temp file: {temp_out.name}")
            temp_out.unlink()

        cmd = self._build_command(src, temp_out, settings)
        self._log_plan(settings, src)

        in_bytes = src.stat().st_size
        start = time.time()
        aborted = threading.Event()

        try:
            proc = subprocess.Popen(cmd)
            self._watch_size(proc, temp_out, in_bytes, aborted)
            proc.wait()
            result = proc
        except Exception as e:
            logger.error(f"  ffmpeg exception: {e}")
            self._cleanup(temp_out)
            return False

        elapsed = time.time() - start
        logger.info(f"  Encode time: {int(elapsed // 60)}m {int(elapsed % 60)}s")

        if aborted.is_set():
            logger.error("  Aborted: temp file grew beyond sanity limit — QP values likely too low")
            self._cleanup(temp_out)
            return False

        if result.returncode != 0:
            logger.error(f"  ffmpeg failed (exit {result.returncode})")
            self._cleanup(temp_out)
            return False

        # Size guard
        out_bytes = temp_out.stat().st_size
        ratio = out_bytes / in_bytes if in_bytes else 1

        if ratio > _MAX_SIZE_RATIO:
            if keep_larger:
                logger.warning(
                    f"  Output is {ratio:.0%} of input size — larger than source, "
                    f"keeping anyway (--keep-larger)"
                )
            else:
                logger.warning(
                    f"  Output is {ratio:.0%} of input size — output larger than source, "
                    f"keeping original and discarding encode"
                )
                self._cleanup(temp_out)
                return True  # Not an error; source is already optimal

        # Replace original
        try:
            orig_dir.mkdir(exist_ok=True)
            src.rename(orig_out)
            final = src.parent / (src.stem + ".mkv")
            temp_out.rename(final)
            in_gb = in_bytes / 1024 ** 3
            out_gb = out_bytes / 1024 ** 3
            logger.info(f"  {in_gb:.2f} GB → {out_gb:.2f} GB ({ratio:.0%})  saved {in_gb - out_gb:.2f} GB")
            logger.info(f"  Original → .originals/{src.name}")
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

        # ── video filter chain ────────────────────────────────────────────────
        filters = []

        # Crop black bars if detected during scan (W:H:X:Y)
        if settings.get("crop"):
            filters.append(f"crop={settings['crop']}")

        # setparams marks decoded frames with explicit colour info before encoding.
        # This writes colour data into the AV1 bitstream (sequence header OBU),
        # not just the container — hardware decoders (AMD, Intel) read the bitstream,
        # not the container tags, so without this they default to unspecified and
        # render colours wrong (blue/dark tint).
        # Range is only set when the source explicitly declares it (or HDR, which is
        # always limited). Forcing "tv" on an untagged source triggers a range
        # conversion that crushes blacks and makes the output darker.
        setparams = (
            f"setparams=colorspace={vs['colorspace']}"
            f":color_primaries={vs['color_primaries']}"
            f":color_trc={vs['color_trc']}"
        )
        if vs.get("color_range"):
            range_filter = "limited" if vs["color_range"] == "tv" else vs["color_range"]
            setparams += f":range={range_filter}"
        filters.append(setparams)

        cmd += ["-vf", ",".join(filters)]

        # ── video encoder flags (encoder-specific, from encoders.py) ─────────
        cmd += encoders.build_video_flags(vs["encoder_profile"], vs)

        # Colour metadata — always set so the encoder tags the output correctly.
        # Without this the encoder defaults to unspecified and players render colours wrong.
        cmd += [
            "-color_primaries", vs["color_primaries"],
            "-color_trc",       vs["color_trc"],
            "-colorspace",      vs["colorspace"],
        ]
        if vs.get("color_range"):
            cmd += ["-color_range", vs["color_range"]]

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
        maxrate_str = f"  maxrate={vs['maxrate_kbps']}k" if vs.get("maxrate_kbps", 0) > 0 else ""
        logger.info(f"  Video  : {vs['codec']} {vs['bitdepth']}bit  {vs['quality_label']}{maxrate_str}")
        if settings.get("crop"):
            logger.info(f"  Crop   : {settings['crop']} (black bars removed)")
        for t in settings["audio"]:
            logger.info(f"  Audio [{t['lang']}]: {t['reason']}")
        for t in settings["subtitles"]:
            if t["codec"] != "copy":
                logger.info(f"  Sub   [{t['lang']}]: {t['reason']}")

    def _watch_size(self, proc: subprocess.Popen, temp: Path,
                    in_bytes: int, aborted: threading.Event) -> None:
        """Background thread: kill ffmpeg if temp file exceeds sanity limit."""
        def _run():
            time.sleep(_SANITY_CHECK_AFTER_SEC)
            while proc.poll() is None:
                try:
                    if temp.exists():
                        temp_bytes = temp.stat().st_size
                        if temp_bytes > in_bytes * _SANITY_MAX_RATIO:
                            in_gb   = in_bytes  / 1024 ** 3
                            temp_gb = temp_bytes / 1024 ** 3
                            logger.error(
                                f"  SANITY CHECK FAILED: temp is {temp_gb:.1f} GB "
                                f"vs source {in_gb:.1f} GB — killing ffmpeg"
                            )
                            aborted.set()
                            proc.kill()
                            return
                except FileNotFoundError:
                    pass
                time.sleep(30)

        t = threading.Thread(target=_run, daemon=True)
        t.start()

    def _cleanup(self, path: Path) -> None:
        if path.exists():
            try:
                path.unlink()
                logger.info(f"  Removed temp: {path.name}")
            except Exception as e:
                logger.error(f"  Could not remove temp {path.name}: {e}")
