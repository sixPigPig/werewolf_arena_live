from __future__ import annotations

from app.werewolf.models import ActionLog


class LocalModel:
    """Deterministic stand-in for an LLM provider."""

    def choose(
        self,
        *,
        actor: str,
        action: str,
        options: list[str],
        round_number: int,
    ) -> tuple[str | None, ActionLog]:
        ordered_options = sorted(options)
        choice = ordered_options[0] if ordered_options else None
        rationale = (
            f"local model chose {choice} for {action} in round {round_number}"
            if choice
            else f"local model had no legal options for {action} in round {round_number}"
        )
        return choice, ActionLog(actor, action, ordered_options, choice, rationale)

    def speak(self, *, actor: str, options: list[str], round_number: int) -> tuple[str, ActionLog]:
        target, log = self.choose(
            actor=actor,
            action="debate",
            options=[option for option in options if option != actor],
            round_number=round_number,
        )
        if target:
            message = f"I think we should pay close attention to {target}."
        else:
            message = "I am watching the table carefully."

        log.choice = message
        log.rationale = f"local model generated debate text in round {round_number}"
        return message, log
