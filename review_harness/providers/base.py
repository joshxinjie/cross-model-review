from dataclasses import dataclass, field


@dataclass
class Completion:
    text: str
    input_tokens: int = 0
    output_tokens: int = 0
    # Tool calls the agent's sandbox refused, as {"tool": str, "command": str} with secrets redacted (Claude Code
    # reports them; other providers leave this empty).
    denials: list[dict] = field(default_factory=list)


class Provider:
    """messages: [{"role": "user" | "assistant", "content": str}, ...], alternating, starting with user."""

    model: str = ""

    def complete(self, system: str, messages: list[dict], max_output_tokens: int) -> Completion:
        raise NotImplementedError
