"""Contract tests for LogprobNormalizer.from_llamacpp() and from_openai_completion()."""

import math

from qivis.providers.base import LogprobNormalizer


class TestFromLlamaCpp:
    def test_converts_linear_prob_to_logprob(self):
        data = [
            {
                "content": "Hello",
                "probs": [
                    {"tok_str": "Hello", "prob": 0.85},
                    {"tok_str": "Hi", "prob": 0.08},
                    {"tok_str": "Hey", "prob": 0.03},
                ],
            }
        ]
        result = LogprobNormalizer.from_llamacpp(data)
        assert result is not None
        assert len(result.tokens) == 1
        token = result.tokens[0]
        assert token.token == "Hello"
        assert abs(token.logprob - math.log(0.85)) < 1e-6
        assert abs(token.linear_prob - 0.85) < 1e-6

    def test_alternatives_exclude_chosen(self):
        data = [
            {
                "content": "the",
                "probs": [
                    {"tok_str": "the", "prob": 0.7},
                    {"tok_str": "a", "prob": 0.2},
                    {"tok_str": "an", "prob": 0.05},
                ],
            }
        ]
        result = LogprobNormalizer.from_llamacpp(data)
        assert result is not None
        alts = result.tokens[0].top_alternatives
        assert len(alts) == 2
        assert alts[0].token == "a"
        assert abs(alts[0].logprob - math.log(0.2)) < 1e-6

    def test_zero_probability_yields_neg_inf(self):
        data = [
            {
                "content": "x",
                "probs": [
                    {"tok_str": "x", "prob": 0.0},
                ],
            }
        ]
        result = LogprobNormalizer.from_llamacpp(data)
        assert result is not None
        assert result.tokens[0].logprob == float("-inf")

    def test_full_vocab_available_when_many_alternatives(self):
        # Simulate 150 alternatives (> 100 threshold)
        probs = [{"tok_str": f"tok_{i}", "prob": 1.0 / 150} for i in range(150)]
        data = [{"content": "tok_0", "probs": probs}]
        result = LogprobNormalizer.from_llamacpp(data)
        assert result is not None
        assert result.full_vocab_available is True
        assert result.top_k_available == 150

    def test_not_full_vocab_when_few_alternatives(self):
        probs = [{"tok_str": f"tok_{i}", "prob": 1.0 / 5} for i in range(5)]
        data = [{"content": "tok_0", "probs": probs}]
        result = LogprobNormalizer.from_llamacpp(data)
        assert result is not None
        assert result.full_vocab_available is False

    def test_returns_none_for_empty_input(self):
        assert LogprobNormalizer.from_llamacpp(None) is None
        assert LogprobNormalizer.from_llamacpp([]) is None

    def test_provider_format_is_llamacpp(self):
        data = [{"content": "x", "probs": [{"tok_str": "x", "prob": 0.5}]}]
        result = LogprobNormalizer.from_llamacpp(data)
        assert result is not None
        assert result.provider_format == "llamacpp"


class TestFromOpenAICompletion:
    def test_extracts_tokens_and_logprobs(self):
        """Completions API format: .tokens, .token_logprobs, .top_logprobs."""

        class MockLogprobs:
            tokens = ["Hello", " world"]
            token_logprobs = [-0.5, -1.2]
            top_logprobs = [
                {"Hello": -0.5, "Hi": -1.0, "Hey": -2.0},
                {" world": -1.2, " there": -2.0},
            ]

        result = LogprobNormalizer.from_openai_completion(MockLogprobs())
        assert result is not None
        assert len(result.tokens) == 2
        assert result.tokens[0].token == "Hello"
        assert abs(result.tokens[0].logprob - (-0.5)) < 1e-6
        # Alternatives: Hi and Hey (not Hello itself)
        assert len(result.tokens[0].top_alternatives) == 2

    def test_returns_none_for_none_input(self):
        assert LogprobNormalizer.from_openai_completion(None) is None

    def test_provider_format_is_openai(self):
        class MockLogprobs:
            tokens = ["x"]
            token_logprobs = [-0.1]
            top_logprobs = [{"x": -0.1}]

        result = LogprobNormalizer.from_openai_completion(MockLogprobs())
        assert result is not None
        assert result.provider_format == "openai"
