"""Open + click tracking, opt-out handling, compliance footer.

Three pure transforms in this package (`pixel`, `link_rewriter`,
`footer`) compose against an outbound `body_html` before MIME
assembly. The HMAC-signed `tokens.py` encoder produces opaque URL
fragments the public router decodes; the router records the open or
click in `email_message_opens` / `email_message_clicks` and serves
the appropriate response (1×1 GIF / 302 redirect / unsubscribe page).
"""
