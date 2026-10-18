"""Lossless CAN/CAN-FD frame export when no DBC is supplied."""

from __future__ import annotations

import math
from pathlib import Path

from . import converter as core


def export_frames(blf: Path, target: Path) -> float:
    frames = []
    with core.can.BLFReader(blf) as reader:
        for frame in reader:
            if not math.isfinite(frame.timestamp):
                raise RuntimeError(f"BLF contains a non-finite timestamp: {blf}")
            if len(frame.data) > 64:
                raise RuntimeError(f"CAN payload exceeds 64 bytes: {blf}")
            frames.append(frame)
    if not frames:
        raise RuntimeError(f"BLF contains no CAN frames: {blf}")
    origin = min(frame.timestamp for frame in frames)
    payload = core.np.zeros((len(frames), 64), dtype=core.np.uint8)
    for index, frame in enumerate(frames):
        payload[index, : len(frame.data)] = list(frame.data)
    fields = {
        "Time": core.np.asarray(
            [frame.timestamp - origin for frame in frames], dtype=core.np.float64
        ),
        "Timestamp": core.np.asarray([frame.timestamp for frame in frames], dtype=core.np.float64),
        "ID": core.np.asarray([frame.arbitration_id for frame in frames], dtype=core.np.uint32),
        "Channel": core.np.asarray(
            [frame.channel if frame.channel is not None else -1 for frame in frames],
            dtype=core.np.int32,
        ),
        "DLC": core.np.asarray([frame.dlc for frame in frames], dtype=core.np.uint8),
        "Length": core.np.asarray([len(frame.data) for frame in frames], dtype=core.np.uint8),
        "Data": payload,
    }
    for label, attribute in (
        ("Extended", "is_extended_id"),
        ("FD", "is_fd"),
        ("Remote", "is_remote_frame"),
        ("Error", "is_error_frame"),
        ("BRS", "bitrate_switch"),
        ("ESI", "error_state_indicator"),
        ("Rx", "is_rx"),
    ):
        fields[label] = core.np.asarray(
            [getattr(frame, attribute) for frame in frames], dtype=core.np.bool_
        )
    core.savemat(
        target, {"Frames": fields}, do_compression=True, long_field_names=True, oned_as="column"
    )
    core.log(f"  Frames: {len(frames)} CAN/CAN-FD frames -> {target}")
    return max(core.MIN_FALLBACK_DURATION_S, max(frame.timestamp for frame in frames) - origin)
