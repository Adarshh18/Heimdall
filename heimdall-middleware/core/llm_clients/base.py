from dataclasses import dataclass

@dataclass
class LLMResponse:
    ok:           bool
    text:         str
    error:        str        = ""
    tokens_input: int        = 0
    tokens_output: int       = 0
    model:        str        = ""
    name:         str        = "unknown"

    @property
    def tokens_total(self) -> int:
        return self.tokens_input + self.tokens_output
