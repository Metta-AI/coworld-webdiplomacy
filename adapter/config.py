"""Episode configuration; phase durations remain native whole minutes."""

import secrets
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class EpisodeConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tokens: list[str] = Field(min_length=7, max_length=7)
    seed: int = Field(default_factory=lambda: secrets.randbits(53))
    phase_minutes: int = Field(default=1, ge=1, le=59)
    retreat_build_minutes: int = Field(default=1, ge=1, le=59)
    press: Literal["NoPress", "Regular"] = "NoPress"
    anonymous: bool = True
    end_year: int = Field(default=1910, ge=1901, le=2000)
    scoring: Literal["sum_of_squares", "draw_size", "supply_centers"] = "sum_of_squares"
    player_connect_timeout_seconds: float = Field(default=180, gt=0, le=300)
    episode_budget_seconds: float = Field(default=5910, ge=5, le=5910)
    completion_timeout_seconds: float = Field(default=20, ge=0, le=20)
    render_maps: bool = True

    @field_validator("tokens")
    @classmethod
    def unique_tokens(cls, tokens):
        if len(set(tokens)) != 7 or any(not token or len(token) > 80 for token in tokens):
            raise ValueError("seven distinct nonempty tokens of at most 80 characters required")
        return tokens
