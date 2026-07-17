import json

from llm_proxy.tool_call_parser import ToolCallStreamParser


class TestBasicToolCallDetection:
    def test_simple_tool_call_in_one_chunk(self):
        """Complete <tool_call>...</tool_call> arrives in a single feed()."""
        parser = ToolCallStreamParser()
        text = '<tool_call>\n{"name": "Bash", "arguments": {"command": "ls"}}\n</tool_call>'
        actions = parser.feed(text)
        assert len(actions) == 1
        assert actions[0][0] == "tool_call"
        assert actions[0][1].name == "Bash"
        assert json.loads(actions[0][1].arguments) == {"command": "ls"}
        assert parser.has_tool_calls is True

    def test_tool_call_split_across_chunks(self):
        """<tool_call> tag arrives across multiple feed() calls."""
        parser = ToolCallStreamParser()
        fragments = [
            "<",
            "tool",
            "_call",
            ">\n",
            '{"name":',
            ' "Bash",',
            ' "arguments":',
            ' {"command": "ls"}}',
            "\n</",
            "tool_call>",
        ]
        all_actions = []
        for frag in fragments:
            all_actions.extend(parser.feed(frag))
        tool_actions = [a for a in all_actions if a[0] == "tool_call"]
        assert len(tool_actions) == 1
        assert tool_actions[0][1].name == "Bash"

    def test_text_before_tool_call(self):
        """Normal text followed by a tool call."""
        parser = ToolCallStreamParser()
        actions = parser.feed("Here is the result:\n\n")
        assert len(actions) == 1
        assert actions[0] == ("content", "Here is the result:\n\n")

        actions2 = parser.feed(
            '<tool_call>\n{"name": "Bash", "arguments": {"command": "ls"}}\n</tool_call>'
        )
        tool_actions = [a for a in actions2 if a[0] == "tool_call"]
        assert len(tool_actions) == 1

    def test_text_with_angle_bracket_not_tool_call(self):
        """A '<' in normal text should not trigger false buffering."""
        parser = ToolCallStreamParser()
        actions = parser.feed("if x < 5 then do something")
        assert len(actions) == 1
        assert actions[0] == ("content", "if x < 5 then do something")

    def test_text_after_tool_call(self):
        """Text after a closing tool_call tag."""
        parser = ToolCallStreamParser()
        text = '<tool_call>\n{"name": "Bash", "arguments": {}}\n</tool_call>\n\nDone!'
        actions = parser.feed(text)
        tool_actions = [a for a in actions if a[0] == "tool_call"]
        content_actions = [a for a in actions if a[0] == "content"]
        assert len(tool_actions) == 1
        assert any("Done!" in a[1] for a in content_actions)


class TestMultipleToolCalls:
    def test_two_tool_calls_in_sequence(self):
        parser = ToolCallStreamParser()
        text = (
            '<tool_call>\n{"name": "Bash", "arguments": {"command": "ls"}}\n</tool_call>\n'
            '<tool_call>\n{"name": "Bash", "arguments": {"command": "pwd"}}\n</tool_call>'
        )
        actions = parser.feed(text)
        tool_actions = [a for a in actions if a[0] == "tool_call"]
        assert len(tool_actions) == 2
        assert json.loads(tool_actions[0][1].arguments) == {"command": "ls"}
        assert json.loads(tool_actions[1][1].arguments) == {"command": "pwd"}

    def test_tool_call_count_tracks_correctly(self):
        parser = ToolCallStreamParser()
        parser.feed(
            '<tool_call>\n{"name": "A", "arguments": {}}\n</tool_call>'
        )
        assert parser._tool_call_count == 1
        parser.feed(
            '<tool_call>\n{"name": "B", "arguments": {}}\n</tool_call>'
        )
        assert parser._tool_call_count == 2


class TestEdgeCases:
    def test_malformed_json_emitted_as_text(self):
        parser = ToolCallStreamParser()
        text = "<tool_call>\nnot valid json\n</tool_call>"
        actions = parser.feed(text)
        assert len(actions) == 1
        assert actions[0][0] == "content"
        assert "<tool_call>" in actions[0][1]
        assert parser.has_tool_calls is False

    def test_unclosed_tag_flushed_as_text(self):
        parser = ToolCallStreamParser()
        parser.feed("<tool_call>\n{partial json")
        actions = parser.flush()
        assert len(actions) == 1
        assert actions[0][0] == "content"

    def test_no_tool_calls_means_has_tool_calls_false(self):
        parser = ToolCallStreamParser()
        parser.feed("Just regular text, nothing special.")
        assert parser.has_tool_calls is False

    def test_partial_opening_tag_at_chunk_boundary(self):
        """'<tool' at end of one chunk, '_call>' at start of next."""
        parser = ToolCallStreamParser()
        actions1 = parser.feed("hello <tool")
        content_actions = [a for a in actions1 if a[0] == "content"]
        assert any("hello" in a[1] for a in content_actions)

        actions2 = parser.feed(
            '_call>\n{"name": "X", "arguments": {}}\n</tool_call>'
        )
        tool_actions = [a for a in actions2 if a[0] == "tool_call"]
        assert len(tool_actions) == 1
        assert tool_actions[0][1].name == "X"

    def test_arguments_as_string(self):
        """Tool call where arguments is already a JSON string."""
        parser = ToolCallStreamParser()
        text = '<tool_call>\n{"name": "Write", "arguments": {"path": "/tmp/test"}}\n</tool_call>'
        actions = parser.feed(text)
        assert actions[0][0] == "tool_call"
        assert actions[0][1].name == "Write"
        parsed_args = json.loads(actions[0][1].arguments)
        assert parsed_args["path"] == "/tmp/test"

    def test_missing_name_emitted_as_text(self):
        """Tool call JSON without a name field is malformed."""
        parser = ToolCallStreamParser()
        text = '<tool_call>\n{"arguments": {"x": 1}}\n</tool_call>'
        actions = parser.feed(text)
        assert actions[0][0] == "content"
        assert parser.has_tool_calls is False

    def test_extra_trailing_braces_recovered(self):
        """GPT-5.2 pattern: extra closing braces like '}}}'."""
        parser = ToolCallStreamParser()
        text = '<tool_call>\n{"name":"read","arguments":{"filePath":"/tmp/test.md"}}}\n</tool_call>'
        actions = parser.feed(text)
        assert len(actions) == 1
        assert actions[0][0] == "tool_call"
        assert actions[0][1].name == "read"
        parsed_args = json.loads(actions[0][1].arguments)
        assert parsed_args["filePath"] == "/tmp/test.md"
        assert parser.has_tool_calls is True

    def test_two_extra_trailing_braces_recovered(self):
        """Even more extra braces should still parse."""
        parser = ToolCallStreamParser()
        text = '<tool_call>\n{"name":"Bash","arguments":{"command":"ls"}}}}}\n</tool_call>'
        # 3 extra braces — we strip up to 3
        actions = parser.feed(text)
        assert len(actions) == 1
        assert actions[0][0] == "tool_call"
        assert actions[0][1].name == "Bash"


class TestFlush:
    def test_flush_pending_tag(self):
        parser = ToolCallStreamParser()
        parser.feed("<tool")
        actions = parser.flush()
        assert len(actions) == 1
        assert actions[0] == ("content", "<tool")

    def test_flush_when_empty(self):
        parser = ToolCallStreamParser()
        actions = parser.flush()
        assert actions == []

    def test_flush_after_complete_tool_call(self):
        """Flush after a fully parsed tool call should return nothing."""
        parser = ToolCallStreamParser()
        parser.feed(
            '<tool_call>\n{"name": "Bash", "arguments": {}}\n</tool_call>'
        )
        actions = parser.flush()
        assert actions == []


class TestToolCallId:
    def test_generate_unique_ids(self):
        parser = ToolCallStreamParser()
        id1 = parser.generate_tool_call_id()
        id2 = parser.generate_tool_call_id()
        assert id1.startswith("call_")
        assert id2.startswith("call_")
        assert id1 != id2
