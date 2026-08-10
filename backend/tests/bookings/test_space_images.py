import pytest
from django.urls import reverse
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.bookings import services, storage
from apps.bookings.models import BookableSpace
from apps.makerspaces import lifecycle, limits
from apps.makerspaces.models import Makerspace, MakerspaceMembership

pytestmark = pytest.mark.django_db


def setup_space(slug):
    makerspace = Makerspace.objects.create(
        name=slug,
        slug=slug,
        resource_limit_overrides={'storage': 1000},
    )
    actor = User.objects.create_user(
        username=f'{slug}-manager',
        access_status=User.AccessStatus.ACTIVE,
    )
    MakerspaceMembership.objects.create(
        user=actor,
        makerspace=makerspace,
        role=MakerspaceMembership.Role.SPACE_MANAGER,
    )
    target = BookableSpace.objects.create(makerspace=makerspace, name='Studio')
    client = APIClient()
    client.force_authenticate(actor)
    return makerspace, target, client


def test_finalize_delete_accounting_and_compensation(
    monkeypatch,
    django_capture_on_commit_callbacks,
):
    makerspace, target, client = setup_space('booking-images')
    old_key = f'spaces/{makerspace.pk}/{target.pk}/images/old.png'
    new_key = f'spaces/{makerspace.pk}/{target.pk}/images/new.png'
    BookableSpace.objects.filter(pk=target.pk).update(image_key=old_key)
    makerspace.storage_bytes_used = 10
    makerspace.save(update_fields=['storage_bytes_used'])
    deleted = []
    monkeypatch.setattr(limits, 'is_self_host', lambda: False)
    monkeypatch.setattr(
        storage,
        'finalize_upload',
        lambda key: storage.FinalizeResult('ok', 25),
    )
    monkeypatch.setattr(storage, 'sniff_is_valid_image', lambda key: True)
    monkeypatch.setattr(
        storage,
        'object_size',
        lambda key: 10 if key == old_key else 25,
    )
    def record_delete(key):
        # Must report True like the real `delete_object` now does: the quota is released
        # only on a confirmed delete, so a double that returns None would make this test
        # assert the failure path while looking like it asserted the success one.
        deleted.append(key)
        return True

    monkeypatch.setattr(storage, 'delete_object', record_delete)
    with django_capture_on_commit_callbacks(execute=True):
        finalized = client.post(
            reverse('admin-bookable-space-image-finalize', kwargs={'pk': target.pk}),
            {'object_key': new_key},
            format='json',
        )
    makerspace.refresh_from_db()
    target.refresh_from_db()
    assert finalized.status_code == 200 and target.image_key == new_key
    assert makerspace.storage_bytes_used == 25 and old_key in deleted
    with django_capture_on_commit_callbacks(execute=True):
        removed = client.delete(
            reverse('admin-bookable-space-image-delete', kwargs={'pk': target.pk})
        )
    makerspace.refresh_from_db()
    target.refresh_from_db()
    assert removed.status_code == 204 and target.image_key is None
    assert makerspace.storage_bytes_used == 0 and new_key in deleted

    BookableSpace.objects.filter(pk=target.pk).update(image_key=old_key)
    makerspace.storage_bytes_used = 10
    makerspace.save(update_fields=['storage_bytes_used'])
    monkeypatch.setattr(
        services.audit,
        'record',
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError('audit')),
    )
    client.raise_request_exception = False
    failed = client.post(
        reverse('admin-bookable-space-image-finalize', kwargs={'pk': target.pk}),
        {'object_key': new_key},
        format='json',
    )
    makerspace.refresh_from_db()
    target.refresh_from_db()
    assert failed.status_code == 500 and target.image_key == old_key
    assert makerspace.storage_bytes_used == 10
    assert new_key in deleted and storage.staging_key(new_key) in deleted


def test_presign_inactive_images_and_purge_collection(monkeypatch):
    makerspace, target, client = setup_space('booking-presign')
    monkeypatch.setattr(
        storage,
        'presigned_upload',
        lambda key, content_type: {'url': 'https://upload'},
    )
    response = client.post(
        reverse('admin-bookable-space-image-presign', kwargs={'pk': target.pk}),
        {'filename': 'photo.png', 'content_type': 'image/png'},
        format='json',
    )
    prefix = f'spaces/{makerspace.pk}/{target.pk}/images/'
    assert response.status_code == 201
    assert response.data['object_key'].startswith(prefix)
    key = response.data['object_key']
    BookableSpace.objects.filter(pk=target.pk).update(image_key=key, is_active=False)
    assert key in lifecycle._collect_public_image_keys(makerspace)
    deleted = []
    monkeypatch.setattr(
        'apps.inventory.public_image_storage.delete_object',
        deleted.append,
    )
    lifecycle._delete_public_image_keys(
        lifecycle._collect_public_image_keys(makerspace)
    )
    assert deleted == [key]
    for name, method in (
        ('admin-bookable-space-image-presign', 'post'),
        ('admin-bookable-space-image-finalize', 'post'),
        ('admin-bookable-space-image-delete', 'delete'),
    ):
        result = getattr(client, method)(
            reverse(name, kwargs={'pk': target.pk}),
            {},
            format='json',
        )
        assert result.status_code == 400
