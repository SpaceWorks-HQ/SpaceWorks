# Established model barrel pattern; split to keep focused model modules below the file ceiling.
from apps.events.models_event import Event
from apps.events.models_collaborators import EventCollaborator
from apps.events.models_registration import EventRegistration
from apps.events.organizer_models import EventOrganizer

__all__ = ["Event", "EventCollaborator", "EventOrganizer", "EventRegistration"]
