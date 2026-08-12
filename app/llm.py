"""
Wraps a single streaming call to Groq for one turn of conversation.

Groq's API is intentionally OpenAI-compatible -- same request/response
shape as OpenAI's chat completions API, just pointed at Groq's own
infrastructure. This is a common pattern across the industry (many
open-model hosts do this), so the client code here would look almost
identical if you swapped in OpenAI itself later.

Unlike DeepgramASR, this class holds no persistent connection -- each call
to stream_reply() is a fresh, independent streaming HTTP request, so one
instance is shared across every session and request in the app.

Design note: the system prompt exists specifically because this text is
headed for TTS next, not just a chat window. Long paragraphs, markdown,
and bullet points all sound broken when read aloud, so we steer the model
toward short, plain, spoken-style sentences up front.
"""

import os

from groq import AsyncGroq

# gpt-oss-20b is Groq's fast/small model tier -- optimized for low latency,
# which matters more than maximum reasoning depth for a voice assistant.
DEFAULT_MODEL = "openai/gpt-oss-20b"

SYSTEM_PROMPT = (
    "You are a helpful, concise voice assistant. Your replies are converted "
    "to speech and read aloud, so: keep answers short and conversational "
    "(usually 1-3 sentences, more only if the user clearly wants detail); "
    "never use markdown, bullet points, headers, or code blocks -- write in "
    "plain spoken sentences; avoid abbreviations or symbols that sound "
    "awkward when spoken (say 'for example' instead of 'e.g.')."
)


class GroqReasoner:
    def __init__(self, api_key: str | None = None, model: str = DEFAULT_MODEL):
        self.api_key = api_key or os.environ.get("GROQ_API_KEY")
        if not self.api_key:
            raise RuntimeError(
                "GROQ_API_KEY is not set. Add it to a .env file in the project root."
            )
        self.client = AsyncGroq(api_key=self.api_key)
        self.model = model

    async def stream_reply(self, history: list[dict], on_token=None) -> str:
        """
        Streams a reply given the full conversation so far (a list of
        {"role": "user"|"assistant", "content": "..."} dicts). Calls
        on_token(text_delta) as each piece of text arrives, and returns the
        complete assembled response once the stream ends.
        """
        messages = [{"role": "system", "content": SYSTEM_PROMPT}, *history]

        full_text = ""
        stream = await self.client.chat.completions.create(
            model=self.model,
            messages=messages,
            max_tokens=512,
            stream=True,
        )

        async for chunk in stream:
            delta = chunk.choices[0].delta.content
            if delta:
                full_text += delta
                if on_token is not None:
                    await on_token(delta)

        return full_text
