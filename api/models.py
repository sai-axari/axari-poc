"""Request/response Pydantic models for the API."""
from __future__ import annotations

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    """Chat API request body."""
    message: str = Field(..., description="User's message")
    conversation_id: str = Field(..., description="Unique conversation identifier")
    tenant_id: str = Field(..., description="Tenant ID for scoped access")
    user_id: str = Field(..., description="User ID")
    user_name: str = Field(default="", description="User's display name")
    org_name: str = Field(default="", description="Organization name")
    user_timezone: str = Field(default="UTC", description="User's timezone")
    allowed_tools: list[str] = Field(default_factory=list, description="Allowed tool names for this tenant")
    integration_constraints: str = Field(default="", description="JSON constraints per integration")


class BehaviorEventRequest(BaseModel):
    """Request to record a user behavior event."""
    tenant_id: str = Field(..., description="Tenant ID")
    user_id: str = Field(..., description="User ID")
    event: dict = Field(..., description="Event data: {type, action, timestamp, metadata}")


class BehaviorDismissRequest(BaseModel):
    """Request to dismiss a nudge."""
    tenant_id: str = Field(..., description="Tenant ID")
    user_id: str = Field(..., description="User ID")
    nudge_id: str = Field(..., description="ID of the nudge to dismiss")


class ResponsibilityExecuteRequest(BaseModel):
    """Request to execute a responsibility (playbook) via streaming."""
    tenant_id: str = Field(..., description="Tenant ID for scoped access")
    responsibility_id: str = Field(..., description="Playbook UUID to execute")
    user_id: str = Field(default="", description="User ID")
    user_name: str = Field(default="", description="User's display name")
    org_name: str = Field(default="", description="Organization name")
    user_timezone: str = Field(default="UTC", description="User's timezone")


class ChatResponse(BaseModel):
    """Chat API response body."""
    response: str = Field(..., description="Agent's response text")
    conversation_id: str = Field(..., description="Conversation ID")
    trajectory: list[dict] = Field(default_factory=list, description="Agent's reasoning trajectory")
    token_usage: dict = Field(default_factory=dict, description="Token usage breakdown")
    events: list[dict] = Field(default_factory=list, description="Real-time events emitted")
