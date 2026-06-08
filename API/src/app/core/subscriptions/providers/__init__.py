"""Concrete payment-provider implementations.

Each module here implements `PaymentProvider` for one vendor. v1 ships
`StripeProvider`; a future Razorpay or Paddle adapter lands as a
sibling module without touching `payment_provider.py` or its consumers.
"""
