# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

PibiCal is a Frappe app that provides bidirectional synchronization between Frappe/ERPNext events and CalDAV calendar servers (primarily NextCloud). It only syncs public events and supports features like recurring events, participants, and meeting minutes.

## Development Commands

```bash
# Install app in development
bench get-app pibical https://github.com/pibico/pibical.git --branch version-13
bench install-app pibical

# Update dependencies
bench update --requirements

# No specific test commands found - standard Frappe testing applies
```

## Architecture

### Core Synchronization Logic
The main synchronization logic is in `pibical/custom.py`:
- `sync_caldav_event_by_user()`: Frappe → CalDAV sync (triggered on Event save)
- `sync_outside_caldav()`: CalDAV → Frappe sync (runs every 3 minutes via cron)
- `remove_caldav_event()`: Removes events from CalDAV when deleted in Frappe

### Key Integration Points
- **Document Hooks** (`hooks.py`): 
  - `Event.before_save` → syncs to CalDAV
  - `Event.on_trash` → removes from CalDAV
- **Scheduled Tasks**: Background job runs every 3 minutes to pull CalDAV changes
- **Custom Fields**: Added to User (CalDAV credentials) and Event (sync settings) doctypes via fixtures

### Important Considerations
- **Timezone**: Now properly handles user timezones from Frappe User settings
  - All events stored in UTC on CalDAV server
  - Converted to user's local timezone for display
  - Each user can have different timezone settings
- **Authentication**: Per-user CalDAV credentials stored in User doctype custom fields
- **Event Filtering**: Only public events are synchronized
- **Async Processing**: Long operations use Frappe's job queue (`frappe.enqueue`)
- **CalDAV UID**: Events maintain unique IDs for tracking across systems

### Dependencies
- `caldav`: CalDAV client library
- `icalendar`: iCalendar format support
- Requires TLS-enabled server (not wildcard certificates)