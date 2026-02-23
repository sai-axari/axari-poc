"""
In-memory user behavior tracking store.

This module tracks user interaction patterns (what actions they use, when
they use them, which dashboard sections they click) and uses that data to
personalize the experience:
- Reorder quick-action buttons by frequency
- Generate time-based greetings ("You usually check emails around now")
- Surface proactive nudges based on habitual patterns

All data is stored in-memory per tenant+user and capped at MAX_EVENTS
to bound memory usage. In production this would be backed by a database.
"""
from __future__ import annotations

import logging
from collections import defaultdict
from datetime import datetime

logger = logging.getLogger(__name__)

# Maximum number of events to retain per user (oldest are dropped FIFO)
MAX_EVENTS = 500

# The default set of quick-action buttons shown in the UI.
# These get reordered based on the user's actual usage patterns.
DEFAULT_ACTIONS = [
    {"label": "Morning brief", "prompt": "Give me my morning brief"},
    {"label": "Commitments", "prompt": "What are my open commitments?"},
    {"label": "Meeting prep", "prompt": "Prep me for my next meeting"},
    {"label": "Check emails", "prompt": "Fetch my emails from today"},
]


class BehaviorStore:
    """
    In-memory user behavior tracker (per tenant+user).

    Records events like dashboard clicks, chat messages, and session starts,
    then computes a behavioral profile used to personalize greetings,
    reorder actions, and generate proactive nudges.
    """

    def __init__(self):
        # Maps "tenant_id:user_id" -> list of event dicts
        self._events: dict[str, list[dict]] = {}
        # Maps "tenant_id:user_id" -> set of dismissed nudge IDs
        # (so dismissed nudges don't reappear within the same session)
        self._dismissed: dict[str, set[str]] = {}

    def _key(self, tenant_id: str, user_id: str) -> str:
        """Build the composite key used for both _events and _dismissed."""
        return f"{tenant_id}:{user_id}"

    def record_event(self, tenant_id: str, user_id: str, event: dict) -> None:
        """
        Append an event to the user's event list.

        Events are capped at MAX_EVENTS using FIFO eviction — when the
        list exceeds the cap, the oldest events are dropped.
        """
        key = self._key(tenant_id, user_id)
        if key not in self._events:
            self._events[key] = []
        self._events[key].append(event)
        # FIFO cap: keep only the most recent MAX_EVENTS
        if len(self._events[key]) > MAX_EVENTS:
            self._events[key] = self._events[key][-MAX_EVENTS:]

    def dismiss_nudge(self, tenant_id: str, user_id: str, nudge_id: str) -> None:
        """Mark a nudge as dismissed so it won't appear again this session."""
        key = self._key(tenant_id, user_id)
        if key not in self._dismissed:
            self._dismissed[key] = set()
        self._dismissed[key].add(nudge_id)

    def get_profile(self, tenant_id: str, user_id: str) -> dict:
        """
        Compute and return a behavioral profile from stored events.

        The profile includes:
        - peak_hours: top 3 hours of the day the user is most active
        - top_actions: most frequently used actions/prompts
        - section_engagement: most clicked dashboard sections
        - session_count: total number of sessions recorded
        - avg_session_hour: average hour of the day sessions start
        - current_hour_context: what the user typically does right now
        - suggested_greeting: personalized greeting string
        - suggested_actions: DEFAULT_ACTIONS reordered by usage frequency
        - nudges: proactive suggestions based on time-of-day patterns
        """
        key = self._key(tenant_id, user_id)
        events = self._events.get(key, [])
        dismissed = self._dismissed.get(key, set())

        # Return defaults if no events have been recorded yet
        if not events:
            return {
                "peak_hours": [],
                "top_actions": [],
                "section_engagement": [],
                "session_count": 0,
                "avg_session_hour": None,
                "current_hour_context": None,
                "suggested_greeting": None,
                "suggested_actions": DEFAULT_ACTIONS,
                "nudges": [],
            }

        now = datetime.now()
        current_hour = now.hour

        # --- Peak hours ---
        # Bucket every event by its hour-of-day, then take the top 3 hours
        hour_counts: dict[int, int] = defaultdict(int)
        for ev in events:
            ts = ev.get("timestamp")
            if ts:
                try:
                    dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                    hour_counts[dt.hour] += 1
                except (ValueError, TypeError):
                    # Fallback: use the "hour" field from event metadata
                    meta_hour = ev.get("metadata", {}).get("hour")
                    if meta_hour is not None:
                        hour_counts[int(meta_hour)] += 1

        peak_hours = sorted(hour_counts, key=hour_counts.get, reverse=True)[:3]

        # --- Top actions ---
        # Count how often each action/prompt appears in dash_action and chat_message events
        action_counts: dict[str, int] = defaultdict(int)
        for ev in events:
            if ev.get("type") in ("dash_action", "chat_message"):
                action = ev.get("action", "")
                if action:
                    action_counts[action] += 1
        top_actions = sorted(action_counts, key=action_counts.get, reverse=True)

        # --- Section engagement ---
        # Track which dashboard sections the user clicks most often
        section_counts: dict[str, int] = defaultdict(int)
        for ev in events:
            if ev.get("type") == "section_click":
                section = ev.get("action", "")
                if section:
                    section_counts[section] += 1
        section_engagement = sorted(section_counts, key=section_counts.get, reverse=True)

        # --- Session stats ---
        # Count total sessions and compute the average hour they start
        session_events = [ev for ev in events if ev.get("type") == "session_start"]
        session_count = len(session_events)
        avg_session_hour = None
        if session_events:
            hours = []
            for ev in session_events:
                meta_hour = ev.get("metadata", {}).get("hour")
                if meta_hour is not None:
                    hours.append(int(meta_hour))
                else:
                    ts = ev.get("timestamp")
                    if ts:
                        try:
                            dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                            hours.append(dt.hour)
                        except (ValueError, TypeError):
                            pass
            if hours:
                avg_session_hour = round(sum(hours) / len(hours), 1)

        # --- Current hour context ---
        # Find the most common action the user does around this time of day
        # (within a +/- 1 hour window)
        current_hour_actions: dict[str, int] = defaultdict(int)
        for ev in events:
            if ev.get("type") in ("dash_action", "chat_message"):
                meta_hour = ev.get("metadata", {}).get("hour")
                if meta_hour is not None and abs(int(meta_hour) - current_hour) <= 1:
                    action = ev.get("action", "")
                    if action:
                        current_hour_actions[action] += 1
        current_hour_context = None
        if current_hour_actions:
            current_hour_context = max(current_hour_actions, key=current_hour_actions.get)

        # --- Personalized greeting ---
        suggested_greeting = self._build_greeting(
            current_hour, current_hour_context, top_actions, session_count
        )

        # --- Reorder quick actions by frequency ---
        suggested_actions = self._build_suggested_actions(action_counts)

        # --- Proactive nudges ---
        nudges = self._build_nudges(
            current_hour, events, action_counts, dismissed
        )

        return {
            "peak_hours": peak_hours,
            "top_actions": top_actions[:10],
            "section_engagement": section_engagement,
            "session_count": session_count,
            "avg_session_hour": avg_session_hour,
            "current_hour_context": current_hour_context,
            "suggested_greeting": suggested_greeting,
            "suggested_actions": suggested_actions,
            "nudges": nudges,
        }

    def _build_greeting(
        self,
        current_hour: int,
        current_hour_context: str | None,
        top_actions: list[str],
        session_count: int,
    ) -> str | None:
        """
        Build a personalized greeting based on time of day and usage patterns.

        Returns None if there isn't enough data yet (< 2 sessions).
        Prefers a time-specific suggestion ("you usually X around now") over
        a generic one ("your most-used action is X").
        """
        if session_count < 2:
            return None  # Not enough data to personalize

        time_of_day = "morning" if current_hour < 12 else "afternoon" if current_hour < 17 else "evening"

        # If we know what the user typically does at this hour, suggest that
        if current_hour_context:
            action_label = self._action_to_label(current_hour_context)
            return f"Good {time_of_day} — you usually start with {action_label} around now. Want me to get that going?"

        # Otherwise, suggest their most-used action overall
        if top_actions:
            action_label = self._action_to_label(top_actions[0])
            return f"Good {time_of_day} — your most-used action is {action_label}. Want to start there?"

        return None

    def _action_to_label(self, action: str) -> str:
        """
        Convert an action prompt string to a short human-readable label.

        Checks if the action matches a known DEFAULT_ACTIONS prompt and
        returns its label. Otherwise, truncates long strings.
        """
        action_lower = action.lower()
        for da in DEFAULT_ACTIONS:
            if da["prompt"].lower() == action_lower:
                return da["label"].lower()
        # Truncate long action strings for display
        if len(action) > 50:
            return action[:50] + "..."
        return action

    def _build_suggested_actions(self, action_counts: dict[str, int]) -> list[dict]:
        """
        Reorder the default quick-action buttons by how often the user uses each.

        Most-used actions float to the top. Actions with equal counts
        retain their original order.
        """
        if not action_counts:
            return DEFAULT_ACTIONS

        # Score each default action by how often its prompt was used
        scored = []
        for da in DEFAULT_ACTIONS:
            count = action_counts.get(da["prompt"], 0)
            scored.append((count, da))

        # Sort by count descending; ties keep original order (stable sort)
        scored.sort(key=lambda x: x[0], reverse=True)
        return [item for _, item in scored]

    def _build_nudges(
        self,
        current_hour: int,
        events: list[dict],
        action_counts: dict[str, int],
        dismissed: set[str],
    ) -> list[dict]:
        """
        Generate proactive nudges based on time-of-day usage patterns.

        A nudge is shown if the user has performed an action at least twice
        around the current hour (+/- 1 hour). Dismissed nudges are excluded.
        At most 3 nudges are returned.
        """
        nudges = []

        # Build a map of hour -> {action -> count} across all events
        hour_action_counts: dict[int, dict[str, int]] = defaultdict(lambda: defaultdict(int))
        for ev in events:
            if ev.get("type") in ("dash_action", "chat_message"):
                meta_hour = ev.get("metadata", {}).get("hour")
                action = ev.get("action", "")
                if meta_hour is not None and action:
                    hour_action_counts[int(meta_hour)][action] += 1

        # Check the current hour and its neighbors (3-hour window)
        seen_actions = set()
        for h in range(current_hour - 1, current_hour + 2):
            normalized_h = h % 24  # Wrap around midnight (e.g. -1 -> 23)
            if normalized_h in hour_action_counts:
                for action, count in hour_action_counts[normalized_h].items():
                    # Only nudge if the user has done this at least twice at this hour
                    if count >= 2 and action not in seen_actions:
                        nudge_id = f"nudge-{action}"
                        if nudge_id not in dismissed:
                            label = self._action_to_label(action)
                            nudges.append({
                                "id": nudge_id,
                                "message": f"You usually {label} around this time.",
                                "action_label": label.capitalize(),
                                "action_prompt": action,
                            })
                            seen_actions.add(action)

        # Return at most 3 nudges to avoid overwhelming the UI
        return nudges[:3]
