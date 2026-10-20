"""Episode configuration; phase durations remain native whole minutes."""

import secrets
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, WithJsonSchema, field_validator


class SeatPlayer(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=200)


# The platform writes each seat's display name into players[slot].name only when the
# schema declares this inline shape (coworld.manifest_validation's
# game_config_with_named_players); a $ref or a nullable union would hide it.
SEAT_PLAYERS_SCHEMA = {
    "type": "array",
    "maxItems": 7,
    "items": {
        "type": "object",
        "properties": {"name": {"type": "string", "minLength": 1, "maxLength": 200}},
        "required": ["name"],
        "additionalProperties": False,
    },
}


class EpisodeConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tokens: list[str] = Field(min_length=7, max_length=7)
    seed: int = Field(default_factory=lambda: secrets.randbits(53))
    # Defaults match the classic-press variant, the game's default.
    phase_minutes: int = Field(default=3, ge=1, le=59)
    retreat_build_minutes: int = Field(default=1, ge=1, le=59)
    press: Literal["NoPress", "Regular"] = "Regular"
    anonymous: bool = True
    end_year: int = Field(default=1908, ge=1901, le=2000)
    scoring: Literal["sum_of_squares", "draw_size", "supply_centers"] = "sum_of_squares"
    player_connect_timeout_seconds: float = Field(default=180, gt=0, le=300)
    episode_budget_seconds: float = Field(default=5910, ge=5, le=5910)
    completion_timeout_seconds: float = Field(default=20, ge=0, le=20)
    render_maps: bool = True
    # countries[slot] is that slot's upstream country ID; None shuffles them by seed.
    countries: list[Annotated[int, Field(ge=1, le=7)]] | None = Field(default=None, min_length=7, max_length=7)
    # Seat display names in slot order, written by the platform. Every player's hello lists
    # them (policy-version names withheld); upstream and /global never see them.
    players: Annotated[list[SeatPlayer], WithJsonSchema(SEAT_PLAYERS_SCHEMA)] = Field(default_factory=list)

    @field_validator("tokens")
    @classmethod
    def unique_tokens(cls, tokens):
        if len(set(tokens)) != 7 or any(not token or len(token) > 80 for token in tokens):
            raise ValueError("seven distinct nonempty tokens of at most 80 characters required")
        return tokens

    @field_validator("players")
    @classmethod
    def one_name_per_seat(cls, players):
        if players and len(players) != 7:
            raise ValueError("players must name all seven seats or be omitted")
        return players

    @field_validator("countries")
    @classmethod
    def countries_are_a_permutation(cls, countries):
        if countries is not None and len(set(countries)) != 7:
            raise ValueError("countries must list each upstream country ID 1-7 exactly once")
        return countries
