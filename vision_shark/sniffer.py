from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable

from .domain import Frame


def sniffer_view(frames: Iterable[Frame], changed_only: bool = False, changed_within_ms: float = 1000.0) -> dict:
    if changed_within_ms < 0:
        raise ValueError('changed_within_ms must be non-negative')
    rows = sorted((f for f in frames if not f.error and not f.rtr), key=lambda f: int(f.ts_ns))
    groups = defaultdict(list)
    for frame in rows:
        groups[(frame.bus, int(frame.arbitration_id), bool(frame.extended), bool(frame.can_fd))].append(frame)
    newest = max((int(f.ts_ns) for f in rows), default=0)
    messages = []
    for key, items in sorted(groups.items()):
        width = max((len(bytes.fromhex(f.data)) for f in items), default=0)
        previous = [None] * width
        changed_at = [None] * width
        changes = [0] * width
        for frame in items:
            raw = bytes.fromhex(frame.data)
            for i in range(width):
                value = raw[i] if i < len(raw) else None
                if previous[i] is None:
                    previous[i] = value
                    changed_at[i] = int(frame.ts_ns)
                elif value != previous[i]:
                    previous[i] = value
                    changed_at[i] = int(frame.ts_ns)
                    changes[i] += 1
        byte_state = []
        recent = False
        for i, value in enumerate(previous):
            age = None if changed_at[i] is None else max(0.0, (newest - int(changed_at[i])) / 1e6)
            is_recent = bool(changes[i] and age is not None and age <= changed_within_ms)
            recent = recent or is_recent
            byte_state.append({'index': i, 'value': None if value is None else f'{value:02X}', 'change_count': changes[i], 'last_change_age_ms': None if age is None else round(age, 3), 'changed_recently': is_recent})
        if changed_only and not recent:
            continue
        bus, arbitration_id, extended, can_fd = key
        messages.append({'bus': bus, 'arbitration_id': arbitration_id, 'id_hex': f'0x{arbitration_id:X}', 'extended': extended, 'can_fd': can_fd, 'count': len(items), 'latest_ts_ns': int(items[-1].ts_ns), 'latest_data': items[-1].data.upper(), 'bytes': byte_state})
    return {'frame_count': len(rows), 'message_count': len(messages), 'newest_ts_ns': newest or None, 'changed_only': bool(changed_only), 'changed_within_ms': float(changed_within_ms), 'messages': messages, 'authority': 'passive_observation_only'}
