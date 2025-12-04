# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

PibiCal is a Frappe app that provides bidirectional synchronization between Frappe/ERPNext events and CalDAV calendar servers (primarily NextCloud). It only syncs public events and supports features like recurring events, participants, and meeting minutes.

**Key Point**: This is a Frappe/ERPNext app, not a standalone application. It runs within the Frappe framework and follows Frappe app conventions.

## Version & Branch Strategy

- **Current branch**: `develop` (Frappe v15)
- **Stable branch**: `version-13` (Frappe v13 - production ready)
- **Legacy**: `version-12` (no longer maintained)

Always check which Frappe version is being targeted before making changes.

## Development Commands

```bash
# Installation (from frappe-bench directory)
bench get-app pibical https://github.com/pibico/pibical.git --branch develop
bench --site [site-name] install-app pibical
bench restart

# Update app and dependencies
bench update --apps pibical --no-backup
bench update --requirements

# Frappe development helpers
bench --site [site-name] console  # Python console with Frappe context
bench --site [site-name] mariadb  # Database console
bench clear-cache                  # Clear Frappe cache
bench migrate                      # Run database migrations

# View logs
tail -f ~/frappe-bench/logs/worker.log  # Background jobs
tail -f ~/frappe-bench/logs/web.log     # Web requests
```

## Architecture

### Core Files

1. **`pibical/pibical/custom.py`** - All synchronization logic (800+ lines)
   - Main sync functions (Frappe ↔ CalDAV)
   - CalDAV client connection handling
   - Event conversion (Frappe Event ↔ iCalendar format)
   - Timezone conversions
   - Invitation email generation

2. **`pibical/hooks.py`** - Frappe integration hooks
   - Document event hooks (before_save, on_trash)
   - Scheduled tasks (cron jobs)
   - Fixture definitions for custom fields

3. **`pibical/fixtures/`** - Database customizations
   - `custom_field.json` - Adds fields to User and Event doctypes
   - `client_script.json` - Client-side JavaScript behaviors
   - `server_script.json` - Server-side script customizations

### Synchronization Flow

#### Frappe → CalDAV (Immediate)
```
User saves Event in Frappe
  ↓
hooks.py: Event.before_save triggers
  ↓
custom.py: sync_caldav_event_by_user()
  ↓
Convert Frappe Event → iCalendar format
  ↓
Push to CalDAV server via caldav library
  ↓
Store event_uid and caldav_id_url on Event doc
```

#### CalDAV → Frappe (Every 3 minutes)
```
Scheduled task runs (cron: */3 * * * *)
  ↓
custom.py: sync_outside_caldav()
  ↓
For each user with CalDAV credentials:
  - Connect to CalDAV server
  - Fetch events (yesterday to +30 days)
  - Compare timestamps to detect changes
  - Convert iCalendar → Frappe Event format
  - Create/update events in Frappe
  ↓
Skip if event already exists (UID + subject + time match)
```

### Key Functions in custom.py

**Whitelisted API Methods** (callable from client):
- `get_calendar(nuser)` - Retrieve user's CalDAV calendars
- `sync_caldav_event_by_user(doc, method)` - Manual Frappe → CalDAV sync
- `remove_caldav_event(doc, method)` - Delete event from CalDAV
- `send_event_invitations(event_name, recipients)` - Email .ics invitations

**Internal Functions**:
- `sync_outside_caldav()` - Background job for CalDAV → Frappe sync
- `get_user_timezone()` - Fetch timezone from User settings
- `convert_to_utc()` / `convert_from_utc()` - Timezone conversions
- `generate_ics_for_event()` - Create iCalendar format for invitations
- `is_event_modified()` - Compare timestamps (±1 second tolerance)

### Custom Fields Added

**User Doctype**:
- `caldav_url` - CalDAV server endpoint
- `caldav_username` - CalDAV username
- `caldav_token` - CalDAV password/token (encrypted)

**Event Doctype**:
- `sync_with_caldav` - Boolean flag to enable sync
- `caldav_id_calendar` - Selected calendar name
- `caldav_id_url` - Calendar URL on server
- `event_uid` - Unique identifier for CalDAV
- `event_stamp` - Last modification timestamp

These fields are defined in `pibical/fixtures/custom_field.json`.

## Important Technical Details

### Timezone Handling
- **Storage**: Events stored in UTC on CalDAV server
- **Display**: Converted to user's local timezone (from User.time_zone)
- **Critical Functions**: `convert_to_utc()`, `convert_from_utc()`, `get_user_timezone()`
- Each user can have different timezone settings

### Event UID Format
- **Frappe-created**: `frappe[md5hash]@pibico.es`
- **CalDAV-created**: Preserves original UID from server
- UIDs are case-sensitive and used for deduplication

### Duplicate Prevention
1. Primary: Match by `event_uid` (case-sensitive)
2. Fallback: Match by subject + start time + calendar
3. In-memory tracking of processed events in sync loop

### Error Handling
- Connection errors logged but don't block other events
- Per-user sync failures don't affect other users
- Async processing via `frappe.enqueue()` for long operations

### Sync Limitations
- **Direction**: Full bidirectional for create/update
- **Deletion**: Only Frappe → CalDAV (CalDAV deletions require manual cleanup)
- **Event Types**: Only "Public" events synchronized
- **Participants**: Frappe → CalDAV only (one-way, disabled by default)
- **Attachments**: Not synchronized

## Testing & Debugging

```bash
# Enable developer mode and detailed logging
# Edit sites/[site-name]/site_config.json:
{
  "developer_mode": 1,
  "logging": 2
}

# Check scheduler is running
bench doctor

# Manually trigger sync (from bench console)
bench --site [site-name] console
>>> from pibical.pibical.custom import sync_outside_caldav
>>> sync_outside_caldav()

# Check for errors in Frappe UI
# Navigate to: Error Log doctype
```

**No automated tests exist** - testing is manual through Frappe UI and background job monitoring.

## Dependencies

- **`caldav`** (>= 0.9.0) - CalDAV client library
- **`icalendar`** (>= 4.0.0) - iCalendar format parsing/generation
- **`frappe`** - Framework (version-specific)

**TLS Requirement**: CalDAV server must have valid TLS/SSL certificate (no wildcard certificates).

## Code Modification Guidelines

1. **Timezone-aware**: Always use `get_user_timezone()` and conversion functions
2. **Error handling**: Wrap CalDAV operations in try/except, log don't raise
3. **Event filtering**: Check `sync_with_caldav` flag and event type = "Public"
4. **UID preservation**: Never change event_uid once set
5. **Frappe context**: Use `frappe.db`, `frappe.get_doc()`, not direct SQL
6. **Async jobs**: Long operations should use `frappe.enqueue()`

## Common Development Patterns

### Adding new Event fields to sync
1. Add field to Event doctype (via fixture or migration)
2. Update `sync_caldav_event_by_user()` - add to iCalendar event
3. Update `sync_outside_caldav()` - parse from CalDAV event
4. Consider timezone implications if datetime field

### Modifying sync frequency
Edit `pibical/hooks.py`:
```python
scheduler_events = {
  "cron": {
    "*/3 * * * *": [  # Change this cron expression
      "pibical.pibical.custom.sync_outside_caldav"
    ]
  }
}
```

### Adding whitelisted API methods
1. Define function in `custom.py`
2. Add `@frappe.whitelist()` decorator
3. Validate permissions within function (check user access)
4. Return JSON-serializable data
