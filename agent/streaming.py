"""Helpers for streaming chat replies to the widget.

The stream is newline-delimited JSON: one event object per line.
  {"type": "delta", "text": "..."}                    more reply text
  {"type": "done", "reply": "...", "escalate": true}  final, cleaned reply
  {"type": "error", "error": "..."}                   the reply failed
The "done" reply is the source of truth; the widget replaces whatever it
built from the deltas with it.
"""

import json

ESCALATE_TAG = "[ESCALATE]"


def event(kind: str, **fields) -> bytes:
    return (json.dumps({"type": kind, **fields}) + "\n").encode()


class EscalationTagFilter:
    """Passes streamed text through, minus the [ESCALATE] tag.

    The tag can arrive split across chunks ("[ESC" then "ALATE]"), so any
    trailing text that could be the start of it is held back until the next
    chunk shows whether it is.
    """

    def __init__(self):
        self._pending = ""
        self.escalated = False

    def feed(self, text: str) -> str:
        buffer = self._pending + text
        if ESCALATE_TAG in buffer:
            self.escalated = True
            buffer = buffer.replace(ESCALATE_TAG, "")
        hold = 0
        for size in range(min(len(buffer), len(ESCALATE_TAG) - 1), 0, -1):
            if ESCALATE_TAG.startswith(buffer[-size:]):
                hold = size
                break
        self._pending = buffer[len(buffer) - hold :] if hold else ""
        return buffer[: len(buffer) - hold]

    def flush(self) -> str:
        """Whatever was held back, once the stream has ended without the tag."""
        rest, self._pending = self._pending, ""
        return rest
