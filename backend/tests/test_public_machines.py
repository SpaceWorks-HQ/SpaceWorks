from datetime import date
from decimal import Decimal

import pytest
from django.urls import reverse
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.inventory.models import Category, InventoryProduct
from apps.machines.models import (
    Machine,
    MachineConsumable,
    MachineDocument,
    MachineErrorLog,
    MachineOperator,
    MachineType,
    MachineUsageEntry,
)
from apps.makerspaces.models import Makerspace
from apps.warranty.models import Warranty, WarrantyDocument


pytestmark = pytest.mark.django_db

PUBLIC_MACHINE_KEYS = {
    'name',
    'machine_type',
    'image_url',
    'status',
    'usage_hours',
}
PUBLIC_MACHINE_TYPE_KEYS = {'name', 'icon'}


def make_public_space(slug):
    return Makerspace.objects.create(
        name=slug,
        slug=slug,
        public_inventory_enabled=True,
        public_stats_enabled=True,
    )


def make_machine(makerspace, name, *, is_public, is_active=True, **overrides):
    defaults = {
        'makerspace': makerspace,
        'machine_type': MachineType.objects.get(
            makerspace__isnull=True,
            slug='laser_cutter',
        ),
        'name': name,
        'is_public': is_public,
        'is_active': is_active,
    }
    defaults.update(overrides)
    return Machine.objects.create(**defaults)


def public_machines_url(makerspace):
    return reverse('public-machines', kwargs={'makerspace_slug': makerspace.slug})


def public_stats_url(makerspace):
    return reverse(
        'v1:public-makerspace-stats',
        kwargs={'makerspace_slug': makerspace.slug},
    )


def test_public_machine_list_is_exact_and_excludes_private_and_retired():
    makerspace = make_public_space('public-machines-list')
    public = make_machine(makerspace, 'Public laser', is_public=True)
    private = make_machine(makerspace, 'Private laser', is_public=False)
    retired = make_machine(
        makerspace,
        'Retired laser',
        is_public=True,
        is_active=False,
    )
    MachineUsageEntry.objects.create(machine=public, hours=Decimal('2.25'))
    MachineUsageEntry.objects.create(machine=private, hours=Decimal('7.00'))
    MachineUsageEntry.objects.create(machine=retired, hours=Decimal('11.00'))

    list_response = APIClient().get(public_machines_url(makerspace))
    stats_response = APIClient().get(public_stats_url(makerspace))

    assert list_response.status_code == 200
    assert [row['name'] for row in list_response.data['results']] == ['Public laser']
    row = list_response.data['results'][0]
    assert set(row) == PUBLIC_MACHINE_KEYS
    assert set(row['machine_type']) == PUBLIC_MACHINE_TYPE_KEYS
    assert Decimal(row['usage_hours']) == Decimal('2.25')
    assert private.name not in str(list_response.data)
    assert retired.name not in str(list_response.data)
    assert stats_response.status_code == 200
    assert set(stats_response.data['machines']) == {'usage_hours'}
    assert stats_response.data['machines']['usage_hours'] == 2.25


def test_public_machine_list_and_stats_respect_module_and_stats_toggles():
    makerspace = make_public_space('public-machines-toggles')
    make_machine(makerspace, 'Toggle machine', is_public=True)
    makerspace.enabled_modules = [
        name for name in makerspace.enabled_modules if name != 'machines'
    ]
    makerspace.save(update_fields=['enabled_modules'])

    list_response = APIClient().get(public_machines_url(makerspace))
    stats_response = APIClient().get(public_stats_url(makerspace))

    assert list_response.status_code == 400
    assert "machines is disabled" in str(list_response.data)
    assert stats_response.status_code == 200
    assert stats_response.data['machines'] is None

    makerspace.public_stats_enabled = False
    makerspace.save(update_fields=['public_stats_enabled'])
    assert APIClient().get(public_stats_url(makerspace)).status_code == 404


def test_machine_sensitive_sentinels_never_leak_to_any_public_surface():
    makerspace = make_public_space('public-machines-leak-sweep')
    sentinels = {
        'WARRANTY_VENDOR_SENTINEL',
        'WARRANTY_CONTACT_SENTINEL',
        'warranty-secret-document.pdf',
        'machine-secret-document.pdf',
        'OPERATOR_USERNAME_SENTINEL',
        'MACHINE_NOTES_SENTINEL',
        'MACHINE_LOCATION_SENTINEL',
        'https://camera.invalid/CAMERA_SENTINEL',
        'FIRMWARE_SENTINEL',
        'ERROR_LOG_SENTINEL',
        'CONSUMABLE_LABEL_SENTINEL',
        'CONSUMABLE_NOTE_SENTINEL',
    }
    machine = make_machine(
        makerspace,
        'Safe public machine name',
        is_public=True,
        location='MACHINE_LOCATION_SENTINEL',
        notes='MACHINE_NOTES_SENTINEL',
        camera_feed_url='https://camera.invalid/CAMERA_SENTINEL',
        firmware_version='FIRMWARE_SENTINEL',
    )
    operator = User.objects.create_user(
        username='OPERATOR_USERNAME_SENTINEL',
        access_status=User.AccessStatus.ACTIVE,
    )
    MachineOperator.objects.create(
        machine=machine,
        user=operator,
        access_level=MachineOperator.AccessLevel.FULL,
    )
    MachineDocument.objects.create(
        machine=machine,
        doc_type=MachineDocument.DocType.MANUAL,
        object_key=f'machines/{makerspace.pk}/secret.pdf',
        original_filename='machine-secret-document.pdf',
        content_type='application/pdf',
        size_bytes=12,
    )
    MachineErrorLog.objects.create(
        machine=machine,
        severity=MachineErrorLog.Severity.CRITICAL,
        message='ERROR_LOG_SENTINEL',
    )
    MachineConsumable.objects.create(
        machine=machine,
        measurement=MachineConsumable.Measurement.GRAMS,
        label='CONSUMABLE_LABEL_SENTINEL',
        remaining=Decimal('50.00'),
        note='CONSUMABLE_NOTE_SENTINEL',
    )
    warranty = Warranty.objects.create(
        makerspace=makerspace,
        machine=machine,
        purchased_on=date(2025, 1, 2),
        warranty_expires_on=date(2030, 3, 4),
        vendor_name='WARRANTY_VENDOR_SENTINEL',
        vendor_contact='WARRANTY_CONTACT_SENTINEL',
    )
    WarrantyDocument.objects.create(
        warranty=warranty,
        object_key=f'warranty/{makerspace.pk}/secret.pdf',
        original_filename='warranty-secret-document.pdf',
        content_type='application/pdf',
        size_bytes=34,
    )
    category = Category.objects.create(
        makerspace=makerspace,
        name='Safe category',
        slug='safe-category',
    )
    InventoryProduct.objects.create(
        makerspace=makerspace,
        category=category,
        name='Safe inventory item',
        is_public=True,
    )

    client = APIClient()
    responses = [
        client.get(f'{reverse("tenant-bootstrap")}?slug={makerspace.slug}'),
        client.get(reverse('public-config')),
        client.get(
            reverse(
                'v1:public-inventory',
                kwargs={'makerspace_slug': makerspace.slug},
            )
        ),
        client.get(
            reverse(
                'v1:public-inventory-categories',
                kwargs={'makerspace_slug': makerspace.slug},
            )
        ),
        client.get(public_stats_url(makerspace)),
        client.get(public_machines_url(makerspace)),
    ]

    assert all(response.status_code == 200 for response in responses)
    combined = '\n'.join(str(response.data) for response in responses)
    for sentinel in sentinels:
        assert sentinel not in combined
    machine_payload = responses[-1].data['results'][0]
    assert set(machine_payload) == PUBLIC_MACHINE_KEYS
    assert set(machine_payload['machine_type']) == PUBLIC_MACHINE_TYPE_KEYS
