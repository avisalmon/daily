"""Delivery dispatcher — routes the rendered digest to configured channels."""

from typing import Any

from . import email, file_out

CHANNELS = {
    "file": file_out.send,
    "email": email.send,
}


def send(digest: str, cfg: dict[str, Any]) -> None:
    for channel in cfg.get("delivery", {}).get("channels", ["file"]):
        handler = CHANNELS.get(channel)
        if handler is None:
            continue
        handler(digest, cfg)
