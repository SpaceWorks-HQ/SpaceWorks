"""Authored default bodies for the events/bookings/maintenance/membership streams.

Separated from the registry module for the same reason the hardware/printing defaults
are: strings are bulk, structure is not, and mixing them puts both past the file ceiling.

Two rules these defaults follow, and a reader changing them should keep:

* **A staff default reproduces what the adapter sends today.** The four adapters built
  their bodies inline in Python; moving that wording here verbatim is what makes the
  switch to the template path a no-op for a space that never edits one.
* **A requester default never contains staff-only detail.** Requester wording addresses
  the person the notification is about, and it is the body a member reads — so no other
  member's name, no internal ids beyond their own, no staff notes.
"""

# --- events ---------------------------------------------------------------------------

EVENTS_STAFF_SUBJECT = "{{ makerspace.name }} event #{{ event.id }} {{ event_name }}"
EVENTS_STAFF_TEXT = """Event #{{ event.id }} {{ event_name }}.
Title: {{ event.title }}
Time: {{ event.when }}
Status: {{ event.status }}
{% if event.location %}Location: {{ event.location }}
{% endif %}{% if registration %}Registration: #{{ registration.id }}
Registrant: {{ registration.name }}
Registration status: {{ registration.status }}
{% endif %}"""

EVENTS_REQUESTER_SUBJECTS = {
    "published": "{{ event.title }} is open for registration",
    "cancelled": "{{ event.title }} has been cancelled",
    "completed": "Thank you for attending {{ event.title }}",
    "registration_created": "You are registered for {{ event.title }}",
    "registration_cancelled": "Your registration for {{ event.title }} was cancelled",
    "registration_promoted": "A place has opened up for {{ event.title }}",
    "registration_attended": "Your attendance at {{ event.title }} is recorded",
}

EVENTS_REQUESTER_BODIES = {
    "published": "Registration is now open.",
    "cancelled": (
        "This event has been cancelled. Please contact the makerspace if you have "
        "questions."
    ),
    "completed": "This event has finished. Thank you for taking part.",
    "registration_created": "Your place is booked. We look forward to seeing you.",
    "registration_cancelled": (
        "Your registration has been cancelled. You can register again while places "
        "remain."
    ),
    "registration_promoted": (
        "You were on the waiting list and a place has opened up. Your registration is "
        "now confirmed."
    ),
    "registration_attended": "Your attendance has been recorded.",
}

EVENTS_REQUESTER_TEXT = """Hello {{ registration.name|default:"there" }},

{{ makerspace.name }}
Event: {{ event.title }}
Time: {{ event.when }}
{% if event.location %}Location: {{ event.location }}
{% endif %}
{{ next_steps }}
"""

# --- bookings -------------------------------------------------------------------------

BOOKINGS_STAFF_SUBJECT = (
    "{{ makerspace.name }} booking #{{ booking.id }} {{ event_name }}"
)
BOOKINGS_STAFF_TEXT = """Booking #{{ booking.id }} {{ event_name }}.
Space: {{ booking.space.name }}
Time: {{ booking.when }}
Status: {{ booking.status }}
Booker: {{ booking.name }}
"""

BOOKINGS_REQUESTER_SUBJECT = "Booking {{ booking.status }}: {{ booking.space.name }}"

# Verbatim from `bookings.notifications._message`, which is the wording members receive
# today. Changing it here changes what every unedited space sends.
BOOKINGS_REQUESTER_BODIES = {
    "created": (
        "Your booking request was received. We will contact you if its status changes."
    ),
    "confirmed": (
        "Your booking is confirmed. Please contact the makerspace if your plans change."
    ),
    "rejected": (
        "Your request was not approved. Please contact the makerspace if you have "
        "questions."
    ),
    "cancelled": "Your booking has been cancelled.",
    "completed": "Your booking has been marked completed.",
    "no_show": "Your booking has been marked as a no-show.",
}

BOOKINGS_REQUESTER_TEXT = """Hello {{ booking.name }},

{{ makerspace.name }}
Space: {{ booking.space.name }}
Time: {{ booking.when }}
Status: {{ booking.status }}

{{ next_steps }}
"""

# --- maintenance ----------------------------------------------------------------------

MAINTENANCE_STAFF_SUBJECT = (
    "{{ makerspace.name }} maintenance {{ event_name }}: {{ machine.name }}"
)
MAINTENANCE_STAFF_TEXT = """Maintenance {{ event_name }}.
Machine: {{ machine.name }}
{% if schedule %}Schedule: #{{ schedule.id }}
Description: {{ schedule.description }}
Next due: {{ schedule.next_due }}
Active: {{ schedule.is_active }}
{% endif %}{% if log %}Log: #{{ log.id }}
Summary: {{ log.summary }}
Performed at: {{ log.performed_at }}
{% if log.parts_note %}Parts note: {{ log.parts_note }}
{% endif %}{% endif %}"""

MAINTENANCE_REQUESTER_SUBJECTS = {
    "schedule_created": "Maintenance scheduled for {{ machine.name }}",
    "schedule_updated": "Maintenance schedule changed for {{ machine.name }}",
    "schedule_deactivated": "Maintenance schedule paused for {{ machine.name }}",
    "schedule_completed": "Maintenance completed on {{ machine.name }}",
    "logged": "Maintenance recorded on {{ machine.name }}",
}

MAINTENANCE_REQUESTER_BODIES = {
    "schedule_created": (
        "Maintenance has been scheduled for this machine. It may be unavailable around "
        "the due date."
    ),
    "schedule_updated": "The maintenance schedule for this machine has changed.",
    "schedule_deactivated": "Scheduled maintenance for this machine has been paused.",
    "schedule_completed": "Scheduled maintenance on this machine is complete.",
    "logged": "Maintenance work on this machine has been recorded.",
}

# Deliberately thinner than the staff body: a member is told the machine and what it
# means for them, never the internal schedule ids, parts notes or engineer summaries.
MAINTENANCE_REQUESTER_TEXT = """Hello,

{{ makerspace.name }}
Machine: {{ machine.name }}
{% if schedule %}Next due: {{ schedule.next_due }}
{% endif %}
{{ next_steps }}
"""

# --- membership -----------------------------------------------------------------------

MEMBERSHIP_STAFF_SUBJECTS = {
    "request_pending": "{{ makerspace.name }}: membership request pending",
    "member_joined": "{{ makerspace.name }}: member joined",
}

MEMBERSHIP_STAFF_TEXTS = {
    "request_pending": (
        "Membership request #{{ request.id }} is pending. "
        "Applicant: {{ request.applicant }}."
    ),
    "member_joined": "Member joined: {{ member.username }}.",
}

MEMBERSHIP_REQUESTER_SUBJECTS = {
    "request_pending": "Your membership request at {{ makerspace.name }}",
    "member_joined": "Welcome to {{ makerspace.name }}",
}

MEMBERSHIP_REQUESTER_TEXTS = {
    "request_pending": """Hello {{ member.name|default:"there" }},

Your membership request at {{ makerspace.name }} has been received and is waiting for
review. We will be in touch once it has been looked at.
""",
    "member_joined": """Hello {{ member.name|default:"there" }},

Your membership at {{ makerspace.name }} is active. Welcome!
""",
}
