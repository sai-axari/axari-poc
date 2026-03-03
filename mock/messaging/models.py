"""Pydantic data models for the messaging app."""
from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field


class UserStatus(str, Enum):
    online = "online"
    away = "away"
    dnd = "dnd"
    offline = "offline"


class ChannelType(str, Enum):
    public = "public"
    private = "private"
    dm = "dm"


# --- Core Models ---

class Reaction(BaseModel):
    emoji: str
    user_ids: list[str] = Field(default_factory=list)


class User(BaseModel):
    id: str
    name: str
    avatar_color: str
    initials: str
    title: str
    status: UserStatus = UserStatus.online
    role: str = ""
    is_bot: bool = True


class Channel(BaseModel):
    id: str
    name: str
    type: ChannelType
    description: str = ""
    members: list[str] = Field(default_factory=list)
    created_by: str = ""
    created_at: datetime = Field(default_factory=datetime.utcnow)


class Message(BaseModel):
    id: str
    channel_id: str
    user_id: str
    content: str
    timestamp: datetime
    thread_id: str | None = None
    reactions: list[Reaction] = Field(default_factory=list)
    reply_count: int = 0
    latest_reply_at: datetime | None = None


# --- Request Models ---

class SendMessageRequest(BaseModel):
    user_id: str = Field(..., description="ID of the sender")
    content: str = Field(..., description="Message content")


class CreateChannelRequest(BaseModel):
    name: str = Field(..., description="Channel name")
    type: ChannelType = Field(default=ChannelType.public)
    description: str = ""
    created_by: str = Field(..., description="User who creates the channel")
    members: list[str] = Field(default_factory=list)


class AddReactionRequest(BaseModel):
    user_id: str = Field(..., description="User toggling the reaction")
    emoji: str = Field(..., description="Emoji string")


# --- Response Models ---

class UserListResponse(BaseModel):
    users: list[User]


class ChannelListResponse(BaseModel):
    channels: list[Channel]


class MessageListResponse(BaseModel):
    messages: list[Message]
    channel_id: str


class ThreadResponse(BaseModel):
    parent: Message
    replies: list[Message]
