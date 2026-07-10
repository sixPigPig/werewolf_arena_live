from __future__ import annotations


class PlayerProfileError(Exception):
    """Base class for HTTP-independent player-profile failures."""


class PlayerProfileNotFound(PlayerProfileError):
    def __init__(self, profile_id: str) -> None:
        self.profile_id = profile_id
        super().__init__(f"Player profile not found: {profile_id}")


class PlayerProfileValidationError(PlayerProfileError):
    pass


class PlayerProfileVersionConflict(PlayerProfileError):
    def __init__(
        self,
        profile_id: str,
        *,
        current_version: int | None,
    ) -> None:
        self.profile_id = profile_id
        self.current_version = current_version
        super().__init__(f"Player profile version conflict: {profile_id}")


class PlayerProfileTransitionError(PlayerProfileError):
    def __init__(
        self,
        profile_id: str,
        *,
        current_status: str,
        target_status: str,
    ) -> None:
        self.profile_id = profile_id
        self.current_status = current_status
        self.target_status = target_status
        super().__init__(
            f"Cannot transition player profile {profile_id} "
            f"from {current_status} to {target_status}"
        )
