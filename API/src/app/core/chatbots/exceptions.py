"""Chatbots module exceptions.

Kept in a leaf module so both :mod:`graph` and :mod:`service` can
import from here without pulling in the DAL / models chain.
"""

from __future__ import annotations


class ChatbotError(Exception):
    """Base for all chatbot module exceptions."""


class InvalidGraph(ChatbotError):
    """Graph fails a semantic check in
    :func:`core.chatbots.graph.validate_graph` (cycle, unknown node
    type, connect-flow chain too deep, etc). Router turns this into
    a 422 with the exception's message as the reason."""


class InvalidSaveTarget(ChatbotError):
    """A Question / Set-Custom-Field node's ``save_to`` refers to a
    field that is not bot-writable, does not exist, or collides with
    a system column name. 422."""


class ChatbotVersionConflict(ChatbotError):
    """``ChatbotUpdate.expected_version`` did not match the current
    ``tbl_chatbots.version_number``. Another operator saved between
    the caller's read and their write. 409."""


class ChatbotNotFound(ChatbotError):
    """No bot with the given id in the requested org. 404."""


class NodeNotAvailable(ChatbotError):
    """A node type is present in the palette but its runtime is not
    yet configured (e.g. WA Commerce catalog / product nodes without
    a Meta Commerce catalog configured). Handler returns an errored
    NodeResult with this reason; engine cancels the run."""
