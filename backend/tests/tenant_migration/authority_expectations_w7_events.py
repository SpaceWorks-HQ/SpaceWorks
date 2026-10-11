"""Independent authority pins for hashed event access and discount credentials."""
from apps.tenant_migration.tenant_dump_types import AuthorityDisposition as D

EVENT_TICKETING_EXPECTED = {
    ("events.Event", "registration_audience"): (D.PRESERVE,),
    ("events.EventSeries", "registration_audience"): (D.PRESERVE,),
    ("events.EventRegistration", "registration_audience"): (D.PRESERVE,),
    ("events.EventTicketType", "audience"): (D.PRESERVE,),
    ("events.EventTicketType", "is_active"): (D.PRESERVE,),
    ("events.EventInvite", "code_digest"): (D.RESET,),
    ("events.EventInvite", "email_digest"): (D.RESET,),
    ("events.EventInvite", "revoked_at"): (D.RESET,),
    ("events.EventPromoCode", "code_digest"): (D.RESET,),
    ("events.EventPromoCode", "revoked_at"): (D.RESET,),
}
