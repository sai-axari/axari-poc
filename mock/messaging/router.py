"""API endpoints for the messaging app."""
from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import HTMLResponse

from .models import (
    AddReactionRequest,
    ChannelListResponse,
    ChannelType,
    CreateChannelRequest,
    MessageListResponse,
    SendMessageRequest,
    ThreadResponse,
    UserListResponse,
)
from .store import store

router = APIRouter()

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"


@router.get("/messaging", response_class=HTMLResponse)
async def serve_messaging_ui():
    html_path = STATIC_DIR / "messaging.html"
    return HTMLResponse(html_path.read_text())


# ── Users ─────────────────────────────────────────────

@router.get("/api/messaging/users", response_model=UserListResponse)
async def list_users():
    return UserListResponse(users=store.get_users())


# ── Channels ──────────────────────────────────────────

@router.get("/api/messaging/channels", response_model=ChannelListResponse)
async def list_channels(
    user_id: str | None = Query(None),
    type: ChannelType | None = Query(None),
):
    channels = store.get_channels(user_id=user_id, type_filter=type)
    return ChannelListResponse(channels=channels)


@router.post("/api/messaging/channels", response_model=ChannelListResponse)
async def create_channel(req: CreateChannelRequest):
    import uuid
    channel_id = req.name.lower().replace(" ", "-")
    if store.get_channel(channel_id):
        channel_id = f"{channel_id}-{uuid.uuid4().hex[:4]}"
    members = req.members if req.members else [req.created_by]
    if req.created_by not in members:
        members.append(req.created_by)
    ch = store.create_channel(
        channel_id=channel_id, name=req.name, ch_type=req.type,
        description=req.description, created_by=req.created_by, members=members,
    )
    return ChannelListResponse(channels=[ch])


@router.get("/api/messaging/channels/{channel_id}")
async def get_channel(channel_id: str):
    ch = store.get_channel(channel_id)
    if ch is None:
        raise HTTPException(404, "Channel not found")
    return ch


# ── Messages ──────────────────────────────────────────

@router.get("/api/messaging/channels/{channel_id}/messages",
            response_model=MessageListResponse)
async def list_messages(channel_id: str, limit: int = Query(50, ge=1, le=200)):
    if store.get_channel(channel_id) is None:
        raise HTTPException(404, "Channel not found")
    msgs = store.get_messages(channel_id, limit=limit)
    return MessageListResponse(messages=msgs, channel_id=channel_id)


@router.post("/api/messaging/channels/{channel_id}/messages")
async def send_message(channel_id: str, req: SendMessageRequest):
    if store.get_channel(channel_id) is None:
        raise HTTPException(404, "Channel not found")
    msg = store.send_message(channel_id, req.user_id, req.content)
    return msg


# ── Threads ───────────────────────────────────────────

@router.get("/api/messaging/messages/{message_id}/thread",
            response_model=ThreadResponse)
async def get_thread(message_id: str):
    parent, replies = store.get_thread(message_id)
    if parent is None:
        raise HTTPException(404, "Message not found")
    return ThreadResponse(parent=parent, replies=replies)


@router.post("/api/messaging/messages/{message_id}/thread")
async def reply_to_thread(message_id: str, req: SendMessageRequest):
    msg = store.reply_to_thread(message_id, req.user_id, req.content)
    if msg is None:
        raise HTTPException(404, "Parent message not found")
    return msg


# ── Reactions ─────────────────────────────────────────

@router.post("/api/messaging/messages/{message_id}/reactions")
async def toggle_reaction(message_id: str, req: AddReactionRequest):
    msg = store.add_reaction(message_id, req)
    if msg is None:
        raise HTTPException(404, "Message not found")
    return msg
