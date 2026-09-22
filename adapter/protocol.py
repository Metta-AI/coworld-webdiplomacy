from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue


class GameState(BaseModel):
    gameID: int
    turn: int
    phase: str
    gameOver: str


class Member(BaseModel):
    countryID: int
    status: str
    votes: list[str]


class FileVersion(BaseModel):
    url: str
    version: str


class Orders(BaseModel):
    orders: list[dict[str, JsonValue]]


class Context(BaseModel):
    game: GameState
    member: Member
    files: dict[str, FileVersion]
    orders: Orders | None
    messages: dict[str, JsonValue]


class Order(BaseModel):
    model_config = ConfigDict(extra='forbid')
    type: Literal['Hold', 'Move', 'Support hold', 'Support move', 'Convoy', 'Retreat', 'Disband', 'Build Army', 'Build Fleet', 'Wait', 'Destroy']
    terrID: int = 0
    fromTerrID: int = 0
    toTerrID: int = 0
    viaConvoy: Literal['Yes', 'No'] = 'No'


class Message(BaseModel):
    model_config = ConfigDict(extra='forbid')
    toCountryID: int = Field(ge=0, le=7)
    message: str = Field(min_length=1, max_length=4000)


class Action(BaseModel):
    model_config = ConfigDict(extra='forbid')
    turn: int
    phase: str
    orders: list[Order]
    messages: list[Message] = []
    draw: bool = False


class Config(BaseModel):
    model_config = ConfigDict(extra='forbid')
    tokens: list[str] = Field(min_length=7, max_length=7)
    max_phases: int = Field(default=20, ge=1, le=200)
    action_timeout_seconds: float = Field(default=30, gt=0)
    player_connect_timeout_seconds: float = Field(default=180, gt=0)
