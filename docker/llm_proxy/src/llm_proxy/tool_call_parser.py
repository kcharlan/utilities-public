"""Stateful parser that detects <tool_call> XML blocks in streaming text
and converts them to structured OpenAI tool_calls format.

Used by the T3ChatAdapter to translate model text output into tool calls
that OpenCode can execute.
"""

import json
import logging
from dataclasses import dataclass
from uuid import uuid4

logger = logging.getLogger(__name__)

OPEN_TAG = "<tool_call>"
CLOSE_TAG = "</tool_call>"


@dataclass
class ParsedToolCall:
    """A successfully parsed tool call extracted from XML tags."""

    name: str
    arguments: str  # JSON string of the arguments dict


class ToolCallStreamParser:
    """Detects <tool_call> XML blocks in streaming text fragments.

    Receives text fragments one at a time via feed(). Returns a list of
    actions for each fragment:
      - ("content", text)          -- emit as normal content delta
      - ("tool_call", ParsedToolCall)  -- emit as structured tool_call delta

    Handles partial tags across chunk boundaries, multiple tool calls,
    malformed JSON (falls back to text), and normal '<' characters.
    """

    def __init__(self):
        self._buffer: str = ""
        self._in_tool_call: bool = False
        self._tool_call_count: int = 0
        self._pending_tag: str = ""

    def feed(self, text: str) -> list[tuple[str, str | ParsedToolCall]]:
        """Process a text fragment and return actions."""
        actions: list[tuple[str, str | ParsedToolCall]] = []

        if self._in_tool_call:
            self._buffer += text
            close_idx = self._buffer.find(CLOSE_TAG)
            if close_idx != -1:
                json_str = self._buffer[:close_idx].strip()
                remaining = self._buffer[close_idx + len(CLOSE_TAG) :]
                self._buffer = ""
                self._in_tool_call = False

                tc = self._try_parse_tool_call(json_str)
                if tc is not None:
                    actions.append(("tool_call", tc))
                else:
                    # Malformed JSON -- emit as regular text
                    full_text = f"{OPEN_TAG}\n{json_str}\n{CLOSE_TAG}"
                    actions.append(("content", full_text))

                # Process any text after the closing tag
                if remaining.strip():
                    actions.extend(self.feed(remaining))
            # else: closing tag not yet found, keep buffering
            return actions

        # Not in a tool call -- look for opening tag
        combined = self._pending_tag + text
        self._pending_tag = ""

        i = 0
        content_start = 0

        while i < len(combined):
            if combined[i] == "<":
                remaining = combined[i:]

                if remaining.startswith(OPEN_TAG):
                    # Full opening tag found
                    if i > content_start:
                        actions.append(("content", combined[content_start:i]))
                    self._in_tool_call = True
                    self._buffer = ""
                    after_tag = remaining[len(OPEN_TAG) :]
                    if after_tag:
                        actions.extend(self.feed(after_tag))
                    return actions

                elif OPEN_TAG.startswith(remaining):
                    # Partial match -- could be start of <tool_call>
                    if i > content_start:
                        actions.append(("content", combined[content_start:i]))
                    self._pending_tag = remaining
                    return actions

                else:
                    # Not a tool_call tag, just a regular '<'
                    i += 1
            else:
                i += 1

        # No tag found -- emit all as content
        if content_start < len(combined):
            actions.append(("content", combined[content_start:]))
        return actions

    def flush(self) -> list[tuple[str, str | ParsedToolCall]]:
        """Called at end of stream. Returns any remaining buffered content."""
        actions: list[tuple[str, str | ParsedToolCall]] = []
        if self._pending_tag:
            actions.append(("content", self._pending_tag))
            self._pending_tag = ""
        if self._in_tool_call and self._buffer:
            logger.warning("Stream ended inside unclosed <tool_call> tag")
            actions.append(("content", f"{OPEN_TAG}\n{self._buffer}"))
            self._buffer = ""
            self._in_tool_call = False
        return actions

    @property
    def has_tool_calls(self) -> bool:
        """True if any tool calls were successfully parsed during this stream."""
        return self._tool_call_count > 0

    def generate_tool_call_id(self) -> str:
        """Generate a unique tool call ID like 'call_abc123'."""
        return f"call_{uuid4().hex[:24]}"

    def _try_parse_tool_call(self, json_str: str) -> ParsedToolCall | None:
        """Attempt to parse a tool call JSON string.

        Handles common model quirks like trailing extra braces
        (e.g. '{"name":"read","arguments":{"path":"/tmp"}}}').
        """
        parsed = self._lenient_json_loads(json_str)
        if parsed is None:
            return None

        name = parsed.get("name", "")
        if not name:
            logger.warning("Tool call JSON missing 'name' field")
            return None
        arguments = parsed.get("arguments", parsed.get("parameters", {}))
        if isinstance(arguments, dict):
            arguments = json.dumps(arguments)
        elif not isinstance(arguments, str):
            arguments = json.dumps(arguments)
        self._tool_call_count += 1
        return ParsedToolCall(name=name, arguments=arguments)

    @staticmethod
    def _lenient_json_loads(s: str) -> dict | None:
        """Parse JSON, tolerating trailing extra braces.

        Some models (notably GPT-5.2) emit malformed JSON like
        '{"name":"x","arguments":{"a":"b"}}}' with extra closing braces.
        We try strict parsing first, then progressively strip trailing '}'
        characters until it parses or we give up.
        """
        s = s.strip()
        try:
            return json.loads(s)
        except (json.JSONDecodeError, TypeError):
            pass

        # Try stripping trailing braces (up to 3 extra)
        for _ in range(3):
            if s.endswith("}"):
                s = s[:-1]
                try:
                    result = json.loads(s)
                    if isinstance(result, dict):
                        logger.debug("Recovered tool call JSON after stripping trailing brace(s)")
                        return result
                except (json.JSONDecodeError, TypeError):
                    continue

        logger.warning("Failed to parse tool call JSON even after brace cleanup")
        return None
