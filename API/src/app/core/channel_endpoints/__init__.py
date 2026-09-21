"""Channel endpoints — unified inbound-endpoint abstraction.

One row in :class:`ChannelEndpoint` per addressable inbound channel
(SMTP reply-capture, OAuth mailbox, Mailgun forwarded address, future
custom-domain inbound). Per-channel detail rows live in sibling tables
(:class:`EmailEndpointDetails` for email).

Track ``email-endpoint-abstraction``. See ``tasks/email-endpoint-abstraction/``.
"""
