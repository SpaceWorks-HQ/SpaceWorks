"""Event cover image: upload/attach/clear, storage accounting, and the
registrations that stop an image object being stranded or double-claimed.
"""

from datetime import timedelta
from unittest.mock import Mock

import pytest
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from apps.audit.models import AuditLog
from apps.events.models import Event
from apps.machines.models import Machine, MachineType
from apps.makerspaces import lifecycle
from apps.makerspaces.models import Makerspace, MakerspaceMembership
from apps.accounts.models import User

pytestmark = pytest.mark.django_db


def make_space(slug='event-image'):
    return Makerspace.objects.create(name=slug, slug=slug)


def make_manager(name, space):
    user = User.objects.create_user(
        username=name, role=User.Role.REQUESTER,
        access_status=User.AccessStatus.ACTIVE,
    )
    MakerspaceMembership.objects.create(
        user=user, makerspace=space,
        role=MakerspaceMembership.Role.SPACE_MANAGER,
    )
    return user


def make_event(space, title='Workshop'):
    start = timezone.now() + timedelta(hours=1)
    return Event.objects.create(
        makerspace=space, title=title,
        starts_at=start, ends_at=start + timedelta(hours=1),
    )


def client_for(user):
    client = APIClient()
    client.force_authenticate(user)
    return client


def image_url(event):
    return reverse('admin-event-image', kwargs={'pk': event.id})


def mock_public_storage(monkeypatch, *, size=123, managed=False):
    from apps.inventory import public_image_storage

    if managed:
        # add_storage/free_storage are no-ops on self-host, so quota assertions
        # are only meaningful with managed mode forced on (the bookings
        # space-image tests force it the same way).
        from apps.makerspaces import limits

        monkeypatch.setattr(limits, 'is_self_host', lambda: False)
    monkeypatch.setattr(
        'apps.inventory.public_image_storage.presigned_upload',
        lambda object_key, content_type: {
            'url': 'http://minio/public-upload',
            'fields': {'key': object_key, 'Content-Type': content_type},
        },
    )
    monkeypatch.setattr(
        'apps.inventory.public_image_storage.finalize_upload',
        lambda object_key: public_image_storage._finalize_result(object_key, size),
    )
    monkeypatch.setattr(
        'apps.inventory.public_image_storage.sniff_is_valid_image',
        lambda object_key: True,
    )
    monkeypatch.setattr(
        'apps.inventory.public_image_storage.object_size', lambda object_key: size
    )
    delete = Mock()
    monkeypatch.setattr('apps.inventory.public_image_storage.delete_object', delete)
    return delete


def attach(client, event, monkeypatch):
    upload = client.post(
        image_url(event),
        {'content_type': 'image/png', 'filename': 'poster.png'},
        format='json',
    )
    object_key = upload.data['object_key']
    attached = client.put(image_url(event), {'object_key': object_key}, format='json')
    return upload, attached, object_key


def test_upload_attach_and_public_exposure(monkeypatch, settings):
    settings.PUBLIC_IMAGE_BASE_URL = 'http://cdn.test/public-images'
    mock_public_storage(monkeypatch)
    space = make_space()
    client = client_for(make_manager('event-image-manager', space))
    event = make_event(space)

    upload, attached, object_key = attach(client, event, monkeypatch)
    event.refresh_from_db()

    assert upload.status_code == 201
    assert object_key.startswith(f'event/{space.id}/')
    assert attached.status_code == 200
    assert event.image_key == object_key
    # Staff see the resolved URL, never the raw key.
    assert attached.data['image_url'] == f'http://cdn.test/public-images/{object_key}'
    assert 'image_key' not in attached.data
    assert AuditLog.objects.filter(action='event.image_updated').exists()


def test_public_event_payload_carries_the_image_url(monkeypatch, settings):
    settings.PUBLIC_IMAGE_BASE_URL = 'http://cdn.test/public-images'
    mock_public_storage(monkeypatch)
    space = make_space()
    client = client_for(make_manager('event-image-public', space))
    event = make_event(space)
    event.is_public = True
    event.status = Event.Status.PUBLISHED
    event.save(update_fields=['is_public', 'status'])

    _, _, object_key = attach(client, event, monkeypatch)
    public = APIClient().get(
        reverse('public-event-list', kwargs={'makerspace_slug': space.slug})
    )

    assert public.status_code == 200
    assert public.data[0]['image_url'] == f'http://cdn.test/public-images/{object_key}'


def test_attach_rejects_another_makerspaces_object_key(monkeypatch):
    mock_public_storage(monkeypatch)
    space = make_space()
    other = make_space('event-image-other')
    client = client_for(make_manager('event-image-cross', space))
    event = make_event(space)

    response = client.put(
        image_url(event),
        {'object_key': f'event/{other.id}/abc.png'},
        format='json',
    )

    assert response.status_code == 400
    event.refresh_from_db()
    assert event.image_key == ''


def test_attach_rejects_a_key_already_claimed_by_a_machine(monkeypatch):
    """A shared key would make clearing one object blank the other's image."""
    mock_public_storage(monkeypatch)
    space = make_space()
    client = client_for(make_manager('event-image-claimed', space))
    event = make_event(space)
    machine_type = MachineType.objects.create(
        makerspace=space, slug='laser', name='Laser',
    )
    taken_key = f'event/{space.id}/taken.png'
    Machine.objects.create(
        makerspace=space, machine_type=machine_type, name='Laser 1',
        image_key=taken_key,
    )

    response = client.put(image_url(event), {'object_key': taken_key}, format='json')

    assert response.status_code == 400
    event.refresh_from_db()
    assert event.image_key == ''


def test_clearing_the_image_frees_storage_and_deletes_the_object(
    monkeypatch, django_capture_on_commit_callbacks,
):
    delete = mock_public_storage(monkeypatch, size=500, managed=True)
    space = make_space()
    client = client_for(make_manager('event-image-clear', space))
    event = make_event(space)

    _, _, object_key = attach(client, event, monkeypatch)
    space.refresh_from_db()
    after_attach = space.storage_bytes_used

    # The object delete is deferred to on_commit, so it only runs inside this.
    with django_capture_on_commit_callbacks(execute=True):
        cleared = client.delete(image_url(event))
    event.refresh_from_db()
    space.refresh_from_db()

    assert cleared.status_code == 200
    assert event.image_key == ''
    assert after_attach == 500
    assert space.storage_bytes_used == 0
    delete.assert_any_call(object_key)
    assert AuditLog.objects.filter(action='event.image_removed').exists()


def test_replacing_the_image_frees_the_previous_object(
    monkeypatch, django_capture_on_commit_callbacks,
):
    delete = mock_public_storage(monkeypatch, size=200, managed=True)
    space = make_space()
    client = client_for(make_manager('event-image-replace', space))
    event = make_event(space)

    _, _, first_key = attach(client, event, monkeypatch)
    with django_capture_on_commit_callbacks(execute=True):
        _, _, second_key = attach(client, event, monkeypatch)
    event.refresh_from_db()
    space.refresh_from_db()

    assert first_key != second_key
    assert event.image_key == second_key
    # One image held, not two: the replaced object was freed and deleted.
    assert space.storage_bytes_used == 200
    delete.assert_any_call(first_key)


def test_makerspace_purge_collects_the_event_image_key(monkeypatch):
    """Without the lifecycle registration the object would outlive every row
    that could name it."""
    mock_public_storage(monkeypatch)
    space = make_space()
    client = client_for(make_manager('event-image-purge', space))
    event = make_event(space)

    _, _, object_key = attach(client, event, monkeypatch)

    assert object_key in lifecycle._collect_public_image_keys(space)


def test_module_purge_plan_collects_the_event_image_key(monkeypatch):
    from apps.makerspaces.module_purge_collectors import events_public_images

    mock_public_storage(monkeypatch)
    space = make_space()
    client = client_for(make_manager('event-image-module-purge', space))
    event = make_event(space)

    _, _, object_key = attach(client, event, monkeypatch)

    assert object_key in events_public_images(space)


def test_recompute_storage_counts_event_images(monkeypatch):
    from apps.makerspaces.management.commands.recompute_storage import Command

    mock_public_storage(monkeypatch)
    space = make_space()
    client = client_for(make_manager('event-image-recompute', space))
    event = make_event(space)

    _, _, object_key = attach(client, event, monkeypatch)

    assert object_key in Command._public_image_keys(space)
