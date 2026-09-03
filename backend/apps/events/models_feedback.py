import json

from django.core.exceptions import ValidationError
from django.core.validators import MaxLengthValidator
from django.db import models
from django.db.models import Q

from apps.encryption.mappers import ScopedPiiModelMixin
from apps.events.feedback_validation import validate_feedback_schema
from apps.events.models_event import Event
from apps.events.models_registration import EventRegistration


def _question_signature(question):
    return tuple(
        json.dumps(question.get(key), sort_keys=True)
        for key in ("id", "label", "type", "options", "required")
    )


class EventFeedbackSurvey(models.Model):
    event = models.OneToOneField(
        Event,
        on_delete=models.CASCADE,
        related_name="feedback_survey",
    )
    title = models.CharField(max_length=200)
    thank_you_text = models.TextField(
        blank=True,
        validators=[MaxLengthValidator(2_000)],
    )
    questions = models.JSONField(default=list, validators=[validate_feedback_schema])
    is_open = models.BooleanField(default=False)
    certificate_enabled = models.BooleanField(default=False)
    answered_question_ids = models.JSONField(default=list, blank=True)
    opened_at = models.DateTimeField(null=True, blank=True)
    closed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=Q(is_open=False) | ~Q(questions=[]),
                name="event_feedback_open_has_questions",
            ),
        ]

    def clean(self):
        super().clean()
        self.questions = validate_feedback_schema(self.questions)
        ids = [question["id"] for question in self.questions]
        if not isinstance(self.answered_question_ids, list) or any(
            not isinstance(value, str) for value in self.answered_question_ids
        ):
            raise ValidationError({"answered_question_ids": "Must be a list of IDs."})
        if not set(self.answered_question_ids).issubset(ids):
            raise ValidationError(
                {"questions": "Answered questions cannot be removed."}
            )
        if self.is_open and not self.questions:
            raise ValidationError({"questions": "An open survey needs a question."})
        if not self.pk:
            return
        original = type(self).objects.filter(pk=self.pk).first()
        if original is None or not original.responses.exists():
            return
        if self.certificate_enabled != original.certificate_enabled:
            raise ValidationError(
                {"certificate_enabled": "Certificate mode is frozen after a response."}
            )
        old = {question["id"]: question for question in original.questions}
        new = {question["id"]: question for question in self.questions}
        for question_id in original.answered_question_ids:
            if question_id not in new or _question_signature(old[question_id]) != _question_signature(new[question_id]):
                raise ValidationError(
                    {"questions": f"Answered question {question_id!r} is immutable."}
                )

    def save(self, *args, **kwargs):
        self.title = (self.title or "").strip()
        self.thank_you_text = (self.thank_you_text or "").strip()
        self.full_clean(validate_unique=False, validate_constraints=False)
        return super().save(*args, **kwargs)


class EventFeedbackResponse(ScopedPiiModelMixin, models.Model):
    survey = models.ForeignKey(
        EventFeedbackSurvey,
        on_delete=models.CASCADE,
        related_name="responses",
    )
    registration = models.ForeignKey(
        EventRegistration,
        on_delete=models.PROTECT,
        related_name="feedback_responses",
        null=True,
        blank=True,
    )
    answers_snapshot = models.TextField()
    certificate_requested = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at", "id"]
        constraints = [
            models.CheckConstraint(
                condition=(
                    Q(registration__isnull=True, certificate_requested=False)
                    | Q(registration__isnull=False, certificate_requested=True)
                ),
                name="event_feedback_response_mode_matches_identity",
            ),
            models.UniqueConstraint(
                fields=["survey", "registration"],
                condition=Q(registration__isnull=False),
                name="uniq_event_feedback_registration",
            ),
        ]
        indexes = [
            models.Index(
                fields=["survey", "created_at", "id"],
                name="event_feedback_response_idx",
            ),
        ]

    def clean(self):
        super().clean()
        if self.registration_id and self.survey_id:
            if self.registration.event_id != self.survey.event_id:
                raise ValidationError(
                    {"registration": "Registration must belong to the survey event."}
                )

    def save(self, *args, **kwargs):
        if self.pk is not None:
            raise RuntimeError("EventFeedbackResponse rows are immutable.")
        self.full_clean(validate_unique=False, validate_constraints=False)
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise RuntimeError("EventFeedbackResponse rows are immutable.")
