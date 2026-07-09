"""Realistic cross-domain distractor tools (the many-servers regime).

A production MCP host is wired to many servers at once -- calendar, mail, CRM, issue
tracking, travel, banking, smart home, file storage -- and almost all of their tools are
irrelevant to any one session. To make the many-tools condition *representative* rather
than synthetic, distractors are drawn from realistic tool templates across such domains
(plausible names, descriptions, and parameter schemas), instantiated per service so that
tool counts can scale to the thousands. Their guards are False in this session -- exactly
the situation of tools that belong to other services' application states -- so flat
advertises them all, retrieval may surface them, and a SEM never exposes them.
"""
from __future__ import annotations
import dataclasses
from .core import Affordance, Env

_STR = {"type": "string"}

# (verb-name, description, params) templates per domain.
_DOMAINS = {
    "calendar": [
        ("create_event", "Create a calendar event with title, start, and end time.",
         {"title": _STR, "start": _STR, "end": _STR}),
        ("list_events", "List calendar events in a date range.",
         {"from": _STR, "to": _STR}),
        ("delete_event", "Delete a calendar event by id.", {"event_id": _STR}),
        ("set_reminder", "Set a reminder for an event.", {"event_id": _STR,
                                                          "minutes_before": _STR}),
    ],
    "mail": [
        ("send_email", "Send an email to a recipient with subject and body.",
         {"to": _STR, "subject": _STR, "body": _STR}),
        ("search_inbox", "Search the mailbox for messages matching a query.",
         {"query": _STR}),
        ("archive_thread", "Archive a conversation thread.", {"thread_id": _STR}),
    ],
    "crm": [
        ("create_lead", "Create a sales lead with contact details.",
         {"name": _STR, "company": _STR}),
        ("update_opportunity", "Update the stage of a sales opportunity.",
         {"opportunity_id": _STR, "stage": _STR}),
        ("log_call", "Log a customer call against an account.",
         {"account_id": _STR, "notes": _STR}),
    ],
    "issues": [
        ("create_ticket", "Open an issue ticket with a title and description.",
         {"title": _STR, "description": _STR}),
        ("assign_ticket", "Assign a ticket to a team member.",
         {"ticket_id": _STR, "assignee": _STR}),
        ("transition_ticket", "Move a ticket to another workflow state.",
         {"ticket_id": _STR, "state": _STR}),
    ],
    "travel": [
        ("search_flights", "Search flights between two airports on a date.",
         {"from": _STR, "to": _STR, "date": _STR}),
        ("book_hotel", "Book a hotel room in a city for a date range.",
         {"city": _STR, "check_in": _STR, "check_out": _STR}),
        ("cancel_reservation", "Cancel a travel reservation by id.",
         {"reservation_id": _STR}),
    ],
    "banking": [
        ("get_balance", "Show the balance of a bank account.", {"account_id": _STR}),
        ("transfer_funds", "Transfer funds between two accounts.",
         {"from_account": _STR, "to_account": _STR, "amount": _STR}),
        ("list_transactions", "List recent transactions of an account.",
         {"account_id": _STR}),
    ],
    "smarthome": [
        ("set_thermostat", "Set the target temperature of a thermostat.",
         {"device_id": _STR, "celsius": _STR}),
        ("toggle_light", "Switch a light on or off.", {"device_id": _STR, "on": _STR}),
        ("lock_front_door", "Lock or unlock the front door.", {"locked": _STR}),
    ],
    "files": [
        ("upload_file", "Upload a file to cloud storage.", {"path": _STR}),
        ("share_document", "Share a document with a user.",
         {"document_id": _STR, "user": _STR}),
        ("search_documents", "Full-text search across stored documents.",
         {"query": _STR}),
    ],
}

_SERVICES = ["acme", "globex", "initech", "umbrella", "hooli", "stark", "wayne",
             "tyrell", "cyberdyne", "aperture", "monarch", "vandelay", "wonka",
             "oscorp", "dunder", "pied", "prestige", "soylent", "massive", "virtucon"]


def distractor_pool(n: int) -> list[Affordance]:
    """Deterministically generate n realistic other-service tools (guards False here)."""
    out: list[Affordance] = []
    templates = [(dom, t) for dom, ts in _DOMAINS.items() for t in ts]
    i = 0
    while len(out) < n:
        service = _SERVICES[(i // len(templates)) % len(_SERVICES)]
        suffix = i // (len(templates) * len(_SERVICES))
        dom, (verb, desc, props) = templates[i % len(templates)]
        name = f"{service}_{dom}_{verb}" + (f"_{suffix}" if suffix else "")
        out.append(Affordance(
            name, f"[{service} {dom}] {desc}",
            {"type": "object", "properties": dict(props)},
            guard=lambda s, a: False,          # belongs to another service's session
            effect=lambda s, a: "noop", rel="action"))
        i += 1
    return out


def pad(env: Env, n: int) -> Env:
    """Return env extended with n realistic cross-service distractor tools."""
    if n <= 0:
        return env
    return dataclasses.replace(
        env, affordances=list(env.affordances) + distractor_pool(n))
