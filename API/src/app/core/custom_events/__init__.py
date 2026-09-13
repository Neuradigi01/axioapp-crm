"""Custom events — org-defined named triggers.

Admin creates events (``visa_expired``, ``membership_ended``, ...) in
Settings → Custom Events. Staff fires them from a contact's detail page
(or a workflow fires them programmatically). Each fire publishes on the
bus as ``custom.<event_key>`` so any workflow whose trigger matches
runs the mapped template.
"""
