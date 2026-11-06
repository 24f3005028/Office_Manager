# Mobile workflow and next features

## Implemented in 1.3.0

Home has four direct routes: Outstanding statement, Find a bill, Office tools and Shared tasks.
Office tools opens a menu rather than immediately showing a large form. Statements use
Party → Create → PDF. Bill sending uses Documents → Recipient → Review, with a final
confirmation before sending. Activity has separate Statements and Office requests views.
Office and task forms stay mounted while changing tabs; bill searches and selected years
are preserved. Android Back and the visible Back control walk back through the task.
Account closes to the screen it was opened from. Icon backgrounds are circular or rounded
pills, with clipping so the selected navigation background cannot draw square corners.

Android date/time pickers replace typed dates in statements, Pouncha, sending filters and
task deadlines. Web preview retains text fields. All task deadlines use Asia/Kolkata.

## Shared tasks

Every approved user can create a common task or mark it done. A task has a title, optional
notes, deadline, selected reminder recipients and a Once/Daily/Weekly/Monthly repeat.
The creator or designated office manager may edit/cancel it; all users can see it.
Names are exposed for recipient selection, without sharing users' phone numbers.

Completing a repeating task advances its due date to the next future occurrence and
records who completed it. Missed occurrences are skipped. Monthly tasks preserve their
original day: 31 January → 28 February → 31 March. Simultaneous completions from two
phones cannot advance the same occurrence twice. Creation keys prevent duplicate tasks
if a confirmation is lost. Cancellation is soft, with an audit event retained.

Open tasks are limited to 200 for the office; the list includes up to 1,000 open/completed
records. The limit gives a clear error instead of silently dropping open tasks.

## Phone reminders

On each phone, open Shared tasks → Enable phone reminders, allow Android notifications,
then use Test notification. Only the selected recipients' enabled phones schedule reminders.
The phone schedules at most 50 of the nearest reminders, up to eight occurrences per task,
and never schedules beyond its authenticated session expiry. Foreground/background refresh
reconciles edits, completion, cancellation and recipient changes. Logging out disables
background refresh and clears pending notifications.

Android WorkManager periodically reads only `/me` and `/tasks` over private Tailscale.
It never invokes BUSY, syncs a sheet or sends WhatsApp messages. No office-PC scheduler
was added. Synced local reminders can run offline. New/changed tasks require a successful
refresh from the office. Android schedules background refresh opportunistically at least
15 minutes apart; battery restrictions, force-stop and lost Tailscale/office connectivity
can delay changes and notifications. This is not instant remote push and not an exact
alarm service. Local delivery uses best-effort alarms without asking for exact-alarm access.
Native delivery must be verified on the user's physical phone using Test notification.

References: [Expo BackgroundTask](https://docs.expo.dev/versions/latest/sdk/background-task/),
[Expo Notifications](https://docs.expo.dev/versions/latest/sdk/notifications/).

## Agreed next priority: party page (proposal, not implemented)

The user selected a unified party page, showing **all saved bills plus a separate
outstanding-statement section**. Proposed journey:

1. Search/select a party once.
2. See their latest statement with its actual as-of date and an explicit Refresh statement action.
3. Browse saved bills by financial year, bill number and date; open/download/share each PDF.
4. See the current user's statement and sending history for that party.

Archived PDFs alone do not establish whether a bill is unpaid. Paid/unpaid labels must come
from a validated outstanding report, with an as-of date. Match archive party names exactly;
where historical spellings differ, use reviewed aliases rather than fuzzy matches that could
show another party's invoices. Do not broaden employees' access to other users' private
request history implicitly. Existing all-party access remains unchanged.

## Other features to discuss

| Priority | Proposal | Why it could help |
| --- | --- | --- |
| Next after party page | Collections follow-up notes and promised payment date | Record who called, what the customer promised and the next follow-up, attached to the party. These are office notes, not accounting payment entries. |
| Next | Ageing summary | Group validated outstanding bills into overdue bands, always with a report date. Requires structured data from a supported export, not assumptions from saved invoices. |
| Next | Manual WhatsApp message templates | Choose a polite statement/reminder/delivery message and review it before sending. No automatic customer messaging. |
| Later | Office connection/status panel | One view for gateway, WhatsApp and last successful requests, with clear recovery actions. BUSY screen inspection would remain explicitly requested. |

Research: [Zoho Books receivables reports](https://www.zoho.com/en-sg/books/help/reports/receivables.html)
describes customer balance and ageing reports; [BUSY outstanding-analysis help](https://busy.in/faqs/accounting-reports/outstanding-analysis/34/)
describes payment reminder workflows. The priorities above are recommendations for this
office's workflow, not claims that those vendors' integrations are installed.
