"""Pydantic schemas for the dev module."""

from __future__ import annotations

from src.app.shared.schemas import ORMModel


class DemoLogin(ORMModel):
    """One row of the dev-only "Test logins" dropdown on the login page."""

    label: str
    identifier: str
    password: str
    org_slug: str
    org_name: str
