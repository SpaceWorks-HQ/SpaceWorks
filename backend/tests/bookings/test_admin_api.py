from datetime import timedelta

import pytest
from django.contrib import admin
from django.urls import resolve, reverse
from django.utils import timezone
from drf_spectacular.generators import SchemaGenerator
from rest_framework.exceptions import ValidationError
from rest_framework.test import APIClient, APIRequestFactory

from apps.accounts import rbac
from apps.accounts.models import User
from apps.bookings import services, storage
from apps.bookings.models import BookableSpace, Booking
from apps.makerspaces import origin_scope
from apps.makerspaces import limits
from apps.makerspaces.models import Makerspace, MakerspaceMembership
from tests.handout_roles import grant_handout

pytestmark = pytest.mark.django_db


def tenant(slug='booking-admin', **values):
    return Makerspace.objects.create(name=slug, slug=slug, **values)


def user(name, role=User.Role.REQUESTER, **values):
    values.setdefault('access_status', User.AccessStatus.ACTIVE)
    return User.objects.create_user(username=name, role=role, **values)


def grant(actor, makerspace, role=MakerspaceMembership.Role.SPACE_MANAGER):
    return MakerspaceMembership.objects.create(
        user=actor,
        makerspace=makerspace,
        role=role,
    )


def space(makerspace, **values):
    defaults = {'name': 'Development Room', 'is_public': True}
    defaults.update(values)
    return BookableSpace.objects.create(makerspace=makerspace, **defaults)


def booking(bookable_space, **values):
    start = values.pop('starts_at', timezone.now() - timedelta(hours=2))
    defaults = {
        'name': 'Ada',
        'email': 'ada@example.com',
        'phone': '123',
        'starts_at': start,
        'ends_at': start + timedelta(hours=1),
    }
    defaults.update(values)
    return Booking.objects.create(space=bookable_space, **defaults)


def client_for(actor):
    client = APIClient()
    client.force_authenticate(actor)
    return client


def urls(makerspace, bookable_space, row):
    return [
        ('get', reverse('admin-bookable-space-list-create', kwargs={'makerspace_id': makerspace.pk}), None),
        ('post', reverse('admin-bookable-space-list-create', kwargs={'makerspace_id': makerspace.pk}), {'name': 'New'}),
        ('get', reverse('admin-bookable-space-detail', kwargs={'pk': bookable_space.pk}), None),
        ('patch', reverse('admin-bookable-space-detail', kwargs={'pk': bookable_space.pk}), {'name': 'Edit'}),
        ('post', reverse('admin-bookable-space-deactivate', kwargs={'pk': bookable_space.pk}), {}),
        ('post', reverse('admin-bookable-space-image-presign', kwargs={'pk': bookable_space.pk}), {'filename': 'x.png', 'content_type': 'image/png'}),
        ('post', reverse('admin-bookable-space-image-finalize', kwargs={'pk': bookable_space.pk}), {'object_key': 'x'}),
        ('delete', reverse('admin-bookable-space-image-delete', kwargs={'pk': bookable_space.pk}), None),
        ('get', reverse('admin-space-booking-list', kwargs={'pk': bookable_space.pk}), None),
        ('get', reverse('admin-bookable-space-booking-rules', kwargs={'pk': bookable_space.pk}), None),
        ('patch', reverse('admin-bookable-space-booking-rules', kwargs={'pk': bookable_space.pk}), {'booking_lead_time_minutes': 90}),
        ('post', reverse('admin-booking-approve', kwargs={'pk': row.pk}), {}),
        ('post', reverse('admin-booking-reject', kwargs={'pk': row.pk}), {}),
        ('post', reverse('admin-booking-cancel', kwargs={'pk': row.pk}), {}),
        ('post', reverse('admin-booking-complete', kwargs={'pk': row.pk}), {}),
        ('post', reverse('admin-booking-no-show', kwargs={'pk': row.pk}), {}),
    ]


def call(client, method, url, data):
    return getattr(client, method)(url, data=data, format='json')


def test_manage_bookings_grant_delta_is_exact():
    makerspace = tenant()
    allowed = set()
    for role, _label in MakerspaceMembership.Role.choices:
        actor = user(f'booking-{role}')
        grant(actor, makerspace, role)
        if rbac.can(actor, rbac.Action.MANAGE_BOOKINGS, makerspace.pk):
            allowed.add(role)
    root = user('booking-root', role=User.Role.SUPERADMIN, is_superuser=True)
    assert allowed == {MakerspaceMembership.Role.SPACE_MANAGER}
    assert rbac.can(root, rbac.Action.MANAGE_BOOKINGS, makerspace.pk)


def test_every_endpoint_enforces_active_staff_and_module():
    makerspace = tenant('booking-guards')
    bookable_space, row = space(makerspace), None
    row = booking(bookable_space)
    cases = (
        (APIClient(), 401),
        (client_for(user('booking-inactive', is_active=False)), 403),
        (
            client_for(
                user(
                    'booking-suspended',
                    access_status=User.AccessStatus.SUSPENDED,
                )
            ),
            403,
        ),
        (client_for(user('booking-outsider')), 404),
    )
    for client, expected_status in cases:
        assert all(
            call(client, method, url, data).status_code == expected_status
            for method, url, data in urls(makerspace, bookable_space, row)
        )
    manager = user('booking-module-manager')
    grant(manager, makerspace)
    makerspace.enabled_modules.remove('bookings')
    makerspace.save(update_fields=['enabled_modules'])
    assert all(
        call(client_for(manager), method, url, data).status_code == 400
        for method, url, data in urls(makerspace, bookable_space, row)
    )


def test_invisible_object_scopes_return_404_before_permission():
    cross_target = tenant('booking-cross-target')
    cross_actor = user('booking-cross-manager')
    grant(cross_actor, tenant('booking-cross-own'))
    archived = tenant('booking-archived', archived_at=timezone.now())
    archived_actor = user('booking-archived-manager')
    grant(archived_actor, archived)
    hidden = tenant(
        'booking-hidden',
        superadmin_access_enabled=False,
    )
    hidden_actor = user(
        'booking-hidden-root',
        role=User.Role.SUPERADMIN,
        is_superuser=True,
    )
    for makerspace, actor in (
        (cross_target, cross_actor),
        (archived, archived_actor),
        (hidden, hidden_actor),
    ):
        target = space(makerspace)
        row = booking(target)
        assert all(
            call(client_for(actor), method, url, data).status_code == 404
            for method, url, data in urls(makerspace, target, row)
        )


@pytest.mark.parametrize(
    'role',
    [
        MakerspaceMembership.Role.INVENTORY_MANAGER,
        MakerspaceMembership.Role.PRINT_MANAGER,
    ],
)
def test_visible_underprivileged_roles_get_403(role):
    makerspace = tenant(f'booking-denied-{role}')
    actor = user(f'booking-denied-user-{role}')
    grant(actor, makerspace, role)
    target = space(makerspace)
    assert client_for(actor).get(
        reverse('admin-bookable-space-detail', kwargs={'pk': target.pk})
    ).status_code == 403


def test_visible_front_desk_role_gets_403():
    """Separate from the parametrized legacy roles because handover is a custom role now:
    there is no enum member to feed the parametrize list."""
    makerspace = tenant('booking-denied-front-desk')
    actor = user('booking-denied-user-front-desk')
    grant_handout(actor, makerspace)
    target = space(makerspace)
    assert client_for(actor).get(
        reverse('admin-bookable-space-detail', kwargs={'pk': target.pk})
    ).status_code == 403


def test_space_crud_allowlist_flags_and_validation():
    makerspace, actor = tenant('booking-write'), user('booking-manager')
    grant(actor, makerspace)
    client = client_for(actor)
    created = client.post(
        reverse('admin-bookable-space-list-create', kwargs={'makerspace_id': makerspace.pk}),
        {
            'name': 'Studio',
            'show_public_availability': True,
            'show_public_booker_names': True,
            'image_key': 'secret',
            'is_active': False,
        },
        format='json',
    )
    assert created.status_code == 201
    assert set(created.data) == {
        'id', 'public_token', 'makerspace_id', 'name', 'kind', 'description',
        'capacity', 'location', 'image_url', 'is_public',
        'show_public_availability', 'show_public_booker_names', 'is_active',
        'approval_mode', 'custom_form', 'requester_notifications_enabled',
        'payment_amount',
        'min_booking_duration_minutes', 'max_booking_duration_minutes',
        'booking_lead_time_minutes', 'max_booking_advance_days',
        'effective_requester_notifications_enabled',
        'created_by_id', 'created_at', 'updated_at',
    }
    assert 'image_key' not in created.data and created.data['is_active'] is True
    invalid = client.patch(
        reverse('admin-bookable-space-detail', kwargs={'pk': created.data['id']}),
        {'show_public_availability': False},
        format='json',
    )
    assert invalid.status_code == 400
    assert invalid.data['code'] == 'booker_names_requires_availability'


def test_booking_control_admins_are_read_only():
    for model in (BookableSpace, Booking):
        model_admin = admin.site._registry[model]
        assert model_admin.has_add_permission(None) is False
        assert model_admin.has_change_permission(None) is False
        assert model_admin.has_delete_permission(None) is False
        assert set(model_admin.readonly_fields) == {
            field.name for field in model._meta.fields
        }


def test_duplicate_finalize_loser_preserves_winner_object_and_accounting(
    monkeypatch,
):
    makerspace = tenant(
        'booking-finalize-race',
        resource_limit_overrides={'storage': 1000},
    )
    actor = user('booking-finalize-race-manager')
    grant(actor, makerspace)
    target = space(makerspace)
    object_key = (
        f'spaces/{makerspace.pk}/{target.pk}/images/concurrent.png'
    )
    staging_key = storage.staging_key(object_key)
    live_objects = {object_key, staging_key}
    original_set_space_image = services.set_space_image

    monkeypatch.setattr(limits, 'is_self_host', lambda: False)
    monkeypatch.setattr(
        storage,
        'finalize_upload',
        lambda key: storage.FinalizeResult('ok', 25),
    )
    monkeypatch.setattr(storage, 'sniff_is_valid_image', lambda key: True)
    monkeypatch.setattr(storage, 'delete_object', live_objects.discard)

    def winner_attaches_before_loser(*args, **kwargs):
        original_set_space_image(*args, **kwargs)
        raise ValidationError(
            {'object_key': 'This image was attached by another request.'}
        )

    monkeypatch.setattr(
        services,
        'set_space_image',
        winner_attaches_before_loser,
    )
    response = client_for(actor).post(
        reverse(
            'admin-bookable-space-image-finalize',
            kwargs={'pk': target.pk},
        ),
        {'object_key': object_key},
        format='json',
    )

    target.refresh_from_db()
    makerspace.refresh_from_db()
    assert response.status_code == 400
    assert target.image_key == object_key
    assert object_key in live_objects
    assert staging_key not in live_objects
    assert makerspace.storage_bytes_used == 25


def test_booking_list_is_space_scoped_and_lifecycle_is_typed():
    own, other = tenant('booking-own'), tenant('booking-other')
    actor = user('booking-list-manager')
    grant(actor, own)
    own_space, other_space = space(own), space(other)
    own_row, secret = booking(own_space), booking(other_space, email='secret@example.com')
    client = client_for(actor)
    response = client.get(
        reverse('admin-space-booking-list', kwargs={'pk': own_space.pk})
    )
    assert [item['id'] for item in response.data['results']] == [own_row.pk]
    assert response.data['results'][0]['email'] == 'ada@example.com'
    assert secret.email not in str(response.data)
    cancelled = client.post(
        reverse('admin-booking-cancel', kwargs={'pk': own_row.pk}),
        {},
        format='json',
    )
    conflict = client.post(
        reverse('admin-booking-cancel', kwargs={'pk': own_row.pk}),
        {},
        format='json',
    )
    assert cancelled.data['status'] == Booking.Status.CANCELLED
    assert conflict.status_code == 409 and conflict.data['code'] == 'invalid_transition'


def test_staff_urls_origin_registry_and_openapi():
    makerspace = tenant('booking-origin')
    target, row = space(makerspace), None
    row = booking(target)
    factory = APIRequestFactory()
    for _method, url, _data in urls(makerspace, target, row):
        match = resolve(url)
        request = factory.get(url)
        request.resolver_match = match
        view = match.func.view_class(**match.func.view_initkwargs)
        view.kwargs = match.kwargs
        assert origin_scope._target_makerspace_id(request, view) == makerspace.pk
    schema = SchemaGenerator().get_schema(request=None, public=True)
    expected = {
        '/api/v1/admin/makerspaces/{makerspace_id}/spaces/': {'get', 'post'},
        '/api/v1/admin/spaces/{id}/': {'get', 'patch'},
        '/api/v1/admin/spaces/{id}/deactivate/': {'post'},
        '/api/v1/admin/spaces/{id}/image/presign/': {'post'},
        '/api/v1/admin/spaces/{id}/image/finalize/': {'post'},
        '/api/v1/admin/spaces/{id}/image/': {'delete'},
        '/api/v1/admin/spaces/{id}/bookings/': {'get'},
        '/api/v1/admin/spaces/{id}/booking-rules/': {'get', 'patch'},
        '/api/v1/admin/bookings/{id}/approve/': {'post'},
        '/api/v1/admin/bookings/{id}/reject/': {'post'},
        '/api/v1/admin/bookings/{id}/cancel/': {'post'},
        '/api/v1/admin/bookings/{id}/complete/': {'post'},
        '/api/v1/admin/bookings/{id}/no-show/': {'post'},
    }
    assert all(methods <= schema['paths'][path].keys() for path, methods in expected.items())
    fields = schema['components']['schemas']['BookableSpaceAdmin']['properties']
    assert 'image_key' not in fields
    assert {'show_public_availability', 'show_public_booker_names'} <= fields.keys()
    expected_errors = {
        '/api/v1/admin/makerspaces/{makerspace_id}/spaces/': {
            'get': {'403', '404'},
            'post': {'400', '403', '404'},
        },
        '/api/v1/admin/spaces/{id}/': {
            'get': {'403', '404'},
            'patch': {'400', '403', '404', '409'},
        },
        '/api/v1/admin/spaces/{id}/deactivate/': {
            'post': {'400', '403', '404', '409'},
        },
        '/api/v1/admin/spaces/{id}/image/presign/': {
            'post': {'400', '403', '404', '503'},
        },
        '/api/v1/admin/spaces/{id}/image/finalize/': {
            'post': {'400', '403', '404', '503'},
        },
        '/api/v1/admin/spaces/{id}/image/': {
            'delete': {'400', '403', '404', '503'},
        },
        '/api/v1/admin/spaces/{id}/bookings/': {
            'get': {'400', '403', '404'},
        },
        '/api/v1/admin/spaces/{id}/booking-rules/': {
            'get': {'400', '403', '404'},
            'patch': {'400', '403', '404', '409'},
        },
        '/api/v1/admin/bookings/{id}/approve/': {
            'post': {'400', '403', '404', '409'},
        },
        '/api/v1/admin/bookings/{id}/reject/': {
            'post': {'400', '403', '404', '409'},
        },
        '/api/v1/admin/bookings/{id}/cancel/': {
            'post': {'400', '403', '404', '409'},
        },
        '/api/v1/admin/bookings/{id}/complete/': {
            'post': {'400', '403', '404', '409'},
        },
        '/api/v1/admin/bookings/{id}/no-show/': {
            'post': {'400', '403', '404', '409'},
        },
    }
    rules_path = '/api/v1/admin/spaces/{id}/booking-rules/'
    for path, methods in expected_errors.items():
        for method, codes in methods.items():
            responses = schema['paths'][path][method]['responses']
            assert codes <= responses.keys()
            for code in codes:
                error_schema = responses[code]['content']['application/json'][
                    'schema'
                ]
                if path == rules_path and code == '400':
                    # Booking-rule 400s are DRF field-error maps (and the
                    # module-disabled {"module": ...} map), documented as a
                    # loose validation-error object, not HardwareRequestError.
                    assert '$ref' not in error_schema
                    assert error_schema.get('type') == 'object'
                else:
                    assert error_schema['$ref'].endswith('/HardwareRequestError')
