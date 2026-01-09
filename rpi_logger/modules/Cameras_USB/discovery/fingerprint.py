import hashlib
from typing import Any

from ..core.state import CameraCapabilities, CameraFingerprint


def compute_fingerprint(vid_pid: str, capabilities: CameraCapabilities) -> CameraFingerprint:
    mode_signatures = []
    for mode in capabilities.modes:
        size = mode.get("size", (0, 0))
        fps = mode.get("fps", 0)
        pixel_format = mode.get("pixel_format", "")
        sig = f"{size[0]}x{size[1]}@{fps:.1f}:{pixel_format}"
        mode_signatures.append(sig)

    modes_str = "|".join(sorted(mode_signatures))
    controls_str = "|".join(sorted(capabilities.controls.keys()))

    combined = f"{modes_str}:{controls_str}"
    capability_hash = hashlib.sha256(combined.encode()).hexdigest()[:16]

    return CameraFingerprint(
        vid_pid=vid_pid,
        capability_hash=capability_hash,
    )


def fingerprint_to_string(fingerprint: CameraFingerprint) -> str:
    return f"{fingerprint.vid_pid}:{fingerprint.capability_hash}"


def fingerprint_from_string(fp_str: str) -> CameraFingerprint | None:
    parts = fp_str.split(":", 2)
    if len(parts) >= 3:
        vid_pid = f"{parts[0]}:{parts[1]}"
        capability_hash = parts[2]
        return CameraFingerprint(vid_pid=vid_pid, capability_hash=capability_hash)
    elif len(parts) == 2:
        return CameraFingerprint(vid_pid=parts[0], capability_hash=parts[1])
    return None


def fingerprints_match(
    stored: CameraFingerprint | str,
    current: CameraFingerprint,
) -> bool:
    if isinstance(stored, str):
        stored_fp = fingerprint_from_string(stored)
        if not stored_fp:
            return False
        stored = stored_fp

    if stored.vid_pid and current.vid_pid:
        if stored.vid_pid != current.vid_pid:
            return False

    return stored.capability_hash == current.capability_hash


def verify_fingerprint(
    cached_fingerprint: str,
    vid_pid: str,
    capabilities: CameraCapabilities,
) -> tuple[bool, CameraFingerprint]:
    current = compute_fingerprint(vid_pid, capabilities)
    match = fingerprints_match(cached_fingerprint, current)
    return match, current
