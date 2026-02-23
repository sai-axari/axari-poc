"""
Register all integration tools from the existing axari-ai-agents codebase.

This file imports integration classes and registers them with the POC tool registry.
The integration classes are pure async Python with no LangGraph/DSPy dependency.

To use: call register_all_integration_tools() at startup.
"""
from __future__ import annotations

import sys
import os
import logging

from tools.registry import register_tool

logger = logging.getLogger(__name__)

# Add the existing codebase to Python path so we can import integrations.
# Use append (not insert) to avoid shadowing the POC's own main.py with
# axari-ai-agents/main.py when uvicorn's reloader re-imports modules.
AGENTS_ROOT = os.path.join(os.path.dirname(__file__), "..", "..", "axari-ai-agents")
if os.path.exists(AGENTS_ROOT):
    sys.path.append(AGENTS_ROOT)


def register_all_integration_tools():
    """
    Register all integration tools from the existing codebase.

    Each tool is registered with its name and the bound async method.
    Auto-generates Anthropic tool schemas from function signatures + docstrings.

    Tools are organized by category:
    - Calendar (Microsoft, Google)
    - Email (Outlook, Gmail)
    - Messaging (Teams, Slack)
    - Workflow Management (Jira, Dex)
    - Security (CrowdStrike, Rapid7, Microsoft Defender, Qualys)
    - Content Management (SharePoint, Google Drive, Notion)
    - Developer Tools (GitHub)
    - GRC/Compliance (Vanta)
    - Industry Intelligence (RSS Feeds)
    """
    registered = 0
    failed = 0

    # --- Calendar Integrations ---
    registered += _register_safe("microsoft_calendar:fetch_calendar_details",
        "integrations.microsoft.microsoft_calender", "MicrosoftCalendar", "fetch_calendar_details")
    registered += _register_safe("google_calendar:fetch_calendar_details",
        "integrations.google.google_calendar", "GoogleCalendar", "fetch_calendar_details")

    # --- Email Integrations ---
    registered += _register_safe("microsoft_outlook:fetch_outlook_emails",
        "integrations.microsoft.microsoft_outlook", "MicrosoftOutlook", "fetch_outlook_emails")
    registered += _register_safe("gmail:fetch_gmail_emails",
        "integrations.google.gmail", "Gmail", "fetch_gmail_emails")

    # --- Messaging Integrations ---
    # Microsoft Teams
    registered += _register_safe("microsoft_teams:list_all_teams",
        "integrations.microsoft.microsoft_teams", "MicrosoftTeams", "list_all_teams")
    registered += _register_safe("microsoft_teams:list_channels_from_team",
        "integrations.microsoft.microsoft_teams", "MicrosoftTeams", "list_channels_from_team")
    registered += _register_safe("microsoft_teams:fetch_messages_from_channel",
        "integrations.microsoft.microsoft_teams", "MicrosoftTeams", "fetch_messages_from_channel")
    registered += _register_safe("microsoft_teams:fetch_teams_chats",
        "integrations.microsoft.microsoft_teams", "MicrosoftTeams", "fetch_teams_chats")

    # Slack
    registered += _register_safe("slack:fetch_users_list",
        "integrations.slack.slack_tools", "Slack", "fetch_users_list")
    registered += _register_safe("slack:fetch_channels_list",
        "integrations.slack.slack_tools", "Slack", "fetch_channels_list")
    registered += _register_safe("slack:fetch_messages_in_time_range",
        "integrations.slack.slack_tools", "Slack", "fetch_messages_in_time_range")
    registered += _register_safe("slack:retrieve_slack_conversations",
        "integrations.slack.slack_tools", "Slack", "retrieve_slack_conversations")

    # --- Workflow Management ---
    # Jira
    registered += _register_safe("jira:search_jira_issues",
        "integrations.jira.jira", "Jira", "search_jira_issues")
    registered += _register_safe("jira:search_jira_projects",
        "integrations.jira.jira", "Jira", "search_jira_projects")
    registered += _register_safe("jira:get_jira_project",
        "integrations.jira.jira", "Jira", "get_jira_project")

    # Dex CRM
    registered += _register_safe("dex:list_contacts",
        "integrations.dex.dex", "DexIntegration", "list_contacts")
    registered += _register_safe("dex:get_contact_by_id",
        "integrations.dex.dex", "DexIntegration", "get_contact_by_id")
    registered += _register_safe("dex:search_contact_by_email",
        "integrations.dex.dex", "DexIntegration", "search_contact_by_email")
    registered += _register_safe("dex:list_reminders",
        "integrations.dex.dex", "DexIntegration", "list_reminders")
    registered += _register_safe("dex:list_notes",
        "integrations.dex.dex", "DexIntegration", "list_notes")

    # --- Security Integrations ---
    # CrowdStrike Falcon
    registered += _register_safe("crowdstrike_falcon:get_device_info",
        "integrations.crowdstrike_falson.crowdstrike_falcon", "CrowdStrikeFalcon", "get_device_info_by_id")
    registered += _register_safe("crowdstrike_falcon:get_host_details",
        "integrations.crowdstrike_falson.crowdstrike_falcon", "CrowdStrikeFalcon", "get_host_details")
    registered += _register_safe("crowdstrike_falcon:list_quarantined_hosts",
        "integrations.crowdstrike_falson.crowdstrike_falcon", "CrowdStrikeFalcon", "list_quarantined_hosts")
    registered += _register_safe("crowdstrike_falcon:fetch_incident_ids",
        "integrations.crowdstrike_falson.crowdstrike_falcon", "CrowdStrikeFalcon", "fetch_incident_ids")
    registered += _register_safe("crowdstrike_falcon:fetch_incident_detail",
        "integrations.crowdstrike_falson.crowdstrike_falcon", "CrowdStrikeFalcon", "fetch_incident_detail")
    registered += _register_safe("crowdstrike_falcon:get_vulnerability_list",
        "integrations.crowdstrike_falson.crowdstrike_falcon", "CrowdStrikeFalcon", "get_vulnerability_list")
    registered += _register_safe("crowdstrike_falcon:get_vulnerability_detail",
        "integrations.crowdstrike_falson.crowdstrike_falcon", "CrowdStrikeFalcon", "get_vulnerability_detail")
    registered += _register_safe("crowdstrike_falcon:list_all_alerts",
        "integrations.crowdstrike_falson.crowdstrike_falcon", "CrowdStrikeFalcon", "list_all_alerts")
    registered += _register_safe("crowdstrike_falcon:get_alert_details",
        "integrations.crowdstrike_falson.crowdstrike_falcon", "CrowdStrikeFalcon", "get_alert_details")

    # Rapid7 InsightVM
    registered += _register_safe("rapid7_insightvm:get_all_vulnerabilities",
        "integrations.rapid7_insightvm.rapid7_insightvm", "Rapid7InsightVm", "get_all_vulnerabilities")
    registered += _register_safe("rapid7_insightvm:get_vulnerability_detail",
        "integrations.rapid7_insightvm.rapid7_insightvm", "Rapid7InsightVm", "get_vulnerability_detail")
    registered += _register_safe("rapid7_insightvm:get_overall_vulnerability_posture",
        "integrations.rapid7_insightvm.rapid7_insightvm", "Rapid7InsightVm", "get_overall_vulnerability_posture")

    # Microsoft Defender
    registered += _register_safe("microsoft_defender:get_all_alerts",
        "integrations.microsoft_defender.microsoft_defender", "MicrosoftDefender", "get_all_alerts")
    registered += _register_safe("microsoft_defender:get_alert_details",
        "integrations.microsoft_defender.microsoft_defender", "MicrosoftDefender", "get_alert_details")
    registered += _register_safe("microsoft_defender:get_all_incidents",
        "integrations.microsoft_defender.microsoft_defender", "MicrosoftDefender", "get_all_incidents")
    registered += _register_safe("microsoft_defender:get_incident_details",
        "integrations.microsoft_defender.microsoft_defender", "MicrosoftDefender", "get_incident_details")
    registered += _register_safe("microsoft_defender:get_all_devices",
        "integrations.microsoft_defender.microsoft_defender", "MicrosoftDefender", "get_all_devices")
    registered += _register_safe("microsoft_defender:get_device_details",
        "integrations.microsoft_defender.microsoft_defender", "MicrosoftDefender", "get_device_details")
    registered += _register_safe("microsoft_defender:get_quarantined_assets",
        "integrations.microsoft_defender.microsoft_defender", "MicrosoftDefender", "get_quarantined_assets")

    # Qualys
    registered += _register_safe("qualys:list_vm_scans",
        "integrations.qualys.qualys", "Qualys", "list_vm_scans")
    registered += _register_safe("qualys:get_vm_scan_summary",
        "integrations.qualys.qualys", "Qualys", "get_vm_scan_summary")
    registered += _register_safe("qualys:get_scan_summary",
        "integrations.qualys.qualys", "Qualys", "get_scan_summary")
    registered += _register_safe("qualys:list_hosts",
        "integrations.qualys.qualys", "Qualys", "list_hosts")
    registered += _register_safe("qualys:list_excluded_hosts",
        "integrations.qualys.qualys", "Qualys", "list_excluded_hosts")
    registered += _register_safe("qualys:list_restricted_ips",
        "integrations.qualys.qualys", "Qualys", "list_restricted_ips")
    registered += _register_safe("qualys:list_reports",
        "integrations.qualys.qualys", "Qualys", "list_reports")
    registered += _register_safe("qualys:download_saved_report",
        "integrations.qualys.qualys", "Qualys", "download_saved_report")
    registered += _register_safe("qualys:list_remediation_tickets",
        "integrations.qualys.qualys", "Qualys", "list_remediation_tickets")
    registered += _register_safe("qualys:get_remediation_ticket",
        "integrations.qualys.qualys", "Qualys", "get_remediation_ticket")
    registered += _register_safe("qualys:list_compliance_controls",
        "integrations.qualys.qualys", "Qualys", "list_compliance_controls")
    registered += _register_safe("qualys:list_compliance_policies",
        "integrations.qualys.qualys", "Qualys", "list_compliance_policies")
    registered += _register_safe("qualys:list_users",
        "integrations.qualys.qualys", "Qualys", "list_users")
    registered += _register_safe("qualys:list_host_vm_detection",
        "integrations.qualys.qualys", "Qualys", "list_host_vm_detection")

    # --- Content Management & Storage ---
    # Microsoft SharePoint
    registered += _register_safe("microsoft_sharepoint:search_sharepoint",
        "integrations.microsoft.microsoft_sharepoint", "MicrosoftSharePoint", "search_sharepoint")
    registered += _register_safe("microsoft_sharepoint:search_with_filters",
        "integrations.microsoft.microsoft_sharepoint", "MicrosoftSharePoint", "search_with_filters")
    registered += _register_safe("microsoft_sharepoint:get_file_content",
        "integrations.microsoft.microsoft_sharepoint", "MicrosoftSharePoint", "get_file_content")
    registered += _register_safe("microsoft_sharepoint:get_file_content_as_pdf",
        "integrations.microsoft.microsoft_sharepoint", "MicrosoftSharePoint", "get_file_content_as_pdf")
    registered += _register_safe("microsoft_sharepoint:list_sites",
        "integrations.microsoft.microsoft_sharepoint", "MicrosoftSharePoint", "list_sites")
    registered += _register_safe("microsoft_sharepoint:get_recent_files",
        "integrations.microsoft.microsoft_sharepoint", "MicrosoftSharePoint", "get_recent_files")

    # Google Drive
    registered += _register_safe("google_drive:search_drive",
        "integrations.google.google_drive", "GoogleDrive", "search_drive")
    registered += _register_safe("google_drive:get_file_content",
        "integrations.google.google_drive", "GoogleDrive", "get_file_content")
    registered += _register_safe("google_drive:search_with_filters",
        "integrations.google.google_drive", "GoogleDrive", "search_with_filters")
    registered += _register_safe("google_drive:list_folders",
        "integrations.google.google_drive", "GoogleDrive", "list_folders")
    registered += _register_safe("google_drive:get_recent_files",
        "integrations.google.google_drive", "GoogleDrive", "get_recent_files")

    # Notion
    registered += _register_safe("notion:search_pages",
        "integrations.notion.notion", "NotionIntegration", "search_pages")
    registered += _register_safe("notion:get_page",
        "integrations.notion.notion", "NotionIntegration", "get_page")
    registered += _register_safe("notion:get_page_content",
        "integrations.notion.notion", "NotionIntegration", "get_page_content")
    registered += _register_safe("notion:get_database",
        "integrations.notion.notion", "NotionIntegration", "get_database")
    registered += _register_safe("notion:query_database",
        "integrations.notion.notion", "NotionIntegration", "query_database")
    registered += _register_safe("notion:get_block",
        "integrations.notion.notion", "NotionIntegration", "get_block")
    registered += _register_safe("notion:get_block_children",
        "integrations.notion.notion", "NotionIntegration", "get_block_children")

    # --- Developer Tools ---
    # GitHub
    registered += _register_safe("github:list_repositories",
        "integrations.github.github", "GitHub", "list_repositories")
    registered += _register_safe("github:get_repository",
        "integrations.github.github", "GitHub", "get_repository")
    registered += _register_safe("github:search_repositories",
        "integrations.github.github", "GitHub", "search_repositories")
    registered += _register_safe("github:list_issues",
        "integrations.github.github", "GitHub", "list_issues")
    registered += _register_safe("github:get_issue",
        "integrations.github.github", "GitHub", "get_issue")
    registered += _register_safe("github:list_pull_requests",
        "integrations.github.github", "GitHub", "list_pull_requests")
    registered += _register_safe("github:get_pull_request",
        "integrations.github.github", "GitHub", "get_pull_request")
    registered += _register_safe("github:list_commits",
        "integrations.github.github", "GitHub", "list_commits")
    registered += _register_safe("github:get_commit",
        "integrations.github.github", "GitHub", "get_commit")
    registered += _register_safe("github:list_organizations",
        "integrations.github.github", "GitHub", "list_organizations")
    registered += _register_safe("github:get_organization",
        "integrations.github.github", "GitHub", "get_organization")
    registered += _register_safe("github:list_org_members",
        "integrations.github.github", "GitHub", "list_org_members")
    registered += _register_safe("github:get_org_member",
        "integrations.github.github", "GitHub", "get_org_member")
    registered += _register_safe("github:get_org_security_settings",
        "integrations.github.github", "GitHub", "get_org_security_settings")
    registered += _register_safe("github:list_repo_collaborators",
        "integrations.github.github", "GitHub", "list_repo_collaborators")
    registered += _register_safe("github:list_branches",
        "integrations.github.github", "GitHub", "list_branches")
    registered += _register_safe("github:get_branch_protection",
        "integrations.github.github", "GitHub", "get_branch_protection")
    registered += _register_safe("github:list_pull_request_reviews",
        "integrations.github.github", "GitHub", "list_pull_request_reviews")
    registered += _register_safe("github:list_dependabot_alerts",
        "integrations.github.github", "GitHub", "list_dependabot_alerts")
    registered += _register_safe("github:list_code_scanning_alerts",
        "integrations.github.github", "GitHub", "list_code_scanning_alerts")
    registered += _register_safe("github:list_secret_scanning_alerts",
        "integrations.github.github", "GitHub", "list_secret_scanning_alerts")
    registered += _register_safe("github:get_file",
        "integrations.github.github", "GitHub", "get_file")
    registered += _register_safe("github:list_workflows",
        "integrations.github.github", "GitHub", "list_workflows")
    registered += _register_safe("github:list_workflow_runs",
        "integrations.github.github", "GitHub", "list_workflow_runs")
    registered += _register_safe("github:list_team_repos",
        "integrations.github.github", "GitHub", "list_team_repos")
    registered += _register_safe("github:list_tags",
        "integrations.github.github", "GitHub", "list_tags")
    registered += _register_safe("github:list_releases",
        "integrations.github.github", "GitHub", "list_releases")
    registered += _register_safe("github:list_audit_log_events",
        "integrations.github.github", "GitHub", "list_audit_log_events")

    # --- GRC / Compliance ---
    # Vanta
    registered += _register_safe("vanta:list_controls",
        "integrations.vanta.vanta", "Vanta", "list_controls")
    registered += _register_safe("vanta:get_control_by_id",
        "integrations.vanta.vanta", "Vanta", "get_control_by_id")
    registered += _register_safe("vanta:list_tests",
        "integrations.vanta.vanta", "Vanta", "list_tests")
    registered += _register_safe("vanta:get_test_by_id",
        "integrations.vanta.vanta", "Vanta", "get_test_by_id")
    registered += _register_safe("vanta:list_people",
        "integrations.vanta.vanta", "Vanta", "list_people")
    registered += _register_safe("vanta:get_people_by_id",
        "integrations.vanta.vanta", "Vanta", "get_people_by_id")
    registered += _register_safe("vanta:list_vulnerabilities",
        "integrations.vanta.vanta", "Vanta", "list_vulnerabilities")
    registered += _register_safe("vanta:get_vulnerability_by_id",
        "integrations.vanta.vanta", "Vanta", "get_vulnerability_by_id")
    registered += _register_safe("vanta:list_frameworks",
        "integrations.vanta.vanta", "Vanta", "list_frameworks")
    registered += _register_safe("vanta:get_framework",
        "integrations.vanta.vanta", "Vanta", "get_framework")
    registered += _register_safe("vanta:list_policies",
        "integrations.vanta.vanta", "Vanta", "list_policies")
    registered += _register_safe("vanta:get_policy",
        "integrations.vanta.vanta", "Vanta", "get_policy")

    # --- Industry Intelligence ---
    registered += _register_safe("industry_intelligence:get_current_threat_intel",
        "integrations.industry_intelligence.rss_feeds", "RssFeeds", "get_current_threat_intel")

    # --- Alignment Tool ---
    registered += _register_safe("alignment_tool",
        "integrations.alignment.alignment_tool", None, "document_aligner",
        is_function=True)

    logger.info(f"Integration tool registration complete: {registered} registered, {failed} failed")
    return registered


# Instance cache to avoid creating multiple instances of the same class
_instance_cache: dict[str, object] = {}


def _register_safe(
    tool_name: str,
    module_path: str,
    class_name: str | None,
    method_name: str,
    is_function: bool = False,
) -> int:
    """
    Safely register a single integration tool.

    Returns 1 on success, 0 on failure (import errors, missing methods, etc.)
    Failures are logged as warnings — they don't prevent other tools from registering.
    """
    try:
        import importlib
        module = importlib.import_module(module_path)

        if is_function:
            # Direct function reference (not a class method)
            func = getattr(module, method_name)
        else:
            # Get or create class instance
            cache_key = f"{module_path}.{class_name}"
            if cache_key not in _instance_cache:
                cls = getattr(module, class_name)
                _instance_cache[cache_key] = cls()
            instance = _instance_cache[cache_key]
            func = getattr(instance, method_name)

        register_tool(tool_name, func)
        return 1

    except ImportError as e:
        logger.warning(f"Could not import {module_path} for tool {tool_name}: {e}")
        return 0
    except AttributeError as e:
        logger.warning(f"Missing attribute for tool {tool_name}: {e}")
        return 0
    except Exception as e:
        logger.warning(f"Failed to register tool {tool_name}: {e}")
        return 0
