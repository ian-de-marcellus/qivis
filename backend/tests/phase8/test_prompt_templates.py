"""Contract tests for prompt template rendering."""

from qivis.generation.templates import render_prompt, render_chatml, render_alpaca, render_llama3


MESSAGES = [
    {"role": "user", "content": "Hello"},
    {"role": "assistant", "content": "Hi there!"},
    {"role": "user", "content": "How are you?"},
]

SYSTEM = "You are a helpful assistant."


class TestChatML:
    def test_renders_system_and_messages(self):
        prompt, stops = render_chatml(MESSAGES, SYSTEM)
        assert "<|im_start|>system\n" in prompt
        assert SYSTEM in prompt
        assert "<|im_start|>user\nHello<|im_end|>" in prompt
        assert "<|im_start|>assistant\nHi there!<|im_end|>" in prompt
        assert "<|im_start|>user\nHow are you?<|im_end|>" in prompt
        # Ends with assistant turn open for completion
        assert prompt.endswith("<|im_start|>assistant\n")

    def test_stop_tokens(self):
        _, stops = render_chatml(MESSAGES, SYSTEM)
        assert "<|im_end|>" in stops

    def test_no_system_prompt(self):
        prompt, _ = render_chatml(MESSAGES, None)
        assert "system" not in prompt.lower().split("user")[0] or "<|im_start|>system" not in prompt
        assert "<|im_start|>user\nHello" in prompt


class TestAlpaca:
    def test_renders_with_system(self):
        prompt, stops = render_alpaca(MESSAGES, SYSTEM)
        assert "### Instruction:" in prompt
        assert SYSTEM in prompt
        assert "### Input:" in prompt or "### Response:" in prompt
        # Ends ready for model response
        assert prompt.rstrip().endswith("### Response:")

    def test_stop_tokens(self):
        _, stops = render_alpaca(MESSAGES, SYSTEM)
        assert any("###" in s for s in stops)


class TestLlama3:
    def test_renders_system_and_messages(self):
        prompt, stops = render_llama3(MESSAGES, SYSTEM)
        assert "<|begin_of_text|>" in prompt
        assert "<|start_header_id|>system<|end_header_id|>" in prompt
        assert SYSTEM in prompt
        assert "<|start_header_id|>user<|end_header_id|>" in prompt
        assert "Hello" in prompt
        assert "<|start_header_id|>assistant<|end_header_id|>" in prompt
        # Ends with assistant header for completion
        assert prompt.endswith("<|start_header_id|>assistant<|end_header_id|>\n\n")

    def test_stop_tokens(self):
        _, stops = render_llama3(MESSAGES, SYSTEM)
        assert "<|eot_id|>" in stops
        assert "<|start_header_id|>" in stops

    def test_no_system_prompt(self):
        prompt, _ = render_llama3(MESSAGES, None)
        assert "<|start_header_id|>system<|end_header_id|>" not in prompt
        assert "<|start_header_id|>user<|end_header_id|>" in prompt


class TestRenderPrompt:
    def test_known_template(self):
        prompt, stops = render_prompt("chatml", MESSAGES, SYSTEM)
        assert "<|im_start|>" in prompt

    def test_unknown_template_falls_back_to_raw(self):
        prompt, stops = render_prompt("nonexistent_template", MESSAGES, SYSTEM)
        assert "Hello" in prompt
        assert "<|im_start|>" not in prompt
        assert stops == []
