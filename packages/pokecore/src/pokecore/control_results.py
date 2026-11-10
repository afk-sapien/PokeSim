"""Additive, serializable status fields for shared controller operations."""


def control_status(kind, reason, *, completed, settled, frames, inputs):
    """Completion and a resting interface are separate facts. Inputs may be waits."""
    return {'kind': kind, 'stop_reason': reason, 'completed': bool(completed),
            'settled': bool(settled), 'frames': frames, 'inputs': inputs}
