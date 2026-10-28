"""Stripe webhook handling — Step 13.

Sub-step 13.a (this commit) ships the endpoint, signature
verification, and the dedup ledger. Sub-step 13.b adds the per-event
handlers under `handlers/`; sub-step 13.c adds the in-app invoice
list endpoint.
"""
