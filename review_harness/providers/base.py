from dataclasses import dataclass


@dataclass
class Completion:
    text: str
    input_tokens: int = 0
    output_tokens: int = 0


class Provider:
    """messages: [{"role": "user" | "assistant", "content": str}, ...], alternating, starting with user."""

    model: str = ""

    def complete(self, system: str, messages: list[dict], max_output_tokens: int) -> Completion:
        raise NotImplementedError
