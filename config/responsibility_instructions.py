"""Summarized, Atlas-friendly instructions for each known responsibility type.

These are concise prompts that Atlas can execute using its available tools.
The execute endpoint matches playbook names (case-insensitive) against the keys
in RESPONSIBILITY_INSTRUCTIONS, falling back to __default__ for unknown types.
"""

RESPONSIBILITY_INSTRUCTIONS = {
    "morning brief": """
        Run the Morning Brief. Collect data from the last 24 hours across all connected sources:
        1. Fetch emails (Outlook/Gmail) - urgent items, action items, key threads
        2. Fetch today's calendar events - upcoming meetings, prep needed
        3. Fetch SIEM alerts (CrowdStrike/Defender) - open/in-progress, critical/high severity
        4. Fetch Jira issues - updated in last 24h, open/in-progress
        5. Fetch messaging (Teams/Slack) - important threads
        Synthesize into a concise morning brief: top priorities, key meetings,
        open security items, and suggested actions. Present as a structured summary.
    """,
    "commitment radar": """
        Run the Commitments Radar. Review recent communications and task data to identify:
        1. Fetch recent emails for promises/commitments made by the user
        2. Fetch Jira issues assigned to or created by the user
        3. Fetch calendar events for follow-up items from past meetings
        Identify commitments at risk of being missed, overdue items, and upcoming deadlines.
        Present each commitment with: title, source, due date, importance, and recommended action.
    """,
    "meeting prep": """
        Run Meeting Prep. For each upcoming meeting in the next 24 hours:
        1. Fetch calendar events for today and tomorrow
        2. For each meeting, search emails for related threads
        3. Search Jira for related tickets/projects
        4. Check messaging (Teams/Slack) for recent discussion context
        Prepare a brief for each meeting: attendees, agenda context,
        relevant open items, suggested talking points, and pre-read materials.
    """,
    # Fallback for unknown playbook types
    "__default__": """
        Execute this responsibility using all available tools.
        Gather relevant data from connected integrations, analyze it,
        and present a structured summary with key findings and recommended actions.
    """,
}
