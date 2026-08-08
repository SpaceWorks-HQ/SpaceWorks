"""Render the chat body for one lifecycle event.

Two guarantees, and the second is a security boundary rather than a convenience:

* **Fallback is the adapter's own text.** No row, an inactive row, an unknown event or a
  render failure all resolve to the `LifecyclePayload.text` the caller already built. A
  broken template must never turn into a blank message posted to a staff room.
* **Chat is a STAFF surface.** `render_chat_text` refuses a requester-audience context and
  the callers never pass one. A webhook is a room, not an inbox: posting "your booking is
  confirmed, Alex Maker" into it exposes that member to everyone with channel access,
  including people who are not staff at all. This is enforced in code and pinned by a test
  so a future call site cannot leak member-facing content into a shared room.
"""

import logging

from django.core.exceptions import ValidationError
from django.template import Context, Template, TemplateSyntaxError

from apps.integrations.email_templates_registry import get_entry
from apps.integrations.email_templates_registry_fablab import STREAM_FOR_FEATURE

logger = logging.getLogger(__name__)

CHAT_AUDIENCE = "staff"


class RequesterContentInChatError(Exception):
    """Raised when member-facing content is routed at a chat room."""


def stream_for_feature(feature):
    """The email stream a notification feature's templates live under.

    Chat templates are keyed by feature (that is what the matrix and the fan-out speak),
    but their variables are the email registry's, so rendering has to cross over.
    """
    return STREAM_FOR_FEATURE.get(feature, feature)


def chat_entry(feature, event):
    """The registry entry whose `fields`/`sample_context` govern a chat body.

    Deliberately the STAFF entry: a chat body may only ever be built from staff-audience
    variables, so the editor cannot offer a member-facing field it would then leak.
    """
    return get_entry(stream_for_feature(feature), CHAT_AUDIENCE, event)


def validate_chat_template_string(feature, event, text_body):
    entry = chat_entry(feature, event)
    if entry is None:
        raise ValidationError("Unknown chat template feature or event.")
    try:
        Template(text_body or "").render(Context(entry.sample_context, autoescape=False))
    except TemplateSyntaxError as exc:
        raise ValidationError(f"Chat template has invalid syntax: {exc}") from exc
    except Exception as exc:
        raise ValidationError(f"Chat template has invalid syntax: {exc}") from exc


def render_chat_text(makerspace, feature, event, fallback_text, context=None, *, audience=CHAT_AUDIENCE):
    if audience != CHAT_AUDIENCE:
        raise RequesterContentInChatError(
            "Chat channels are a staff surface; requester content must go to email only."
        )
    if not context:
        return fallback_text

    from apps.integrations.models_chat_templates import ChatTemplate

    try:
        row = ChatTemplate.objects.filter(
            makerspace=makerspace, feature=feature, event=event, is_active=True
        ).first()
    except Exception:
        logger.warning(
            "chat_template_lookup_failed",
            extra={"makerspace_id": getattr(makerspace, "pk", None), "feature": feature},
        )
        return fallback_text

    if row is None:
        return fallback_text

    try:
        # autoescape off: this is plain text posted to a chat API, and escaping would
        # render "&amp;" in a Slack message. The body is operator-authored, never
        # user-supplied, and it is not HTML.
        rendered = Template(row.text_body or "").render(
            Context(context, autoescape=False)
        )
    except Exception:
        logger.warning(
            "chat_template_render_failed",
            extra={"makerspace_id": getattr(makerspace, "pk", None), "feature": feature},
            exc_info=True,
        )
        return fallback_text

    # An empty render is a broken template, not an intentional silence: chat delivery is
    # governed by the (feature, channel) matrix, so falling back is the safe reading.
    return rendered.strip() or fallback_text
