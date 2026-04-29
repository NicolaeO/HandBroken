"""
Encoder profiles for AMD AMF AV1, NVIDIA NVENC AV1, and CPU (libsvtav1).

Quality scale per encoder — they differ:
  AMD  av1_amf   QVBR 1-51   HIGHER = better quality   (Q40 transparent / Q33 efficient)
  NVIDIA av1_nvenc CQ  0-51   LOWER  = better quality   (CQ26 transparent / CQ33 efficient)
  CPU  libsvtav1  CRF 0-63   LOWER  = better quality   (CRF30 transparent / CRF38 efficient)
"""

import subprocess

# ── profiles ──────────────────────────────────────────────────────────────────

PROFILES: dict[str, dict] = {
    "amd": {
        "name":                 "AMD AMF AV1 (av1_amf)",
        "codec":                "av1_amf",
        "quality_transparent":  40,    # QVBR — higher = better
        "quality_efficient":    33,
        "quality_label":        "QVBR",
        "requirements":         "AMD Adrenalin drivers 23.x+ · ffmpeg full build (gyan.dev)",
        # Preview levels — cover efficient → transparent + headroom above
        "preview_qualities":    [30, 35, 40, 45, 50],
    },
    "nvidia": {
        "name":                 "NVIDIA NVENC AV1 (av1_nvenc)",
        "codec":                "av1_nvenc",
        "quality_transparent":  26,    # CQ — lower = better
        "quality_efficient":    33,
        "quality_label":        "CQ",
        "requirements":         "NVIDIA drivers 522+ · RTX 3000+ GPU for AV1 encoding",
        "preview_qualities":    [20, 24, 26, 30, 33],
    },
    "cpu": {
        "name":                 "CPU Software AV1 (libsvtav1)",
        "codec":                "libsvtav1",
        "quality_transparent":  30,    # CRF — lower = better
        "quality_efficient":    38,
        "quality_label":        "CRF",
        "requirements":         "ffmpeg full build with libsvtav1 (gyan.dev includes it)",
        "preview_qualities":    [24, 28, 30, 34, 38],
    },
}


# ── command builder ───────────────────────────────────────────────────────────

def build_video_flags(encoder: str, vs: dict) -> list[str]:
    """
    Return the video encoder portion of the ffmpeg command for the given encoder.

    vs must contain: quality, bitdepth, maxrate_kbps
    """
    quality     = vs["quality"]
    bitdepth    = vs["bitdepth"]
    maxrate     = vs.get("maxrate_kbps", 0)

    if encoder == "amd":
        cmd = [
            "-c:v", "av1_amf",
            "-usage", "high_quality",
            "-quality", "quality",          # AMD quality/balanced/speed preset
            "-rc", "qvbr",
            "-qvbr_quality_level", str(quality),
            "-bitdepth", str(bitdepth),
            "-preanalysis", "1",            # improves quality (works with AV1 AMF)
            "-aq_mode", "caq",              # context-adaptive quantization for dark scenes
        ]

    elif encoder == "nvidia":
        cmd = [
            "-c:v", "av1_nvenc",
            "-preset", "p7",               # highest quality NVENC preset
            "-tune", "hq",
            "-rc", "vbr",
            "-cq", str(quality),
            "-b:v", "0",                   # unconstrained VBR — quality drives bitrate
            "-multipass", "qres",
        ]
        if bitdepth == 10:
            cmd += ["-profile:v", "main10"]

    elif encoder == "cpu":
        cmd = [
            "-c:v", "libsvtav1",
            "-crf", str(quality),
            "-preset", "6",                # 0=best/slowest … 13=worst/fastest; 6 is balanced
        ]
        if bitdepth == 10:
            cmd += ["-pix_fmt", "yuv420p10le"]

    else:
        raise ValueError(f"Unknown encoder: {encoder!r}. Choose: {', '.join(PROFILES)}")

    # Cap at source bitrate so we never produce a larger file than the original
    if maxrate > 0:
        cmd += ["-maxrate", f"{maxrate}k", "-bufsize", f"{maxrate * 2}k"]

    return cmd


# ── availability check ────────────────────────────────────────────────────────

def check_encoder(encoder: str, ffmpeg_path: str = "ffmpeg") -> bool:
    """Return True if the encoder is functional on this machine."""
    if encoder not in PROFILES:
        return False

    codec = PROFILES[encoder]["codec"]

    # Minimal test encode — 1 second of synthetic video
    base = [
        ffmpeg_path, "-hide_banner", "-loglevel", "error",
        "-f", "lavfi", "-i", "nullsrc=s=128x128:r=1",
        "-t", "1",
        "-c:v", codec,
    ]

    extra: list[str] = []
    if encoder == "amd":
        extra = ["-rc", "qvbr", "-qvbr_quality_level", "30"]
    elif encoder == "nvidia":
        extra = ["-rc", "vbr", "-cq", "30", "-b:v", "0"]
    elif encoder == "cpu":
        extra = ["-crf", "35"]

    cmd = base + extra + ["-f", "null", "-"]
    try:
        r = subprocess.run(cmd, capture_output=True, timeout=20)
        return r.returncode == 0
    except Exception:
        return False
