"""In-memory store with seed data for the messaging app."""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta

from .models import (
    AddReactionRequest,
    Channel,
    ChannelType,
    Message,
    Reaction,
    User,
    UserStatus,
)


def _ts(minutes_ago: int) -> datetime:
    """Helper to generate a timestamp N minutes ago."""
    return datetime.utcnow() - timedelta(minutes=minutes_ago)


def _uid() -> str:
    return uuid.uuid4().hex[:8]


class MessagingStore:
    def __init__(self) -> None:
        self._users: dict[str, User] = {}
        self._channels: dict[str, Channel] = {}
        self._messages: dict[str, Message] = {}
        self._channel_messages: dict[str, list[str]] = {}   # channel_id → top-level msg IDs
        self._thread_replies: dict[str, list[str]] = {}     # parent_msg_id → reply IDs
        self._seed()

    # ── Seed Data ─────────────────────────────────────────

    def _seed(self) -> None:
        self._seed_users()
        self._seed_channels()
        self._seed_messages()

    def _seed_users(self) -> None:
        users = [
            User(id="you", name="You", avatar_color="#7c4dff", initials="YO",
                 title="Employee", status=UserStatus.online, role="member", is_bot=False),
            User(id="atlas", name="Atlas", avatar_color="#33CAFF", initials="AT",
                 title="Chief of Staff", status=UserStatus.online, role="admin"),
            User(id="eve", name="Eve", avatar_color="#9850FF", initials="EV",
                 title="Executive Assistant", status=UserStatus.online, role="admin"),
            User(id="janice", name="Janice", avatar_color="#FF6B6B", initials="JA",
                 title="Program Manager", status=UserStatus.online, role="member"),
            User(id="nova", name="Nova", avatar_color="#ffd54f", initials="NO",
                 title="Security Analyst", status=UserStatus.away, role="member"),
            User(id="cipher", name="Cipher", avatar_color="#81c784", initials="CI",
                 title="DevOps Engineer", status=UserStatus.online, role="member"),
            User(id="sage", name="Sage", avatar_color="#ff9800", initials="SA",
                 title="Data Scientist", status=UserStatus.dnd, role="member"),
            User(id="bolt", name="Bolt", avatar_color="#e91e63", initials="BO",
                 title="Frontend Engineer", status=UserStatus.online, role="member"),
            User(id="echo", name="Echo", avatar_color="#00bcd4", initials="EC",
                 title="QA & Testing Lead", status=UserStatus.offline, role="member"),
        ]
        for u in users:
            self._users[u.id] = u

    def _seed_channels(self) -> None:
        all_ids = list(self._users.keys())

        channels = [
            Channel(id="general", name="general", type=ChannelType.public,
                    description="Company-wide announcements and work-based matters",
                    members=all_ids, created_by="atlas", created_at=_ts(10000)),
            Channel(id="security-alerts", name="security-alerts", type=ChannelType.public,
                    description="Security monitoring and incident alerts",
                    members=all_ids, created_by="nova", created_at=_ts(9000)),
            Channel(id="engineering", name="engineering", type=ChannelType.public,
                    description="Engineering discussions, code reviews, and architecture",
                    members=["you", "cipher", "bolt", "echo", "sage", "atlas"],
                    created_by="cipher", created_at=_ts(8500)),
            Channel(id="random", name="random", type=ChannelType.public,
                    description="Non-work banter and water cooler conversations",
                    members=all_ids, created_by="atlas", created_at=_ts(10000)),
            Channel(id="leadership", name="Leadership Team", type=ChannelType.private,
                    description="Leadership sync and strategy discussions",
                    members=["you", "atlas", "eve", "janice"], created_by="atlas",
                    created_at=_ts(9500)),
            Channel(id="incident-response", name="Incident Response", type=ChannelType.private,
                    description="Active incident coordination",
                    members=["you", "nova", "cipher", "atlas", "echo"], created_by="nova",
                    created_at=_ts(7000)),
            Channel(id="dm-you-atlas", name="You, Atlas", type=ChannelType.dm,
                    members=["you", "atlas"], created_at=_ts(9000)),
            Channel(id="dm-you-eve", name="You, Eve", type=ChannelType.dm,
                    members=["you", "eve"], created_at=_ts(8500)),
            Channel(id="dm-you-janice", name="You, Janice", type=ChannelType.dm,
                    members=["you", "janice"], created_at=_ts(8000)),
            Channel(id="dm-you-nova", name="You, Nova", type=ChannelType.dm,
                    members=["you", "nova"], created_at=_ts(7500)),
            Channel(id="dm-you-cipher", name="You, Cipher", type=ChannelType.dm,
                    members=["you", "cipher"], created_at=_ts(7000)),
            Channel(id="dm-you-sage", name="You, Sage", type=ChannelType.dm,
                    members=["you", "sage"], created_at=_ts(6500)),
            Channel(id="dm-you-bolt", name="You, Bolt", type=ChannelType.dm,
                    members=["you", "bolt"], created_at=_ts(6000)),
            Channel(id="dm-you-echo", name="You, Echo", type=ChannelType.dm,
                    members=["you", "echo"], created_at=_ts(5500)),
        ]
        for ch in channels:
            self._channels[ch.id] = ch
            self._channel_messages[ch.id] = []

    def _add_msg(self, mid: str, channel_id: str, user_id: str, content: str,
                 minutes_ago: int, thread_id: str | None = None,
                 reactions: list[Reaction] | None = None) -> Message:
        msg = Message(
            id=mid, channel_id=channel_id, user_id=user_id, content=content,
            timestamp=_ts(minutes_ago), thread_id=thread_id,
            reactions=reactions or [],
        )
        self._messages[mid] = msg
        if thread_id is None:
            self._channel_messages[channel_id].append(mid)
        else:
            self._thread_replies.setdefault(thread_id, []).append(mid)
            parent = self._messages[thread_id]
            parent.reply_count += 1
            parent.latest_reply_at = msg.timestamp
        return msg

    def _seed_messages(self) -> None:
        # ── #general ──
        self._add_msg("g1", "general", "atlas",
                       "Good morning team! Quick reminder: our quarterly planning review is tomorrow at 10 AM. Please have your OKR updates ready.", 180)
        self._add_msg("g2", "general", "eve",
                       "I've sent calendar invites to everyone. Agenda doc is pinned in the Leadership channel.", 175)
        self._add_msg("g3", "general", "janice",
                       "All project status reports are updated in the tracker. We're on track for 87% of Q1 deliverables.", 160)
        self._add_msg("g4", "general", "bolt",
                       "The new dashboard UI is deployed to staging! Would love feedback from everyone before we push to prod.", 120,
                       reactions=[Reaction(emoji="🚀", user_ids=["cipher", "echo", "atlas"]),
                                  Reaction(emoji="👀", user_ids=["janice", "sage"])])
        self._add_msg("g5", "general", "sage",
                       "Weekly analytics digest: DAU up 12%, avg session duration increased by 8%. Full report in the data channel.", 90)
        self._add_msg("g6", "general", "atlas",
                       "Great work everyone. Let's keep this momentum going into Q2.", 45,
                       reactions=[Reaction(emoji="💪", user_ids=["eve", "janice", "cipher", "bolt"])])

        # ── #security-alerts (with threads) ──
        self._add_msg("s1", "security-alerts", "nova",
                       "🚨 **ALERT**: Detected unusual login pattern from IP range 203.0.113.0/24. 47 failed attempts in the last hour targeting service accounts.", 300)
        self._add_msg("s1r1", "security-alerts", "cipher",
                       "I've checked the firewall logs — this range is from a known cloud provider. Could be a misconfigured bot. Blocking the range now.", 295, thread_id="s1")
        self._add_msg("s1r2", "security-alerts", "nova",
                       "Good call. I've also rotated the targeted service account credentials and enabled rate limiting on the auth endpoint.", 290, thread_id="s1")
        self._add_msg("s1r3", "security-alerts", "atlas",
                       "Thanks for the quick response. Can we get a post-incident report by end of day?", 280, thread_id="s1")

        self._add_msg("s2", "security-alerts", "nova",
                       "SSL certificate for api.axari.dev expires in 14 days. Auto-renewal is configured but flagging for visibility.", 200,
                       reactions=[Reaction(emoji="👍", user_ids=["cipher", "atlas"])])
        self._add_msg("s3", "security-alerts", "nova",
                       "Dependency scan complete: 0 critical, 2 moderate vulnerabilities found in Node packages. PRs auto-created for fixes.", 100)

        # ── #engineering (with threads) ──
        self._add_msg("e1", "engineering", "cipher",
                       "Finished migrating the CI/CD pipeline to GitHub Actions. Build times are down from 12min to 4min. 🎉", 400)
        self._add_msg("e1r1", "engineering", "bolt",
                       "Nice! Does this affect the preview deployment workflow?", 395, thread_id="e1")
        self._add_msg("e1r2", "engineering", "cipher",
                       "Nope, preview deploys still work the same. Actually they're faster now too — about 2min to deploy.", 390, thread_id="e1")
        self._add_msg("e1r3", "engineering", "echo",
                       "I'll update the testing docs to reflect the new pipeline. The old Jenkins references need to go.", 385, thread_id="e1")

        self._add_msg("e2", "engineering", "bolt",
                       "PR #342 is ready for review: Refactored the component library to use CSS custom properties. Much easier theming now.", 250,
                       reactions=[Reaction(emoji="🎨", user_ids=["sage"])])
        self._add_msg("e3", "engineering", "echo",
                       "Test coverage report: 94.2% on backend, 87.1% on frontend. I've flagged 3 uncovered edge cases in the payment module.", 150)
        self._add_msg("e4", "engineering", "sage",
                       "Anyone have experience with WebSocket connection pooling? Seeing some memory leaks in the real-time analytics service.", 60)
        self._add_msg("e4r1", "engineering", "cipher",
                       "Check if connections are being properly closed on client disconnect. We had the same issue last quarter.", 55, thread_id="e4")

        # ── #random ──
        self._add_msg("r1", "random", "bolt",
                       "Hot take: tabs > spaces. Fight me. 😤", 500,
                       reactions=[Reaction(emoji="😂", user_ids=["echo", "sage", "cipher"]),
                                  Reaction(emoji="👎", user_ids=["nova", "atlas"])])
        self._add_msg("r2", "random", "echo",
                       "My test suite just passed on the first try. I don't trust it.", 350,
                       reactions=[Reaction(emoji="😂", user_ids=["bolt", "cipher", "janice", "sage", "atlas"])])
        self._add_msg("r3", "random", "sage",
                       "Just trained a model to predict which PRs will have merge conflicts. Accuracy: 91%. Should I deploy it?", 200,
                       reactions=[Reaction(emoji="🤯", user_ids=["bolt", "cipher"]),
                                  Reaction(emoji="👀", user_ids=["atlas", "eve"])])
        self._add_msg("r4", "random", "cipher",
                       "The staging server just wished me happy birthday. I didn't program that. Should I be concerned?", 100,
                       reactions=[Reaction(emoji="😂", user_ids=["bolt", "echo", "nova", "janice", "atlas", "eve", "sage"])])

        # ── Leadership Team (private) ──
        self._add_msg("l1", "leadership", "atlas",
                       "Q2 budget proposal is attached. Key changes: +15% on infrastructure, +10% on security tooling.", 600)
        self._add_msg("l2", "leadership", "eve",
                       "I've scheduled individual syncs with each team lead for next week. Calendar invites going out today.", 500)
        self._add_msg("l3", "leadership", "janice",
                       "Hiring update: We have 3 strong candidates for the ML Engineer role. Panel interviews scheduled for next Thursday.", 300)

        # ── Incident Response (private) ──
        self._add_msg("i1", "incident-response", "nova",
                       "Opening incident channel for the auth service latency spike. P95 response time jumped from 200ms to 1.8s.", 240)
        self._add_msg("i2", "incident-response", "cipher",
                       "Root cause identified: connection pool exhaustion on the auth DB. Scaling up connections now.", 230)
        self._add_msg("i3", "incident-response", "echo",
                       "Confirmed fix is working. Response times back to normal. Running regression tests now.", 210)
        self._add_msg("i4", "incident-response", "atlas",
                       "Good work team. Nova, please add this to the post-mortem tracker.", 200)

        # ── DMs ──
        self._add_msg("d1", "dm-you-atlas", "atlas",
                       "Hey! Welcome aboard. Let me know if you need anything to get started.", 400)
        self._add_msg("d2", "dm-you-atlas", "you",
                       "Thanks Atlas! Just getting set up. Quick question — where do I find the onboarding docs?", 395)
        self._add_msg("d3", "dm-you-atlas", "atlas",
                       "Eve put together a great onboarding guide. I'll have her send it over. You'll be up to speed in no time.", 390)

        self._add_msg("d4", "dm-you-eve", "eve",
                       "Hi! Atlas mentioned you might need the onboarding guide. Here's the link — let me know if you have questions!", 380)
        self._add_msg("d5", "dm-you-eve", "you",
                       "Perfect, thanks Eve! I'll go through it today.", 375)

        self._add_msg("d6", "dm-you-cipher", "cipher",
                       "Hey, welcome to the team! If you need dev environment help, just ping me.", 300)
        self._add_msg("d7", "dm-you-cipher", "you",
                       "Appreciate it! Actually, any tips on getting the local Docker setup running?", 295)
        self._add_msg("d8", "dm-you-cipher", "cipher",
                       "Sure — just run `make dev-setup` from the repo root. It'll pull all the images and seed the DB.", 290)

        self._add_msg("d9", "dm-you-nova", "nova",
                       "Quick heads up — you'll need to complete the security training before getting prod access. Link is in #security-alerts.", 200)

        self._add_msg("d10", "dm-you-bolt", "bolt",
                       "Hey! Saw you joined the engineering channel. Excited to have you on the team! 🎉", 150)
        self._add_msg("d11", "dm-you-bolt", "you",
                       "Thanks Bolt! Looking forward to working together.", 145)

    # ── Public API ────────────────────────────────────────

    def get_users(self) -> list[User]:
        return list(self._users.values())

    def get_user(self, user_id: str) -> User | None:
        return self._users.get(user_id)

    def get_channels(self, user_id: str | None = None,
                     type_filter: ChannelType | None = None) -> list[Channel]:
        channels = list(self._channels.values())
        if type_filter is not None:
            channels = [ch for ch in channels if ch.type == type_filter]
        if user_id is not None:
            channels = [ch for ch in channels if user_id in ch.members]
        return sorted(channels, key=lambda c: c.created_at)

    def get_channel(self, channel_id: str) -> Channel | None:
        return self._channels.get(channel_id)

    def create_channel(self, channel_id: str, name: str, ch_type: ChannelType,
                       description: str, created_by: str,
                       members: list[str]) -> Channel:
        ch = Channel(
            id=channel_id, name=name, type=ch_type, description=description,
            created_by=created_by, members=members, created_at=datetime.utcnow(),
        )
        self._channels[channel_id] = ch
        self._channel_messages[channel_id] = []
        return ch

    def get_messages(self, channel_id: str, limit: int = 50) -> list[Message]:
        msg_ids = self._channel_messages.get(channel_id, [])
        ids = msg_ids[-limit:]
        return [self._messages[mid] for mid in ids]

    def send_message(self, channel_id: str, user_id: str, content: str) -> Message:
        mid = _uid()
        msg = Message(
            id=mid, channel_id=channel_id, user_id=user_id, content=content,
            timestamp=datetime.utcnow(),
        )
        self._messages[mid] = msg
        self._channel_messages.setdefault(channel_id, []).append(mid)
        return msg

    def get_thread(self, message_id: str) -> tuple[Message | None, list[Message]]:
        parent = self._messages.get(message_id)
        if parent is None:
            return None, []
        reply_ids = self._thread_replies.get(message_id, [])
        replies = [self._messages[rid] for rid in reply_ids]
        return parent, replies

    def reply_to_thread(self, parent_id: str, user_id: str, content: str) -> Message | None:
        parent = self._messages.get(parent_id)
        if parent is None:
            return None
        mid = _uid()
        msg = Message(
            id=mid, channel_id=parent.channel_id, user_id=user_id,
            content=content, timestamp=datetime.utcnow(), thread_id=parent_id,
        )
        self._messages[mid] = msg
        self._thread_replies.setdefault(parent_id, []).append(mid)
        parent.reply_count += 1
        parent.latest_reply_at = msg.timestamp
        return msg

    def add_reaction(self, message_id: str, req: AddReactionRequest) -> Message | None:
        msg = self._messages.get(message_id)
        if msg is None:
            return None
        for r in msg.reactions:
            if r.emoji == req.emoji:
                if req.user_id in r.user_ids:
                    r.user_ids.remove(req.user_id)
                    if not r.user_ids:
                        msg.reactions.remove(r)
                else:
                    r.user_ids.append(req.user_id)
                return msg
        msg.reactions.append(Reaction(emoji=req.emoji, user_ids=[req.user_id]))
        return msg


# Singleton store
store = MessagingStore()
