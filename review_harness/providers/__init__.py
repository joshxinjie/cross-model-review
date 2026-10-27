"""Provider adapters. Each turns (system, messages) into text with token usage; nothing else is provider-specific."""

from .base import Completion, Provider


def get_provider(reviewer: dict, work_dir=None) -> Provider:
    """work_dir: the checkout the reviewer reads and runs tests in (default: the harness's repo)."""
    kind = reviewer["provider"]
    if kind == "anthropic":
        from .anthropic import AnthropicProvider
        return AnthropicProvider(reviewer)
    if kind == "claude-code":
        from .claude_code import ClaudeCodeProvider
        return ClaudeCodeProvider(reviewer, work_dir=work_dir)
    if kind == "codex":
        from .codex import CodexProvider
        return CodexProvider(reviewer, work_dir=work_dir)
    raise NotImplementedError(f"no adapter yet for provider {kind!r} (milestone M6)")


__all__ = ["Completion", "Provider", "get_provider"]
