# PibiCal

Bidirectional calendar synchronization between Frappe/ERPNext and CalDAV servers (NextCloud, ownCloud, etc.)

## Overview

PibiCal enables real-time synchronization of calendar events between your Frappe/ERPNext instance and CalDAV-compatible calendar servers. It supports bidirectional sync, recurring events, event participants, and timezone management.

## Version Compatibility

| Frappe Version | PibiCal Branch | Status | Notes |
|----------------|----------------|---------|--------|
| v15 | `develop` | ✅ Active Development | Recommended for new installations |
| v13 | `version-13` | ✅ Stable | Production ready |
| v12 | `version-12` | ⚠️ Legacy | No longer maintained |

## Requirements

- Frappe/ERPNext instance (v15 for this branch)
- CalDAV server (NextCloud, ownCloud, or any CalDAV-compatible server)
- TLS/SSL enabled server (wildcard certificates NOT supported)
- Python dependencies:
  - `caldav` >= 0.9.0
  - `icalendar` >= 4.0.0

## Installation

### For Frappe v15 (Recommended)

```bash
# Navigate to your frappe-bench directory
cd ~/frappe-bench

# Download the app
bench get-app pibical https://github.com/pibico/pibical.git --branch develop

# Install on your site (single-tenant)
bench install-app pibical

# OR install on specific site (multi-tenant)
bench --site your-site-name install-app pibical

# Restart bench to apply changes
bench restart
```

### For Frappe v13 (Stable)

```bash
bench get-app pibical https://github.com/pibico/pibical.git --branch version-13
bench --site your-site-name install-app pibical
```

## Updating

```bash
# Update the app
bench update --apps pibical --no-backup

# If you encounter dependency issues
bench update --requirements
```

## Configuration

### Step 1: Configure CalDAV Credentials

After installation, each user needs to configure their CalDAV credentials:

1. Go to **User List** → Select your user → Edit
2. Scroll to the **CalDAV Credentials** section
3. Fill in the following fields:

| Field | Description | Example |
|-------|-------------|---------|
| **CalDAV URL** | Your CalDAV server endpoint | `https://nextcloud.example.com/remote.php/dav/principals/` |
| **CalDAV Username** | Your CalDAV username | `john.doe` or `john.doe@example.com` |
| **CalDAV Token** | Your password or app-specific token | `your-password-or-token` |

![CalDAV User Settings](https://user-images.githubusercontent.com/69711454/139237194-4edf0621-4002-4bd2-bbf1-1e1b91c17b23.png)

> **💡 Tip**: For NextCloud users, you can generate an app-specific password from Settings → Security → Devices & sessions

### Step 2: Enable Sync for Events

When creating or editing an event in Frappe:

1. Set **Event Type** to **"Public"** (only public events are synchronized)
2. Check **"Sync with CalDAV"**
3. Select your calendar from the **"CalDAV ID Calendar"** dropdown

![Event CalDAV Settings](https://user-images.githubusercontent.com/69711454/139238862-d947d264-49a3-4812-b86c-38f7f5f811e9.png)

## Features

### ✅ Supported Features

- **Bidirectional Sync**: Changes in either system are synchronized
- **Timezone Support**: Events are properly converted between user timezones and UTC
- **Recurring Events**: Weekly, monthly, yearly patterns with end dates
- **Event Status**: Open, Completed, Cancelled states are synchronized
- **Event Description**: HTML descriptions are converted to plain text for CalDAV
- **All-Day Events**: Properly handled as date-only events
- **Multiple Calendars**: Support for multiple CalDAV calendars per user
- **Event Invitations**: Send calendar invitations with .ics attachments to participants (Contacts only)

### 🔄 Synchronization Details

- **Frappe → CalDAV**: Instant sync when saving events
- **CalDAV → Frappe**: Automatic sync every 3 minutes (configurable in `hooks.py`)
- **Conflict Resolution**: Last write wins based on modification timestamp
- **Duplicate Prevention**: Smart detection prevents duplicate events

### 📧 Event Invitations (New in v15)

You can send calendar invitations to event participants:

1. Add participants to your event (only Contacts with email addresses)
2. Save the event
3. Click **"Send Invitations"** button
4. Select recipients and send

![Event Participants](https://user-images.githubusercontent.com/69711454/139239301-349e96b9-cfd9-4993-a786-a9209f43c4ae.png)

## Usage Examples

### Creating a Synchronized Event

```python
# Via Frappe UI
1. Go to Events → New Event
2. Fill in event details:
   - Subject: "Team Meeting"
   - Event Type: "Public"
   - Check "Sync with CalDAV"
   - Select your calendar
   - Set date/time and other details
3. Save the event
```

### Synchronization Behavior

#### 📅 Event Created in Frappe/ERPNext

When you create an event in Frappe:
- **Requirement**: Must check "Sync with CalDAV" and select a calendar
- **UID Generated**: `frappe[hash]@pibico.es` format
- **Sync**: Immediate push to CalDAV server
- **Message**: "Event created on CalDAV server"
- **Fields Set**: 
  - `event_uid`: New unique identifier with "frappe" prefix
  - `caldav_id_url`: Selected calendar URL
  - `event_stamp`: Current UTC timestamp

#### 📅 Event Created in NextCloud/CalDAV

When you create an event in NextCloud:
- **Detection**: Background job checks every 3 minutes
- **Sync Window**: Events from yesterday to +30 days
- **Event Type**: Automatically set to "Public" in Frappe
- **UID Preserved**: Original CalDAV UID kept (no "frappe" prefix)
- **Timezone**: Converted from UTC to user's local time
- **No Notification**: Silent background sync

#### ✏️ Event Modified in Frappe/ERPNext

When you modify an event in Frappe:
- **Calendar Change**: If calendar changed, deletes from old location first
- **Update Method**: Deletes and recreates event in CalDAV (ensures clean update)
- **Message**: "Event updated on CalDAV server"
- **Preserved**: Original UID maintained
- **Supported Changes**: All fields including recurring patterns

#### ✏️ Event Modified in NextCloud/CalDAV  

When you modify an event in NextCloud:
- **Detection**: Timestamp comparison (±1 second tolerance)
- **Sync Delay**: Up to 3 minutes
- **Updates**: Subject, times, description, status, recurrence
- **Preserved**: Frappe-specific fields and participants
- **No Notification**: Silent background update

#### 🗑️ Event Deleted in Frappe/ERPNext

When you delete an event in Frappe:
- **Trigger**: Immediate on trash action
- **Deletion Methods** (tries in order):
  1. Direct URL deletion
  2. Search by UID
  3. Date range search (±30 days)
- **Messages**:
  - ✅ "Deleted Event in CalDav Calendar [name]"
  - ⚠️ "Event not found in CalDAV calendar"
  - 🚫 "Cannot delete due to insufficient permissions"

#### 🗑️ Event Deleted in NextCloud/CalDAV

When you delete an event in NextCloud:
- **Current Limitation**: ⚠️ **NOT automatically synced**
- **Workaround**: Manually delete the event in Frappe
- **Future Enhancement**: Planned for future releases

### 🔄 Sync Details & Limitations

| Feature | Status | Details |
|---------|--------|---------|
| **Sync Direction** | ✅ Bidirectional | Frappe ↔️ CalDAV |
| **Sync Frequency** | Frappe → CalDAV: Instant<br>CalDAV → Frappe: Every 3 min | Configurable in `hooks.py` |
| **Event Types** | ✅ Public only | Private events not synced |
| **Timezones** | ✅ Full support | Auto-conversion UTC ↔️ Local |
| **Recurring Events** | ✅ Supported | Weekly, Monthly, Yearly patterns |
| **Participants** | ⚠️ Limited | Frappe → CalDAV only (disabled by default) |
| **Attachments** | ❌ Not supported | Files don't sync |
| **Deletion Sync** | ⚠️ One-way only | Frappe → CalDAV works<br>CalDAV → Frappe manual |
| **Conflict Resolution** | Last write wins | Based on timestamp |

### 🛡️ Duplicate Prevention

The system prevents duplicate events through:
1. **UID Matching**: Primary identifier (case-sensitive)
2. **Fallback Check**: Subject + Start time + Calendar
3. **Skip Logic**: Already processed events tracked in memory

### ⚠️ Important Notes

1. **First Sync**: Initial sync may take time if you have many existing events
2. **UID Format**: 
   - Frappe-created: `frappe[hash]@pibico.es`
   - CalDAV-created: Preserves original UID
3. **Error Handling**: Connection issues are logged but won't stop other events from syncing
4. **Performance**: Large calendars (>1000 events) may experience delays

## Troubleshooting

### Common Issues

1. **"Unable to connect to CalDAV server"**
   - Verify your CalDAV URL is correct
   - Check username and password/token
   - Ensure your server has TLS/SSL enabled
   - Wildcard SSL certificates are NOT supported

2. **Events not syncing from CalDAV**
   - Check Error Log for "CalDAV Connection Error"
   - Verify the background job is running: `bench doctor`
   - Ensure your user has CalDAV credentials configured

3. **Timezone issues**
   - Set your timezone in User → Settings → Time Zone
   - Events are stored in UTC and converted to your local timezone

### Debug Mode

To enable detailed logging:

```python
# In frappe-bench/sites/your-site/site_config.json
{
    "developer_mode": 1,
    "logging": 2
}
```

Check logs in:
- Error Log (in Frappe UI)
- `frappe-bench/logs/worker.log`
- `frappe-bench/logs/web.log`

## API Reference

### Whitelisted Methods

```python
# Get user's CalDAV calendars
pibical.pibical.custom.get_calendar(nuser)

# Send event invitations
pibical.pibical.custom.send_event_invitations(event_name, recipients)
```

### Scheduled Jobs

```python
# Sync from CalDAV to Frappe (runs every 3 minutes)
pibical.pibical.custom.sync_outside_caldav()
```

## Contributing

1. Fork the repository
2. Create your feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add some amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

## License

MIT - see [LICENSE](license.txt) file for details

## Support

- **Issues**: [GitHub Issues](https://github.com/pibico/pibical/issues)
- **Discussions**: [GitHub Discussions](https://github.com/pibico/pibical/discussions)
- **Email**: pibico.sl@gmail.com
