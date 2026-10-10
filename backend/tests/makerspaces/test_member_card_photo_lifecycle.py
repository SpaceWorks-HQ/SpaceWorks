"""Card photo consent, staging promotion, quota release and private preview pins."""
from unittest.mock import Mock

import pytest
from django.utils import timezone
from django.urls import reverse
from rest_framework.exceptions import ValidationError

from apps.audit.models import AuditLog
from apps.evidence import storage
from apps.makerspaces import member_card_services, member_card_storage
from tests.makerspaces.test_membership_j1 import manager, member_role, space, user
from apps.makerspaces.models import MakerspaceMembership
from tests.return_helpers import authenticated_client

pytestmark = pytest.mark.django_db


@pytest.fixture
def photo_card():
    makerspace = space("photo-lifecycle")
    boss = manager(makerspace, "photo-lifecycle-manager")
    membership = MakerspaceMembership.objects.create(
        makerspace=makerspace, user=user("photo-lifecycle-member"),
        assigned_role=member_role(makerspace), role="custom",
    )
    return boss, member_card_services.issue_card(boss, membership)


@pytest.fixture
def objects(monkeypatch):
    """Storage I/O is the only fake; the endpoint, service, row and audits are real."""
    rows = {}
    monkeypatch.setattr(storage, "object_size", lambda key: rows.get(key))
    monkeypatch.setattr(storage, "validate_evidence_object", lambda key: None)
    monkeypatch.setattr(storage, "copy_object", lambda source, dest: rows.update({dest: rows[source]}))
    monkeypatch.setattr(storage, "delete_object", lambda key: rows.pop(key, None))
    return rows


@pytest.mark.parametrize("method", ["post", "put"])
def test_presign_binds_mime_and_only_allows_the_staging_key(photo_card, monkeypatch, settings, method):
    _, card = photo_card
    settings.STORAGE_PRESIGN_METHOD = method
    client = Mock()
    client.generate_presigned_post.return_value = {"url": "https://storage.test", "fields": {}}
    client.generate_presigned_url.return_value = "https://storage.test"
    monkeypatch.setattr(storage, "_public_client", lambda: client)
    response = authenticated_client(card.membership.user).post(
        reverse("member-card-photo", args=[card.makerspace_id]), {"content_type": "image/jpeg"}, format="json",
    )
    assert response.status_code == 201
    final = response.data["object_key"]
    assert final.startswith(f"member-cards/{card.makerspace_id}/")
    if method == "post":
        arguments = client.generate_presigned_post.call_args.kwargs
        assert arguments["Key"] == storage.staging_key(final)
        assert arguments["Fields"] == {"Content-Type": "image/jpeg"}
        assert ["content-length-range", 1, settings.EVIDENCE_MAX_BYTES] in arguments["Conditions"]
    else:
        assert client.generate_presigned_url.call_args.kwargs["Params"]["Key"] == storage.staging_key(final)


def test_finalize_requires_consent_promotes_once_and_delete_releases_quota(photo_card, objects, monkeypatch):
    _, card = photo_card
    client = authenticated_client(card.membership.user)
    final = f"member-cards/{card.makerspace_id}/uploaded"
    objects[storage.staging_key(final)] = 1200
    added, freed = [], []
    monkeypatch.setattr(member_card_storage, "add_storage", lambda ms, size: added.append(size))
    monkeypatch.setattr(member_card_storage, "free_storage", lambda ms, size: freed.append(size))
    url = reverse("member-card-photo", args=[card.makerspace_id])
    body = {"object_key": final, "content_type": "image/jpeg", "consent": False}
    assert client.put(url, body, format="json").status_code == 400
    assert objects == {storage.staging_key(final): 1200}
    assert not AuditLog.objects.filter(action="member_card.photo_updated").exists()
    body["consent"] = True
    assert client.put(url, body, format="json").status_code == 200
    card.refresh_from_db()
    assert objects == {final: 1200}
    assert (card.photo_object_key, card.photo_size_bytes) == (final, 1200)
    assert card.photo_consent_at and card.photo_consent_version == member_card_storage.PHOTO_CONSENT_VERSION
    assert added == [1200]
    assert client.put(url, body, format="json").status_code == 400
    assert AuditLog.objects.filter(action="member_card.photo_updated", actor=card.membership.user).count() == 1
    assert client.delete(url).status_code == 200
    card.refresh_from_db()
    assert not objects and freed == [1200]
    assert (card.photo_object_key, card.photo_consent_at, card.photo_size_bytes) == ("", None, None)
    assert AuditLog.objects.filter(action="member_card.photo_removed", actor=card.membership.user).count() == 1


def test_photo_validation_refuses_foreign_keys_missing_uploads_and_oversize(photo_card, objects, settings):
    _, card = photo_card
    for key in ("member-cards/another-space/upload", f"member-cards/{card.makerspace_id}/nested/upload"):
        with pytest.raises(ValidationError, match="Unknown upload"):
            member_card_storage.finalize_photo(card.membership.user, card, object_key=key, content_type="image/jpeg", consent=True)
    final = f"member-cards/{card.makerspace_id}/missing"
    with pytest.raises(ValidationError, match="Upload not found"):
        member_card_storage.finalize_photo(card.membership.user, card, object_key=final, content_type="image/jpeg", consent=True)
    objects[storage.staging_key(final)] = settings.EVIDENCE_MAX_BYTES + 1
    with pytest.raises(ValidationError, match="size limit"):
        member_card_storage.finalize_photo(card.membership.user, card, object_key=final, content_type="image/jpeg", consent=True)
    assert not objects


def test_revoking_a_photo_card_releases_storage_and_preview_is_watermarked(photo_card, objects, monkeypatch):
    boss, card = photo_card
    # The photo fields travel as a set (member_card_photo_all_or_nothing).
    card.photo_object_key = f"member-cards/{card.makerspace_id}/face"
    card.photo_content_type = "image/jpeg"
    card.photo_size_bytes = 1234
    card.photo_consent_at = timezone.now()
    card.photo_consent_version = member_card_storage.PHOTO_CONSENT_VERSION
    card.save()
    freed = []
    monkeypatch.setattr(member_card_storage, "free_storage", lambda ms, size: freed.append(size))
    monkeypatch.setattr(member_card_storage, "photo_bytes", lambda card: None)
    # Spy on the snapshot the preview renders: the watermark is a property of the drawn
    # card, so pin it there rather than by parsing reportlab's compressed page streams.
    from apps.makerspaces import member_card_views

    watermarks = []
    real_snapshot = member_card_views.snapshot_for

    def spy(card, **kwargs):
        watermarks.append(kwargs.get("watermark"))
        return real_snapshot(card, **kwargs)

    monkeypatch.setattr(member_card_views, "snapshot_for", spy)
    response = authenticated_client(card.membership.user).get(reverse("member-card-preview", args=[card.makerspace_id]))
    assert response.status_code == 200
    assert response["Content-Type"] == "application/pdf"
    assert response.content.startswith(b"%PDF")
    assert watermarks == ["PREVIEW - not valid"]
    member_card_services.revoke_card(boss, card)
    assert freed == [1234]
