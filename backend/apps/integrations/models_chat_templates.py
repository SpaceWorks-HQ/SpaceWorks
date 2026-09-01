"""One editable chat body per (makerspace, stream, key), shared by all four channels.

**One body, not four.** Slack, Mattermost, Discord and Telegram all receive plain text
here, so per-channel bodies would quadruple the editing surface and let an operator edit
one and forget the rest — shipping wording that differs by room for no reason. If a
channel ever needs genuinely different markup, that is a per-channel *renderer*, not a
per-channel stored body.

**Absence means today's behaviour.** With no row, the chat message stays exactly the
`LifecyclePayload.text` the adapter built. So this model changes nothing until an operator
edits one, and deleting a row reverts cleanly.

**Staff audience only, enforced in code** — see `chat_templates.render_chat_text`. A
webhook is a room: posting "your booking is confirmed" into it exposes that member's name
to everyone with channel access.
"""

from django.conf import settings
from django.db import models

from apps.integrations.notification_enums import NotificationFeature


class ChatTemplate(models.Model):
    makerspace = models.ForeignKey(
        "makerspaces.Makerspace",
        on_delete=models.CASCADE,
        related_name="chat_templates",
    )
    feature = models.CharField(max_length=32, choices=NotificationFeature.choices)
    event = models.CharField(max_length=64)
    text_body = models.TextField()
    # Same semantic as EmailTemplate.is_active: "use the built-in default", never
    # "suppress the message". Chat delivery is governed by the (feature, channel) matrix,
    # not by a template row.
    is_active = models.BooleanField(default=True)
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["makerspace", "feature", "event"],
                name="uniq_chat_template_per_event",
            )
        ]
        ordering = ["makerspace_id", "feature", "event"]

    def clean(self):
        from apps.integrations.chat_templates import validate_chat_template_string

        validate_chat_template_string(self.feature, self.event, self.text_body)

    def __str__(self):
        return f"{self.makerspace_id}:{self.feature}/{self.event} chat"
