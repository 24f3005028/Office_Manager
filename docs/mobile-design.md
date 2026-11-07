# Mobile experience

The home screen prioritises the office's daily work: a live task summary, party
statements, bill lookup and two compact office shortcuts. The hamburger drawer
groups Reports, Team & office and Settings. Existing task forms and office requests
remain mounted so changing sections does not discard a draft or restart a request.

The visual system uses a consistent navy and blue palette, circular icon surfaces,
rounded cards, readable text and 48 dp or larger action targets. Optional explanations
use disclosures; errors, task results and confirmations stay visible. Task cards show
the title, deadline and completion control first, with details and management actions
below. Home supports pull-to-refresh and reports connection failures without inventing
an empty task count.

The supplied logo is preserved inside a padded circular badge. The same badge supplies
the launcher, native splash and app logo. `expo-splash-screen` holds the native launch
screen until SecureStore restoration and the first app layout complete; there is no
second JavaScript splash or startup spinner.

## Task widget

- Each visible task has a 48 dp completion target. Tapping it opens an Android
  confirmation above the home screen, including an explanation for repeating tasks.
- Add task opens a new task form and preserves an existing draft. Open tasks opens
  the list. Refresh fetches the current task list without desktop/BUSY operations.
- Completion re-reads server state and sends the displayed task version. Duplicate
  taps or stale tasks cannot advance another occurrence. Ambiguous writes are never
  retried automatically. Results come from a subsequent server read.
- Network work runs in WorkManager. Pending actions are bound to the original
  connection fingerprint. Credentials are encrypted using Android Keystore AES-GCM
  in no-backup storage, separate from the display snapshot and widget intents.
- Logout/expiry clears native credentials and task snapshots. Late responses cannot
  overwrite a newer snapshot or restore logged-out data. Authentication failure clears
  the widget. Offline failures retain the last verified list and show a status message.
- Completing a task cancels this phone's scheduled reminder for that occurrence;
  normal reminder reconciliation retains subsequent repeating occurrences.
- Compact widgets show fewer rows, rather than shrinking controls below 48 dp.

## PDF viewing

Every Open PDF button uses the same download-and-view path: party statements,
all-account reports, statement activity and saved bill PDFs. Android opens a local
`content://` URI through Google Drive's PDF viewer when available, or another
registered PDF viewer if Drive is unavailable. The intent grants read access only;
it contains no office URL, bearer token or write permission. The print API and its
package have been removed. Share and Download remain separate actions.

The native viewer uses Android's standard `ACTION_VIEW` and `application/pdf`, with
the app's FileProvider. See [Android file sharing](https://developer.android.com/training/secure-file-sharing/share-file).

## Copy account and group balances

The Reports drawer and home shortcut open two focused options. Copy account allows
searching the account catalogue, optionally within one named group, then choosing
From and Through dates. Defaults come from the office's current Indian financial
year. The form and its dates survive navigation between sections.

Group balances asks for one group and an as-of date within the current financial
year. Group names come from the owner's Name column, with exact membership from
the imported account list; parent categories are not substituted. The resulting
list shows each nonzero account, debit and credit totals, search and pagination.
Tapping an account opens its Copy account form. A PDF uses the same reconciled
rows as the in-app view.

Tapping Create report submits directly, without a second mobile confirmation. Both use the existing
five-second office warning and shared BUSY desktop lock. Progress reads never
start exports. BUSY report settings are set and checked before export, and group
totals must reconcile before a result becomes available. Temporary Excel files
are removed after parsing, including failures. PDFs and private balance snapshots
follow the existing 48-hour availability and cleanup policy.

The catalogue stores only names and group membership in the dashboard's own
database. Import it with `python -m scripts.import_mobile_accounts <xlsx-path>`
from the backend directory; the existing trade-party list remains compatible.
BUSY's database is never accessed.

## Loading and sharing

All in-app loading indicators use the same indeterminate yarn-style progress
bar: diagonal strands travel horizontally along a track. Long operations show
elapsed time after five seconds, alongside the actual report status. No estimated
completion percentage is displayed. Reduced-motion settings disable the animation.
Task refresh, account searches, document requests, office work, invites and widget
actions share this component. Native launch remains the branded splash screen.

PDF actions are Open, Download and Share. Sharing opens the phone's share sheet,
where WhatsApp and other apps are available. The separate Send to my WhatsApp
button has been removed; the office bill-sending tool remains available.

## Design references

Applied guidance from [Android widget design](https://developer.android.com/design/ui/mobile/guides/widgets)
and [widget updates](https://developer.android.com/develop/ui/views/appwidgets/advanced)
for focused actions, sizing and background work; [Material interaction](https://m3.material.io/foundations/interaction)
for consistent controls; and [Android launch screens](https://developer.android.com/develop/ui/views/launch/splash-screen)
plus [Expo splash configuration](https://docs.expo.dev/versions/latest/sdk/splash-screen/)
for one branded startup experience.
