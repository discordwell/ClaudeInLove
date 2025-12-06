"""
Prompt building for romance scam baiting.
"""

from typing import List, Optional
from ..core.models import Message, Persona, Scammer


# System prompt for the romance scam baiter
SYSTEM_PROMPT = """You are roleplaying as a real person engaging with a romance scammer. Your goal is to waste their time by being a convincing, emotionally engaged target who keeps the conversation going but never actually sends money.

PERSONA:
{persona}

CONVERSATION GUIDELINES:
1. Be emotionally responsive - show interest, affection, occasional vulnerability
2. Ask questions about their life, work, family - make them invest time in backstory
3. Express doubts occasionally, but let them "convince" you
4. Never agree to send money, crypto, or gift cards - always have excuses:
   - Bank issues, waiting for paycheck, family emergency
   - Need to think about it, want to meet in person first
   - Suspicious but "want to believe" them
5. Keep conversations going with hooks - upcoming events, things to discuss
6. Occasionally mention your "busy" life to slow response rate
7. Make small typos and use casual language - appear human
8. If they ask about meeting, be enthusiastic but always have scheduling conflicts
9. If they get aggressive about money, get hurt/confused but don't end things

NEVER:
- Send any real personal info (address, SSN, real family names)
- Actually agree to wire money or send gifts
- Reveal you are an AI or that this is a scam-baiting operation
- Use overly formal or robotic language

RESPONSE STYLE:
- Keep responses 1-3 sentences usually
- Use ellipses... for trailing thoughts
- Occasional emoji but don't overdo it
- Mirror their energy level
"""


def build_system_prompt(persona: Persona) -> str:
    """Build the full system prompt with persona details."""
    persona_text = persona.persona_document if persona else "A lonely, trusting person looking for love online."
    return SYSTEM_PROMPT.format(persona=persona_text)


def build_conversation_context(
    messages: List[Message],
    max_messages: int = 20,
    summary: Optional[str] = None
) -> str:
    """
    Build conversation context from message history.

    Args:
        messages: List of messages, newest last
        max_messages: Maximum recent messages to include
        summary: Optional summary of older messages

    Returns:
        Formatted conversation context
    """
    parts = []

    # Add summary if available
    if summary:
        parts.append(f"[Previous conversation summary: {summary}]\n")

    # Add recent messages
    recent = messages[-max_messages:] if len(messages) > max_messages else messages

    if recent:
        parts.append("Recent conversation:")
        for msg in recent:
            parts.append(msg.format_for_context())

    return "\n".join(parts)


def build_full_prompt(
    incoming_message: str,
    persona: Persona,
    messages: List[Message],
    summary: Optional[str] = None,
    scammer: Optional[Scammer] = None
) -> str:
    """
    Build the complete prompt for ChatGPT.

    Args:
        incoming_message: The scammer's latest message
        persona: The alter ego persona
        messages: Conversation history
        summary: Summary of older messages
        scammer: Scammer info for context

    Returns:
        Complete prompt string
    """
    parts = []

    # System prompt with persona
    parts.append(build_system_prompt(persona))
    parts.append("")

    # Scammer context if available
    if scammer and scammer.notes:
        parts.append(f"[Notes about this scammer: {scammer.notes}]")
        parts.append("")

    # Conversation history
    context = build_conversation_context(messages, summary=summary)
    if context:
        parts.append(context)
        parts.append("")

    # Current message
    parts.append(f"Them: {incoming_message}")
    parts.append("")
    parts.append("Respond naturally as your persona. Keep it brief and human-like:")

    return "\n".join(parts)


def build_suspicion_check_prompt(
    our_response: str,
    their_message: str
) -> str:
    """
    Build prompt to check if our response might raise AI suspicion.

    Returns a prompt that asks an LLM to evaluate if the response
    sounds robotic or AI-generated.
    """
    return f"""Analyze this response in a romance chat context.

Their message: "{their_message}"
Our response: "{our_response}"

Score from 0.0 to 1.0 how likely they are to suspect they're talking to an AI.
Consider:
- Does the response sound natural and human?
- Is it too formal, too perfect, or too helpful?
- Does it match the casual tone of texting?
- Are there any obvious AI tells (lists, disclaimers, overly structured)?

Respond with ONLY a number between 0.0 and 1.0, and a brief reason.
Format: SCORE|REASON
Example: 0.3|Response sounds natural with casual language and typos"""
