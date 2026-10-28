"""Core AI module — agent integrations across channels.

Today only the WhatsApp surface (whatsapp-platform-upgrade Step 19) is
wired. Future steps will add cross-channel AI (SMS / email / web chat)
under the same module. The intentional split:

* ``whatsapp_integration.py`` carries the channel-specific glue —
  conversation history shape, handover heuristics, system-prompt
  composition.
* The LLM call itself is a single function (``_invoke_llm``) inside
  ``whatsapp_integration.py`` — swap that one function out to plug in
  OpenAI / Anthropic / Gemini / a self-hosted model.
"""
