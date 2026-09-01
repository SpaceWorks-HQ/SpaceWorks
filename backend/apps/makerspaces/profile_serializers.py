"""Boundary validation for maker profiles.

Two rules here are security, not tidiness:

* **link URLs must be http or https.** These render as `href` on a page other members
  read, so a stored `javascript:` URL is stored XSS with a click as the trigger. The
  scheme allowlist is the whole defence; escaping the text does nothing for an href.
* **every list is capped.** They are member-writable JSON columns on a row the member
  controls, so an uncapped list is an unbounded write to the database and an unbounded
  render on everyone else's screen.
"""

from urllib.parse import urlparse

from rest_framework import serializers

MAX_INTERESTS = 20
MAX_LANGUAGES = 10
MAX_EDUCATION = 10
MAX_LINKS = 10
MAX_PROJECTS = 20
MAX_BIO = 2000
ALLOWED_LINK_SCHEMES = ("http", "https")


class TagListField(serializers.ListField):
    def __init__(self, *, max_items, **kwargs):
        super().__init__(
            child=serializers.CharField(max_length=60, allow_blank=False, trim_whitespace=True),
            required=False,
            allow_empty=True,
            max_length=max_items,
            **kwargs,
        )


class EducationEntrySerializer(serializers.Serializer):
    institution = serializers.CharField(max_length=200)
    qualification = serializers.CharField(max_length=200, required=False, allow_blank=True, default="")
    year = serializers.CharField(max_length=20, required=False, allow_blank=True, default="")


class ProjectLinkSerializer(serializers.Serializer):
    label = serializers.CharField(max_length=60)
    url = serializers.URLField(max_length=500)

    def validate_url(self, value):
        if urlparse(value).scheme.lower() not in ALLOWED_LINK_SCHEMES:
            raise serializers.ValidationError("Links must start with http:// or https://.")
        return value


class ProjectWriteSerializer(serializers.Serializer):
    # Present for a project being kept or edited, absent for a new one. Anything the
    # caller does not send back is deleted -- see `profile_services.save_projects` for
    # why replace rather than merge.
    id = serializers.IntegerField(required=False)
    title = serializers.CharField(max_length=200)
    description = serializers.CharField(max_length=4000, required=False, allow_blank=True, default="")
    links = serializers.ListField(
        child=ProjectLinkSerializer(), required=False, allow_empty=True, max_length=MAX_LINKS
    )


class ProfileWriteSerializer(serializers.Serializer):
    is_visible = serializers.BooleanField(required=False)
    show_attended_events = serializers.BooleanField(required=False)
    headline = serializers.CharField(max_length=200, required=False, allow_blank=True)
    institution = serializers.CharField(max_length=200, required=False, allow_blank=True)
    bio = serializers.CharField(max_length=MAX_BIO, required=False, allow_blank=True)
    interests = TagListField(max_items=MAX_INTERESTS)
    languages = TagListField(max_items=MAX_LANGUAGES)
    education = serializers.ListField(
        child=EducationEntrySerializer(), required=False, allow_empty=True, max_length=MAX_EDUCATION
    )
    github_username = serializers.RegexField(
        r"^[A-Za-z0-9](?:[A-Za-z0-9]|-(?=[A-Za-z0-9])){0,38}$",
        required=False,
        allow_blank=True,
    )
    projects = serializers.ListField(
        child=ProjectWriteSerializer(), required=False, allow_empty=True, max_length=MAX_PROJECTS
    )


class ProjectReadSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    title = serializers.CharField()
    description = serializers.CharField()
    links = serializers.JSONField()
    image_url = serializers.CharField(allow_null=True)


class AttendedEventSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    title = serializers.CharField()
    starts_at = serializers.DateTimeField()


class ProfileActivitySerializer(serializers.Serializer):
    events_attended = serializers.IntegerField(required=False)
    events_registered = serializers.IntegerField(required=False)
    recent_attended_events = AttendedEventSerializer(many=True, required=False)

    def to_representation(self, instance):
        # Filtering against the source mapping makes omission explicit: module-disabled
        # keys must stay absent rather than becoming null or an invented empty list.
        representation = super().to_representation(instance)
        return {
            key: value for key, value in representation.items() if key in instance
        }


class ProfileReadSerializer(serializers.Serializer):
    membership_id = serializers.IntegerField()
    display_name = serializers.CharField()
    is_visible = serializers.BooleanField()
    show_attended_events = serializers.BooleanField()
    headline = serializers.CharField()
    institution = serializers.CharField()
    bio = serializers.CharField()
    avatar_url = serializers.CharField(allow_null=True)
    interests = serializers.JSONField()
    languages = serializers.JSONField()
    education = serializers.JSONField()
    github_username = serializers.CharField()
    github_contributions = serializers.IntegerField(allow_null=True)
    projects = ProjectReadSerializer(many=True)
    activity = ProfileActivitySerializer()


class DirectoryEntrySerializer(serializers.Serializer):
    """The listing row. Display name and avatar only -- never email, never phone.

    Otherwise "see who else is here" is an address harvest performed by anyone a space
    admits, which is a different thing from what the member agreed to publish.
    """

    membership_id = serializers.IntegerField()
    display_name = serializers.CharField()
    headline = serializers.CharField()
    avatar_url = serializers.CharField(allow_null=True)


class DirectorySerializer(serializers.Serializer):
    members = DirectoryEntrySerializer(many=True)
    # Members who have not opted in contribute to this and nothing else, so the space
    # can still show its size without naming anyone who did not agree to be named.
    hidden_count = serializers.IntegerField()
