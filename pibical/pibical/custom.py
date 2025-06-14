# -*- coding: utf-8 -*-
# Copyright (c) 2020, PibiCo and contributors
# For license information, please see license.txt
from __future__ import unicode_literals
import frappe
from frappe import msgprint, _, throw, enqueue
import json
from datetime import date, datetime, timedelta

import sys, requests, hashlib
from icalendar import Calendar, Event
from icalendar import vCalAddress, vText, vRecur
from pytz import UTC, timezone
import pytz

import caldav
from frappe.utils.password import get_decrypted_password
from frappe.utils import get_datetime, get_datetime_str, strip_html

def get_user_timezone():
  """Get timezone from user settings or system default"""
  user_timezone = frappe.db.get_value("User", frappe.session.user, "time_zone")
  if not user_timezone:
    # Get system default timezone
    user_timezone = frappe.get_system_settings("time_zone") or "UTC"
  return timezone(user_timezone)

def is_event_modified(event1_stamp, event2_stamp):
  """Compare two event timestamps to check if they differ by more than 1 second"""
  if isinstance(event1_stamp, str):
    event1_stamp = datetime.strptime(event1_stamp, '%Y-%m-%d %H:%M:%S')
  if isinstance(event2_stamp, str):
    event2_stamp = datetime.strptime(event2_stamp, '%Y-%m-%d %H:%M:%S')
  
  # Allow 1 second difference for timezone conversion rounding
  return abs((event1_stamp - event2_stamp).total_seconds()) > 1

def convert_to_utc(dt, user_tz=None):
  """Convert datetime to UTC considering user timezone"""
  if not user_tz:
    user_tz = get_user_timezone()
  
  if isinstance(dt, str):
    dt = datetime.strptime(dt, '%Y-%m-%d %H:%M:%S')
  
  # If datetime is naive, localize it to user timezone first
  if dt.tzinfo is None:
    dt = user_tz.localize(dt)
  
  # Convert to UTC
  return dt.astimezone(UTC)

def convert_from_utc(dt, user_tz=None):
  """Convert UTC datetime to user timezone"""
  if not user_tz:
    user_tz = get_user_timezone()
  
  if isinstance(dt, str):
    dt = datetime.strptime(dt, '%Y-%m-%d %H:%M:%S')
  
  # If datetime is naive, assume it's UTC
  if dt.tzinfo is None:
    dt = UTC.localize(dt)
  
  # Convert to user timezone
  return dt.astimezone(user_tz)

@frappe.whitelist()
def get_calendar(nuser):
  fp_user = frappe.get_doc("User", nuser)
  if fp_user.caldav_url and fp_user.caldav_username and fp_user.caldav_token:
    if fp_user.caldav_url[-1] == "/":
      caldav_url = fp_user.caldav_url + "users/" + fp_user.caldav_username
    else:
      caldav_url = fp_user.caldav_url + "/users/" + fp_user.caldav_username
    # print(caldav_url)
    caldav_username = fp_user.caldav_username
    caldav_token = get_decrypted_password('User', nuser, 'caldav_token', False)
    
    try:
      # set connection to caldav calendar with user credentials
      caldav_client = caldav.DAVClient(url=caldav_url, username=caldav_username, password=caldav_token)
      cal_principal = caldav_client.principal()
      # fetching calendars from server
      calendars = cal_principal.calendars()
      arr_cal = []
      if calendars:
        # print("[INFO] Received %i calendars:" % len(calendars))
        cal_url = caldav_url.replace("principals/users","calendars")
        for c in calendars:
          print("Name: %-20s  URL: %s" % (c.name, c.url.replace(cal_url +"/" , "").replace("/","")))
          scal = {}
          scal['name'] = c.name
          scal['url'] = str(c.url)
          arr_cal.append(scal)
      else:
        frappe.msgprint(_("Server has no calendars for your user"))
      return arr_cal
    except Exception as e:
      frappe.log_error(f"CalDAV Error for user {nuser}: {str(e)}", "PibiCal Get Calendar Error")
      frappe.msgprint(_("Error connecting to CalDAV server: {0}").format(str(e)))
      return []
  else:
    frappe.msgprint(_("Please configure CalDAV settings in your User profile"))
    return []

@frappe.whitelist()
def sync_caldav_event_by_user(doc, method=None):
  if doc.sync_with_caldav:
    # Get CalDav Data from logged in user
    fp_user = frappe.get_doc("User", frappe.session.user)
    # Get user timezone
    user_tz = get_user_timezone()
    
    # Continue if CalDav Data exists on logged in user
    if fp_user.caldav_url and fp_user.caldav_username and fp_user.caldav_token:
      # Check if selected calendar matches with previously recorded and delete event if not matching
      if doc.caldav_id_url:
        s_cal = doc.caldav_id_url.split("/")
        ocal = s_cal[len(s_cal)-2]
        if '_shared_by_' in ocal:
          pos = ocal.find("_shared_by_")
          ocal = ocal[0:pos]
        if (doc.caldav_id_calendar and not ocal in doc.caldav_id_calendar) or (doc.event_uid and not 'frappe' in doc.event_uid):
          remove_caldav_event(doc)
          doc.caldav_id_url = None
          doc.event_uid = None
          doc.event_stamp = None
      # Fill CalDav URL with selected CalDav Calendar
      doc.caldav_id_url = doc.caldav_id_calendar
      # Create uid for new events
      str_uid = datetime.now().strftime("%Y%m%dT%H%M%S")
      uidstamp = 'frappe' + hashlib.md5(str_uid.encode('utf-8')).hexdigest() + '@pibico.es'
      if not doc.event_uid:
        doc.event_uid = uidstamp
      else:
        uidstamp = doc.event_uid
      ucal = str(doc.caldav_id_url).split("/")
      # Get Calendar Name from URL as last portion in URL
      cal_name = ucal[len(ucal)-2]
      # Get CalDav URL, CalDav User and Token
      if fp_user.caldav_url[-1] == "/":
        caldav_url = fp_user.caldav_url + "users/" + fp_user.caldav_username
      else:
        caldav_url = fp_user.caldav_url + "/users/" + fp_user.caldav_username
      caldav_username = fp_user.caldav_username
      caldav_token = get_decrypted_password('User', frappe.session.user, 'caldav_token', False)
      # Set connection to caldav calendar with CalDav user credentials
      caldav_client = caldav.DAVClient(url=caldav_url, username=caldav_username, password=caldav_token)
      cal_principal = caldav_client.principal()
      # Fetching calendars from server
      calendars = cal_principal.calendars()
      if calendars:
        # Loop on CalDav User Calendars to check if event exists
        for c in calendars:
          scal = str(c.url).split("/")
          str_user = scal[len(scal)-3]
          str_cal = scal[len(scal)-2]
          # Check if CalDav calendar name or calendar name shared by another user matches
          if str_cal == cal_name or str_cal + "_shared_by_"  in str(doc.caldav_id_url):
            # Prepare iCalendar Event
            # Initialise iCalendar
            cal = Calendar()
            cal.add('prodid', '-//PibiCal//pibico.org//')
            cal.add('version', '2.0')
            # Initialize Event
            event = Event()
            # Fill data to Event
            # UID  
            event['uid'] = uidstamp
            # SUMMARY from Subject
            event.add('summary', doc.subject)
            # DTSTAMP from current time (always UTC)
            utc_timestamp = datetime.now(UTC)
            doc.event_stamp = utc_timestamp.strftime("%Y-%m-%d %H:%M:%S")
            event.add('dtstamp', utc_timestamp)
            # DTSTART from start - convert to UTC
            dtstart = datetime.strptime(doc.starts_on, '%Y-%m-%d %H:%M:%S')
            if doc.all_day:
              dtstart = date(dtstart.year, dtstart.month, dtstart.day)
            else:  
              # Convert to UTC for non-all-day events
              dtstart = convert_to_utc(dtstart, user_tz)
            event.add('dtstart', dtstart)
            # DTEND if end - convert to UTC
            if doc.ends_on:
              dtend = datetime.strptime(doc.ends_on, '%Y-%m-%d %H:%M:%S')
              if doc.all_day:
                dtend = date(dtend.year, dtend.month, dtend.day)
              else:  
                # Convert to UTC for non-all-day events
                dtend = convert_to_utc(dtend, user_tz)
              event.add('dtend', dtend)
            # DESCRIPTION if any - convert HTML to plain text
            if doc.description:
              plain_description = strip_html(doc.description)
              event.add('description', plain_description)
            # CATEGORIES from event_category
            category = _(doc.event_category)
            event.add('categories', [category])
            # ORGANIZER from user session
            if not fp_user in ["Administrator", "Guest"]:
              organizer = vCalAddress(u'mailto:%s' % fp_user)
              organizer.params['cn'] = vText(fp_user.caldav_username)
              organizer.params['ROLE'] = vText('ORGANIZER')
              event.add('organizer', organizer)
            # STATUS from event status
            if doc.status:
              status_map = {
                'Open': 'TENTATIVE',
                'Completed': 'CONFIRMED',
                'Closed': 'CONFIRMED',
                'Cancelled': 'CANCELLED'
              }
              ical_status = status_map.get(doc.status, 'TENTATIVE')
              event.add('status', ical_status)
            # ATTENDEES from event_participants
            if doc.event_participants:
              for participant in doc.event_participants:
                if participant.email:
                  attendee = vCalAddress(u'mailto:%s' % participant.email)
                  attendee.params['cn'] = vText(participant.reference_docname or participant.email)
                  attendee.params['ROLE'] = vText('REQ-PARTICIPANT')
                  event.add('attendee', attendee)
            # Add Recurring events
            if doc.repeat_this_event:
             if doc.repeat_on:
               if not doc.repeat_till:
                 if doc.repeat_on.lower() == 'weekly':
                   sday = []
                   if doc.monday:
                     sday.append('MO')
                   if doc.tuesday:
                     sday.append('TU')
                   if doc.wednesday:
                     sday.append('WE')
                   if doc.thursday:
                     sday.append('TH')
                   if doc.friday:
                     sday.append('FR')
                   if doc.saturday:
                     sday.append('SA')
                   if doc.sunday:
                     sday.append('SU')
                   if len(sday) > 0:  
                     event.add('rrule', {'freq': [doc.repeat_on.lower()], 'byday': sday})
                   else:
                     event.add('rrule', {'freq': [doc.repeat_on.lower()]})
                 else:
                   event.add('rrule', {'freq': [doc.repeat_on.lower()]})
               else:
                 dtuntil = datetime.strptime(doc.repeat_till, '%Y-%m-%d')
                 dtuntil = convert_to_utc(datetime(dtuntil.year, dtuntil.month, dtuntil.day, 23, 59, 59), user_tz)
                 if doc.repeat_on.lower() == 'weekly':
                   sday = []
                   if doc.monday:
                     sday.append('MO')
                   if doc.tuesday:
                     sday.append('TU')
                   if doc.wednesday:
                     sday.append('WE')
                   if doc.thursday:
                     sday.append('TH')
                   if doc.friday:
                     sday.append('FR')
                   if doc.saturday:
                     sday.append('SA')
                   if doc.sunday:
                     sday.append('SU')
                   if len(sday) > 0:  
                     event.add('rrule', {'freq': [doc.repeat_on.lower()], 'byday': sday, 'until': [dtuntil]})
                 else:
                   event.add('rrule', {'freq': [doc.repeat_on.lower()], 'until': [dtuntil]})
            # Add event to iCalendar 
            cal.add_component(event)
            
            # Check if event already exists on CalDAV server
            try:
              existing_event = None
              all_events = c.events()
              for cal_event in all_events:
                cal_url = str(cal_event).replace("Event: https://", "https://" + caldav_username + ":" + caldav_token +"@")
                req = requests.get(cal_url)
                ical = Calendar.from_ical(req.text)
                for evt in ical.walk('vevent'):
                  evt_uid = evt.decoded('uid')
                  if isinstance(evt_uid, bytes):
                    evt_uid = evt_uid.decode('utf-8')
                  if evt_uid.lower() == uidstamp.lower():
                    existing_event = cal_event
                    break
                if existing_event:
                  break
              
              if existing_event:
                # Update existing event
                existing_event.delete()
                c.save_event(cal.to_ical())
                frappe.msgprint(_("Event updated on CalDAV server"))
              else:
                # Create new event
                c.save_event(cal.to_ical())
                frappe.msgprint(_("Event created on CalDAV server"))
            except Exception as e:
              frappe.log_error(f"CalDAV sync error: {str(e)}", "PibiCal Sync Error")
              frappe.msgprint(_("Error syncing event to CalDAV: {0}").format(str(e)))
            
  else:
    if doc.event_uid:
      args = {
        "doc": doc
      }
      #remove_caldav_event(doc)
      enqueue(method=remove_caldav_event, queue='short', timeout=300, now=True, *args)

      doc.caldav_id_url = None
      doc.event_uid = None
      doc.event_stamp = None

@frappe.whitelist()
def remove_caldav_event(doc, method=None):
  if doc.event_uid:
    # Get CalDav Data from logged in user
    fp_user = frappe.get_doc("User", frappe.session.user)
    # Continue if CalDav Data exists on logged in user
    if fp_user.caldav_url and fp_user.caldav_username and fp_user.caldav_token:
      uidstamp = doc.event_uid
      cal_name = None
      if doc.caldav_id_url:
        ucal = str(doc.caldav_id_url).split("/")
        # Get Calendar Name from URL as last portion in URL
        cal_name = ucal[len(ucal)-2]
      # Get CalDav URL, CalDav User and Token
      if fp_user.caldav_url[-1] == "/":
        caldav_url = fp_user.caldav_url + "users/" + fp_user.caldav_username
      else:
        caldav_url = fp_user.caldav_url + "/users/" + fp_user.caldav_username
      caldav_username = fp_user.caldav_username
      caldav_token = get_decrypted_password('User', frappe.session.user, 'caldav_token', False)
      # Set connection to caldav calendar with CalDav user credentials
      caldav_client = caldav.DAVClient(url=caldav_url, username=caldav_username, password=caldav_token)
      cal_principal = caldav_client.principal()
      # Fetching calendars from server
      calendars = cal_principal.calendars()
      doExists = False
      if calendars:
        # Loop on CalDav User Calendars to check if event exists
        for c in calendars:
          scal = str(c.url).split("/")
          str_user = scal[len(scal)-3]
          str_cal = scal[len(scal)-2]
          # Check if CalDav calendar name or calendar name shared by another user matches
          if str_cal == cal_name or str_cal + "_shared_by_"  in str(doc.caldav_id_url):
            # Get all events in matched calendar just to inform about existing or new event
            all_events = c.events()
            # Loop through events to check if current event exists
            for url_event in all_events:
              cal_url = str(url_event).replace("Event: https://", "https://" + caldav_username + ":" + caldav_token +"@")
              req = requests.get(cal_url)
              cal = Calendar.from_ical(req.text)
              for evento in cal.walk('vevent'):
                uid_value = evento.decoded('uid')
                if isinstance(uid_value, bytes):
                  uid_value = uid_value.decode('utf-8')
                if uidstamp in str(uid_value).lower():
                  doExists = True
                  break
              if doExists:
                url_event.delete()
                frappe.msgprint(_("Deleted Event in CalDav Calendar ") + str(c.name))
                break

def sync_outside_caldav():
  # Get All Users with CalDav Credentials
  caldav_users = frappe.get_list(
    doctype = "User",
    fields = ["name", "caldav_url", "caldav_username", "time_zone"],
    filters = [['enabled', '=', 1],['name', '!=', 'Administrator'], ['name', '!=', 'Guest'], ['caldav_username', '!=', '']]
  )
  if caldav_users:
    if len(caldav_users) > 0:
      # Array for include processed uuid events
      sel_uuid = []
      for caldav_user in caldav_users:
        # Get user timezone
        user_timezone = caldav_user.time_zone or frappe.get_system_settings("time_zone") or "UTC"
        user_tz = timezone(user_timezone)
        
        # Get CalDav URL, CalDav User and Token
        if caldav_user.caldav_url[-1] == "/":
          caldav_url = caldav_user.caldav_url + "users/" + caldav_user.caldav_username
        else:
          caldav_url = caldav_user.caldav_url + "/users/" + caldav_user.caldav_username
        caldav_username = caldav_user.caldav_username
        caldav_token = get_decrypted_password('User', caldav_user.name, 'caldav_token', False)
        # Set connection to caldav calendar with CalDav user credentials
        caldav_client = caldav.DAVClient(url=caldav_url, username=caldav_username, password=caldav_token)
        cal_principal = caldav_client.principal()
        # Fetching calendars from server
        calendars = cal_principal.calendars()
        if calendars:
          # Loop on CalDav User Calendars to check events scheduled from yesterday to 30 days onwards
          for c in calendars:
            sel_events = c.date_search(datetime.now().date()-timedelta(days=1), datetime.now().date()+timedelta(days=+30))
            # Loop through selected events by scheduled dates
            for url_event in sel_events:
              cal_url = str(url_event).replace("Event: https://", "https://" + caldav_username + ":" + caldav_token +"@")
              req = requests.get(cal_url)
              cal = Calendar.from_ical(req.text)
              # Sync CalDav calendar from OutSide Server
              for evento in cal.walk('vevent'):
                # Check if already processed uuid event
                # Fix double decoding issue
                event_uid = evento.decoded('uid')
                if isinstance(event_uid, bytes):
                    event_uid = event_uid.decode('utf-8')
                event_uid_lower = str(event_uid).lower()
                
                if not event_uid_lower in sel_uuid:
                  # Add uuid event to processed events array
                  sel_uuid.append(event_uid_lower)
                  # Processing event if dtstamp has changed or not in frappe events
                  fp_event = frappe.get_list(
                    doctype = 'Event',
                    fields = ['*'],
                    filters = [['docstatus', '<', 2], ['event_uid', '=', event_uid_lower]]
                  )
                  
                  # Also check for potential duplicates by subject and time
                  if not fp_event and 'summary' in evento and 'dtstart' in evento:
                    summary = evento.decoded('summary')
                    if isinstance(summary, bytes):
                      summary = summary.decode('utf-8')
                    dtstart = evento.decoded('dtstart')
                    if isinstance(dtstart, datetime):
                      if dtstart.tzinfo:
                        dtstart_local = dtstart.astimezone(user_tz)
                      else:
                        dtstart_local = UTC.localize(dtstart).astimezone(user_tz)
                      start_str = dtstart_local.strftime("%Y-%m-%d %H:%M:%S")
                    else:
                      start_str = dtstart.strftime("%Y-%m-%d")
                    
                    # Check for duplicate by subject and start time
                    duplicate_check = frappe.get_list(
                      doctype = 'Event',
                      fields = ['name', 'event_uid'],
                      filters = [
                        ['docstatus', '<', 2],
                        ['subject', '=', str(summary)],
                        ['starts_on', '=', start_str],
                        ['event_uid', '!=', event_uid_lower]
                      ]
                    )
                    
                    if duplicate_check:
                      # Skip this event as it appears to be a duplicate
                      frappe.log_error(f"Skipping potential duplicate event: {summary} at {start_str}", "PibiCal Duplicate Detection")
                      continue
                  
                  if fp_event:
                    # Check if dtstamp has changed meaning it has been updated on NextCloud
                    caldav_stamp = evento.decoded('dtstamp')
                    if caldav_stamp.tzinfo:
                      caldav_stamp_local = caldav_stamp.astimezone(user_tz)
                    else:
                      caldav_stamp_local = UTC.localize(caldav_stamp).astimezone(user_tz)
                    
                    if is_event_modified(fp_event[0].event_stamp, caldav_stamp_local.strftime("%Y-%m-%d %H:%M:%S")):
                      cal_event = frappe.get_doc("Event", fp_event[0].name)
                      # caldav_id_url
                      cal_event.caldav_id_url = str(c.url)
                      upd_event = prepare_fp_event(cal_event, evento, user_tz)  
                      upd_event.save()
                      #print(upd_event.as_dict())
                  else:
                    #Create new event in Frappe
                    new_cal_event = frappe.new_doc("Event")
                    new_cal_event.caldav_id_url = str(c.url)
                    new_event = prepare_fp_event(new_cal_event, evento, user_tz)
                    new_event.save()
                    frappe.db.commit()
                    #print(new_event.as_dict())
                    
def prepare_fp_event(event, cal_event, user_tz=None):
  # Prepare event for Frappe
  if not user_tz:
    user_tz = get_user_timezone()
    
  # event_type.  ALWAYS PUBLIC
  event.event_type = "Public"
  # sync_with_caldav. ALWAYS TRUE
  event.sync_with_caldav = 1
  # subject
  if not 'summary' in cal_event:
    event.subject = (_("Untitled event"))
  else:
    summary = cal_event.decoded('summary')
    if isinstance(summary, bytes):
      summary = summary.decode('utf-8')
    event.subject = str(summary)
  # starts_on - convert from UTC to user timezone
  dtstart = cal_event.decoded('dtstart')
  if isinstance(dtstart, datetime):
    event.all_day = False
    # If the datetime has timezone info, convert to user timezone
    if dtstart.tzinfo:
      dtstart_local = dtstart.astimezone(user_tz)
    else:
      # Assume UTC if no timezone info
      dtstart_local = UTC.localize(dtstart).astimezone(user_tz)
    event.starts_on = dtstart_local.strftime("%Y-%m-%d %H:%M:%S")
  else:
    event.all_day = True
    event.starts_on = dtstart.strftime("%Y-%m-%d")
  # ends_on - convert from UTC to user timezone
  if 'dtend' in cal_event:
    dtend = cal_event.decoded('dtend')
    if isinstance(dtend, datetime):
      # If the datetime has timezone info, convert to user timezone
      if dtend.tzinfo:
        dtend_local = dtend.astimezone(user_tz)
      else:
        # Assume UTC if no timezone info
        dtend_local = UTC.localize(dtend).astimezone(user_tz)
      event.ends_on = dtend_local.strftime("%Y-%m-%d %H:%M:%S")
    else:
      event.ends_on = dtend.strftime("%Y-%m-%d")
  # event_dtstamp
  dtstamp = cal_event.decoded('dtstamp')
  if dtstamp.tzinfo:
    dtstamp_local = dtstamp.astimezone(user_tz)
  else:
    dtstamp_local = UTC.localize(dtstamp).astimezone(user_tz)
  event.event_stamp = dtstamp_local.strftime("%Y-%m-%d %H:%M:%S")
  # event_uid
  uid_value = cal_event.decoded('uid')
  if isinstance(uid_value, bytes):
    uid_value = uid_value.decode('utf-8')
  event.event_uid = str(uid_value).lower()
  # description
  if 'description' in cal_event:
    description = cal_event.decoded('description')
    if isinstance(description, bytes):
      description = description.decode('utf-8')
    event.description = str(description)
  # event_category
  if not event.event_category:
    event.event_category = "Other"
  # status
  if 'status' in cal_event:
    ical_status = str(cal_event.decoded('status')).upper()
    status_map = {
      'TENTATIVE': 'Open',
      'CONFIRMED': 'Completed',
      'CANCELLED': 'Cancelled'
    }
    event.status = status_map.get(ical_status, 'Open')
  else:
    event.status = 'Open'
  # participants/attendees
  # Clear existing participants before adding new ones
  if hasattr(event, 'event_participants') and event.event_participants:
    event.event_participants = []
  if 'attendee' in cal_event:
    attendees = cal_event.get('attendee')
    if not isinstance(attendees, list):
      attendees = [attendees]
    for attendee in attendees:
      email = str(attendee).replace('mailto:', '')
      if email:
        # Try to find user by email
        user_name = frappe.db.get_value("User", {"email": email}, "name")
        participant = {
          'email': email,
          'reference_doctype': 'User' if user_name else None,
          'reference_docname': user_name if user_name else None
        }
        event.append('event_participants', participant)
  # For future development  
  if 'rrule' in cal_event:
    """ {'FREQ': ['WEEKLY'], 'UNTIL': [datetime.datetime(2021, 10, 3, 0, 0)], 'BYDAY': ['TU', 'TH', 'SA']} """
    event.repeat_this_event = 1
    rule = cal_event.get('rrule')
    if rule:
      rrule = dict(rule)
      if 'FREQ' in rrule:
        frequency = rrule['FREQ'][0].lower().capitalize()
        event.repeat_on = frequency
        if frequency == "Weekly":
          if 'BYDAY' in rrule:
            if 'MO' in rrule['BYDAY']:
              event.monday = True             
            if 'TU' in rrule['BYDAY']:
              event.tuesday = True
            if 'WE' in rrule['BYDAY']:
              event.wednesday = True
            if 'TH' in rrule['BYDAY']:
              event.thursday = True
            if 'FR' in rrule['BYDAY']:
              event.friday = True
            if 'SA' in rrule['BYDAY']:
              event.saturday = True
            if 'SU' in rrule['BYDAY']:
              event.sunday = True 
      if 'UNTIL' in rrule:
        until_dt = rrule['UNTIL'][0]
        if until_dt.tzinfo:
          until_local = until_dt.astimezone(user_tz)
        else:
          until_local = UTC.localize(until_dt).astimezone(user_tz)
        event.repeat_till = until_local.strftime("%Y-%m-%d")
                                  
  #print(event.as_dict())
  return event

@frappe.whitelist()
def send_event_invitations(event_name, recipients):
  """Send event invitations to selected participants"""
  import json
  
  if isinstance(recipients, str):
    recipients = json.loads(recipients)
  
  event = frappe.get_doc("Event", event_name)
  
  # Get user timezone for event details
  user_tz = get_user_timezone()
  
  # Prepare event details for email
  starts_on = convert_from_utc(datetime.strptime(event.starts_on, '%Y-%m-%d %H:%M:%S'), user_tz) if not event.all_day else event.starts_on
  ends_on = convert_from_utc(datetime.strptime(event.ends_on, '%Y-%m-%d %H:%M:%S'), user_tz) if event.ends_on and not event.all_day else event.ends_on
  
  # Format dates for email
  if event.all_day:
    event_time = starts_on if isinstance(starts_on, str) else starts_on.strftime('%Y-%m-%d')
  else:
    start_str = starts_on.strftime('%Y-%m-%d %H:%M')
    end_str = ends_on.strftime('%Y-%m-%d %H:%M') if ends_on else ""
    event_time = f"{start_str} - {end_str}" if end_str else start_str
  
  # Send email to each selected recipient
  sent_count = 0
  for recipient in recipients:
    if recipient.get('send_invitation') and recipient.get('email'):
      try:
        # Prepare email content
        subject = _("Event Invitation: {0}").format(event.subject)
        
        # Build message without f-strings for translation functions
        message = "<h3>" + _("Event Invitation") + "</h3>"
        message += "<p><strong>" + _("Event") + ":</strong> " + event.subject + "</p>"
        message += "<p><strong>" + _("Date/Time") + ":</strong> " + event_time + "</p>"
        
        if event.description:
          plain_description = strip_html(event.description)
          message += "<p><strong>" + _("Description") + ":</strong><br>" + plain_description + "</p>"
        
        if event.location:
          message += "<p><strong>" + _("Location") + ":</strong> " + event.location + "</p>"
        
        message += "<hr>"
        message += "<p><small>" + _("You have been invited to this event. Please mark your calendar.") + "</small></p>"
        
        # Send email
        frappe.sendmail(
          recipients=[recipient.get('email')],
          subject=subject,
          message=message,
          reference_doctype="Event",
          reference_name=event_name
        )
        sent_count += 1
        
      except Exception as e:
        frappe.log_error(f"Failed to send invitation to {recipient.get('email')}: {str(e)}", "Event Invitation Error")
  
  return {
    'sent_count': sent_count,
    'total_selected': len([r for r in recipients if r.get('send_invitation')])
  }