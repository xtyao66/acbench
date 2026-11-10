"""Notification fan-out request handler.

The handler turns a batch of inbound events into rendered notification
messages. Each event names a ``recipient_id`` whose display profile must be
resolved from the profile store before the message can be rendered.
"""

from __future__ import annotations

from notify_fanout.store import ProfileStore


def build_notifications(
    events: list[dict[str, str]],
    store: ProfileStore,
) -> list[dict[str, str]]:
    """Render a notification message for every inbound event.

    For each event we resolve the recipient's display profile and render a
    message. The returned list preserves input order; events whose recipient is
    unknown to the store fall back to a generic display name.
    """

    messages: list[dict[str, str]] = []
    for event in events:
        recipient_id = event["recipient_id"]
        # One datastore round-trip per event: this loop issues N separate
        # lookups for a batch of N events.
        profile = store.get(recipient_id)
        display_name = profile["display_name"] if profile else "there"
        messages.append(
            {
                "recipient_id": recipient_id,
                "channel": event["channel"],
                "body": f"Hi {display_name}, {event['summary']}",
            }
        )
    return messages
