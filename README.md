# Schedule Reconciler (Gmail, iMessage, Google Calendar)

A tool designed to cross-reference your **Google Calendar**, **Gmail**, and macOS **iMessage** conversation history to identify unreflected plans, scheduling discrepancies, double bookings, and pending appointments.

> [!IMPORTANT]
> This tool is strictly read-only with respect to your calendar. It will never add, edit, or delete events automatically. It generates structured recommendations for your review and approval.

---

## What It Checks

1. **Google Calendar**: Retrieves upcoming events (next 60 days) and analyzes timing, durations, and potential double-bookings.
2. **Gmail**: Searches recent emails (past 14 days) for appointments, bookings, event tickets, league match lineups, and schedule changes.
3. **iMessage (`chat.db`)**: Analyzes recent conversations for plans with friends, drills, match arrangements, travel talk, and pending dates.

---

## How to Run

Execute the runner script directly from the terminal:

```bash
./run_reconciliation.sh
```

Or run via Python:

```bash
/Users/michaelcadelago/antigravity-skills/universal/google_workspace/.venv/bin/python reconcile_schedule.py
```

---

## How to Schedule Recurring Runs

### Option 1: Via Antigravity Chat
You can schedule recurring execution by asking the assistant or using the `/schedule` slash command:
- e.g. *"Run schedule reconciliation every morning at 8 AM"*

### Option 2: macOS Crontab
To run daily at 8:00 AM:
```bash
crontab -e
```
Add:
```cron
0 8 * * * /Users/michaelcadelago/Documents/antigravity/kind-shannon/run_reconciliation.sh >> /Users/michaelcadelago/Documents/antigravity/kind-shannon/reconciliation.log 2>&1
```
