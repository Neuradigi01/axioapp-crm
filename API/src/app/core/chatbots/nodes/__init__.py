"""Chatbot node handlers (``tasks/chatbot-builder`` Steps 7-10).

Each ``*.py`` in this package registers one node type against
:mod:`core.chatbots.engine`'s ``NODE_REGISTRY`` at module import
time. Side-effect import from here ensures every handler is wired
before the first bus event fires.

Step 7 (this module load):
  * ``text_button``, ``media_button``, ``list``, ``template``
  * commerce stubs: ``catalog_message``, ``single_product``, ``multi_product``

Steps 8-10 add: ``ask_question``, ``ask_address``, ``ask_location``,
``ask_media``, ``condition``, ``delay``, ``add_tag``,
``set_custom_field``, ``api_request``, ``connect_flow``,
``handoff_to_human``, ``create_lead``, ``book_appointment``,
``create_task``, ``single_ai_message``, ``assign_ai_assistant``.
"""

from __future__ import annotations

# Side-effect imports — each module calls ``engine.register_node``
# at its bottom, so importing the package registers everything.
from src.app.core.chatbots.nodes import (  # noqa: F401
    add_tag,
    api_request,
    ask_address,
    ask_location,
    ask_media,
    ask_question,
    assign_ai_assistant,
    book_appointment,
    catalog_message,
    condition,
    connect_flow,
    create_lead,
    create_task,
    delay,
    end_bot,
    handoff_to_human,
    list as _list_node,
    media_button,
    multi_product,
    set_custom_field,
    single_ai_message,
    single_product,
    template,
    text_button,
)
