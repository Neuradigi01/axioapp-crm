"""Slack integration — minimal incoming-webhook client.

v1 ships only :func:`post_message` from :mod:`core.integrations.slack.client`
— the smallest surface needed for the Step-7 workflow ``send.slack``
action handler. A future step adds a Settings → Integrations → Slack
page that stores the webhook URL on ``tbl_integrations`` so workflow
nodes can reference the org's default without re-pasting it.
"""
from src.app.core.integrations.slack.client import (
    SlackError,
    post_message,
)


__all__ = ["SlackError", "post_message"]
