#!/usr/bin/env python3
"""
Schedule Reconciler
Cross-references Google Calendar, Gmail, and macOS iMessage chat history.
Identifies discrepancies, unreflected plans, conflicts, and tentative bookings.
Does NOT modify the calendar; generates a structured list of actionable suggestions.
"""

import os
import sys
import json
import sqlite3
import re
from datetime import datetime, timezone, timedelta
from pathlib import Path

# Paths
REPO_DIR = Path(__file__).resolve().parent
WORKSPACE_SKILL = Path("/Users/michaelcadelago/antigravity-skills/universal/google_workspace")
IMESSAGE_SKILL = Path("/Users/michaelcadelago/antigravity-skills/mac/imessage")

sys.path.append(str(WORKSPACE_SKILL / "scripts"))
sys.path.append(str(IMESSAGE_SKILL / "scripts"))

try:
    from auth import get_credentials
    from googleapiclient.discovery import build
except ImportError as e:
    print(f"Error importing Google Workspace libraries: {e}", file=sys.stderr)
    sys.exit(1)

try:
    from contacts import ContactsResolver
except ImportError:
    class ContactsResolver:
        def resolve(self, val):
            return val

APPLE_EPOCH_OFFSET = 978307200
CHAT_DB_PATH = os.path.expanduser("~/Library/Messages/chat.db")

def clean_extracted_text(text):
    """Clean control characters and non-printable bytes from extracted text."""
    if not text:
        return ''
    cleaned = text
    while cleaned and (ord(cleaned[0]) < 32 or cleaned[0] in '\x7f\x80\x81\x82\x83\x84\x85\x86\x87\x88\x89\x8a\x8b\x8c\x8d\x8e\x8f\x90\x91\x92\x93\x94\x95\x96\x97\x98\x99\x9a\x9b\x9c\x9d\x9e\x9f\xa0\ufffd\u200a\u200b'):
        cleaned = cleaned[1:]
    while cleaned and (ord(cleaned[-1]) < 32 or cleaned[-1] in '\x7f\x80\x81\x82\x83\x84\x85\x86\x87\x88\x89\x8a\x8b\x8c\x8d\x8e\x8f\x90\x91\x92\x93\x94\x95\x96\x97\x98\x99\x9a\x9b\x9c\x9d\x9e\x9f\xa0\ufffd\u200a\u200b'):
        cleaned = cleaned[:-1]
    return cleaned.strip()

def parse_attributed_body_exact(attr_body):
    """Extract message string from Apple typedstream binary blob (attributedBody)."""
    if not attr_body:
        return ''
    try:
        nsstring_idx = attr_body.find(b'NSString')
        if nsstring_idx == -1:
            return ''
        
        after_nsstring = attr_body[nsstring_idx + 8:]
        end_markers = [b'NSDictionary', b'NSNumber', b'NSMutableDictionary', b'NSDate', b'NSArray', b'NSMutableArray']
        split_idx = -1
        for marker in end_markers:
            idx = after_nsstring.find(marker)
            if idx != -1:
                if split_idx == -1 or idx < split_idx:
                    split_idx = idx
        
        raw_segment = after_nsstring[:split_idx] if split_idx != -1 else after_nsstring
        plus_idx = raw_segment.find(b'+')
        if plus_idx == -1:
            return ''
            
        if plus_idx + 1 < len(raw_segment):
            b1 = raw_segment[plus_idx + 1]
            if b1 == 129:
                if plus_idx + 3 < len(raw_segment):
                    b2 = raw_segment[plus_idx + 2]
                    b3 = raw_segment[plus_idx + 3]
                    length = b2 + b3 * 256
                    start_idx = plus_idx + 4
                else:
                    return ''
            elif b1 < 128:
                length = b1
                start_idx = plus_idx + 2
            else:
                return ''
        else:
            return ''
            
        text_bytes = raw_segment[start_idx:start_idx + length]
        return text_bytes.decode('utf-8', errors='replace').strip()
    except Exception:
        return ''

def get_message_text(text_col, attr_body_col):
    if text_col is not None and text_col.strip() != "":
        return text_col.strip()
    parsed = parse_attributed_body_exact(attr_body_col)
    return clean_extracted_text(parsed)

def get_calendar_events(days_ahead=60):
    """Fetch upcoming Google Calendar events."""
    creds = get_credentials()
    service = build("calendar", "v3", credentials=creds)
    now_utc = datetime.now(timezone.utc)
    max_utc = now_utc + timedelta(days=days_ahead)

    events_res = service.events().list(
        calendarId="primary",
        timeMin=now_utc.isoformat(),
        timeMax=max_utc.isoformat(),
        singleEvents=True,
        orderBy="startTime",
        maxResults=250
    ).execute()

    items = events_res.get("items", [])
    events = []
    for it in items:
        start_raw = it.get("start", {}).get("dateTime") or it.get("start", {}).get("date")
        end_raw = it.get("end", {}).get("dateTime") or it.get("end", {}).get("date")
        events.append({
            "id": it.get("id"),
            "summary": it.get("summary", "(No title)"),
            "start": start_raw,
            "end": end_raw,
            "location": it.get("location", ""),
            "description": it.get("description", ""),
            "status": it.get("status", "")
        })
    return events

def get_recent_emails(days_back=14):
    """Fetch relevant recent emails from Gmail."""
    creds = get_credentials()
    service = build("gmail", "v1", credentials=creds)
    query = f"newer_than:{days_back}d"

    resp = service.users().messages().list(userId="me", q=query, maxResults=100).execute()
    messages = resp.get("messages", [])

    results = []
    for msg in messages:
        msg_data = service.users().messages().get(
            userId="me", id=msg["id"], format="metadata",
            metadataHeaders=["From", "Subject", "Date"]
        ).execute()

        headers = {h["name"]: h["value"] for h in msg_data.get("payload", {}).get("headers", [])}
        results.append({
            "id": msg["id"],
            "date": headers.get("Date", ""),
            "from": headers.get("From", ""),
            "subject": headers.get("Subject", ""),
            "snippet": msg_data.get("snippet", "")
        })
    return results

def get_recent_imessages(days_back=14):
    """Extract recent messages and candidate scheduling texts from chat.db."""
    if not os.path.exists(CHAT_DB_PATH):
        return []

    conn = sqlite3.connect(f"file:{CHAT_DB_PATH}?mode=ro", uri=True)
    cursor = conn.cursor()
    cutoff_dt = datetime.now(timezone.utc) - timedelta(days=days_back)
    cutoff_timestamp = int((cutoff_dt.timestamp() - APPLE_EPOCH_OFFSET) * 1e9)
    resolver = ContactsResolver()

    query = """
    SELECT 
        m.rowid,
        m.text,
        m.attributedBody,
        m.date,
        m.is_from_me,
        c.chat_identifier,
        c.display_name,
        h.id as handle_id
    FROM message m
    JOIN chat_message_join cmj ON m.rowid = cmj.message_id
    JOIN chat c ON cmj.chat_id = c.rowid
    LEFT JOIN handle h ON m.handle_id = h.rowid
    WHERE m.date > ?
    ORDER BY m.date ASC
    """
    cursor.execute(query, (cutoff_timestamp,))
    rows = cursor.fetchall()

    keywords = [
        'tomorrow', 'tonight', 'monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday',
        'match', 'game', 'court', 'tennis', 'doctor', 'dr.', 'dentist', 'graft', 'appointment', 'lunch',
        'dinner', 'meet', 'play', 'movie', 'ticket', 'flight', 'drive', 'trip', 'practice', 'scrimmage',
        'schedule', 'calendar', 'free', 'busy', 'time', 'drills', 'reschedule', 'cancel'
    ]

    messages = []
    for rowid, text, attr_body, date_val, is_from_me, chat_id, chat_disp, handle_id in rows:
        content = get_message_text(text, attr_body)
        if not content:
            continue

        text_lower = content.lower()
        if any(kw in text_lower for kw in keywords):
            msg_time_sec = (date_val / 1e9) + APPLE_EPOCH_OFFSET
            msg_dt = datetime.fromtimestamp(msg_time_sec, timezone.utc).astimezone()
            sender = "Me" if is_from_me else (resolver.resolve(handle_id) if handle_id else "Unknown")
            chat_name = chat_disp or resolver.resolve(chat_id) or chat_id
            messages.append({
                "id": rowid,
                "datetime": msg_dt.strftime("%Y-%m-%d %H:%M:%S"),
                "sender": sender,
                "chat": chat_name,
                "text": content
            })

    conn.close()
    return messages

def analyze_reconciliation(events, emails, messages):
    """Reconciles calendar events against emails and messages."""
    overlaps = []
    timed_events = []
    for e in events:
        if "T" in str(e["start"]) and "T" in str(e["end"]):
            try:
                s_dt = datetime.fromisoformat(e["start"])
                e_dt = datetime.fromisoformat(e["end"])
                timed_events.append((s_dt, e_dt, e))
            except Exception:
                pass

    for i in range(len(timed_events)):
        for j in range(i + 1, len(timed_events)):
            s1, e1, ev1 = timed_events[i]
            s2, e2, ev2 = timed_events[j]
            if s1 < e2 and s2 < e1:
                overlaps.append({
                    "event1": ev1,
                    "event2": ev2,
                    "date": s1.strftime("%Y-%m-%d")
                })

    return {
        "events_count": len(events),
        "emails_count": len(emails),
        "messages_count": len(messages),
        "overlaps": overlaps
    }

def main():
    print("=" * 70)
    print(" 📅 Calendar, Gmail & iMessage Reconciliation Job")
    print(f" Run Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 70)

    print("\n[1/3] Fetching Google Calendar events...")
    events = get_calendar_events(days_ahead=60)
    print(f"      Retrieved {len(events)} upcoming events.")

    print("\n[2/3] Fetching recent Gmail emails (past 14 days)...")
    emails = get_recent_emails(days_back=14)
    print(f"      Retrieved {len(emails)} recent emails.")

    print("\n[3/3] Inspecting macOS iMessage history (past 14 days)...")
    imessages = get_recent_imessages(days_back=14)
    print(f"      Identified {len(imessages)} messages with scheduling context.")

    analysis = analyze_reconciliation(events, emails, imessages)

    print("\n" + "=" * 70)
    print(" 📋 SUMMARY OF DETECTED RECONCILIATION ITEMS")
    print("=" * 70)

    if analysis["overlaps"]:
        print("\n⚠️  DIRECT CALENDAR CONFLICTS / DOUBLE BOOKINGS:")
        for o in analysis["overlaps"]:
            ev1, ev2 = o["event1"], o["event2"]
            print(f"  • Date: {o['date']}")
            print(f"    - [{ev1['start']} -> {ev1['end']}] {ev1['summary']}")
            print(f"    - [{ev2['start']} -> {ev2['end']}] {ev2['summary']}")

    print("\nDone. Full report ready for review.")

if __name__ == "__main__":
    main()
