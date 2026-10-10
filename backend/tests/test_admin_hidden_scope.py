from types import SimpleNamespace

import pytest
from django.contrib import admin
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import RequestFactory
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import User
from apps.makerspaces import lifecycle
from apps.inventory.models import InventoryProduct
from apps.makerspaces.models import Makerspace, MakerspaceMembership
from apps.encryption.models import PiiGlobalWriteFence, PiiMakerspaceWriteFence
from config.admin_access import GLOBAL_ADMIN_MODELS
from config.admin_access import NESTED_MAKERSPACE_LOOKUPS

pytestmark = pytest.mark.django_db


def test_pii_write_fence_scope_decisions_are_explicit():
    assert "encryption.piiglobalwritefence" in GLOBAL_ADMIN_MODELS
    assert _makerspace_lookup_paths(PiiMakerspaceWriteFence) == {"makerspace_id"}
    assert _makerspace_lookup_paths(PiiGlobalWriteFence) == set()


def _makerspace_lookup_paths(model, max_depth=4):
    if model is Makerspace:
        return {"id"}

    paths = set()

    def walk(current_model, prefix, depth, seen):
        if depth > max_depth:
            return

        for field in current_model._meta.get_fields():
            if not getattr(field, "is_relation", False):
                continue
            if getattr(field, "auto_created", False) and not getattr(field, "concrete", False):
                continue
            if not (getattr(field, "many_to_one", False) or getattr(field, "one_to_one", False)):
                continue

            remote_field = getattr(field, "remote_field", None)
            related_model = getattr(remote_field, "model", None) if remote_field else None
            if related_model is None or isinstance(related_model, str):
                continue

            field_path = prefix + [field.name]
            if related_model is Makerspace:
                paths.add("__".join(field_path) + "_id")
            elif depth < max_depth and related_model not in seen:
                walk(related_model, field_path, depth + 1, seen | {related_model})

    walk(model, [], 1, {model})
    return paths


def test_every_registered_admin_resolves_a_makerspace_decision():
    failures = []

    for model, model_admin in sorted(
        admin.site._registry.items(),
        key=lambda item: item[0]._meta.label_lower,
    ):
        model_key = f"{model._meta.app_label}.{model._meta.model_name}"
        lookup = (
            model_admin.resolve_hidden_lookup()
            if hasattr(model_admin, "resolve_hidden_lookup")
            else None
        )
        paths = _makerspace_lookup_paths(model)

        if model_key in GLOBAL_ADMIN_MODELS:
            if lookup is not None:
                failures.append(
                    f"{model_key}: listed GLOBAL_ADMIN_MODELS but resolved {lookup!r}"
                )
            continue

        if paths:
            if lookup is None:
                failures.append(
                    f"{model_key}: reaches Makerspace via {sorted(paths)} but resolved None"
                )
            elif lookup not in paths:
                failures.append(
                    f"{model_key}: resolved {lookup!r}, expected one of {sorted(paths)}"
                )
        elif lookup is not None:
            failures.append(f"{model_key}: has no Makerspace path but resolved {lookup!r}")
        else:
            failures.append(
                f"{model_key}: has no Makerspace path and is missing from GLOBAL_ADMIN_MODELS"
            )

    assert not failures, "Admin hidden-scope drift:\n" + "\n".join(failures)


def test_machine_service_models_have_explicit_nested_scope_decisions():
    assert NESTED_MAKERSPACE_LOOKUPS["machines.servicebucket"] == "machine__makerspace_id"
    assert NESTED_MAKERSPACE_LOOKUPS["machines.servicerequestconsumption"] == (
        "service_request__makerspace_id"
    )


def test_inventory_product_admin_hides_disabled_makerspace_rows():
    hidden_space = Makerspace.objects.create(
        name="Hidden",
        slug="hidden-admin-scope",
        superadmin_access_enabled=False,
    )
    hidden_manager = get_user_model().objects.create_user(
        username="hidden-admin-scope-manager",
        email="hidden-admin-scope-manager@example.com",
        role=User.Role.SPACE_MANAGER,
        access_status=User.AccessStatus.ACTIVE,
    )
    MakerspaceMembership.objects.create(
        user=hidden_manager,
        makerspace=hidden_space,
        role=MakerspaceMembership.Role.SPACE_MANAGER,
    )
    visible_space = Makerspace.objects.create(
        name="Visible",
        slug="visible-admin-scope",
    )
    hidden_product = InventoryProduct.objects.create(
        makerspace=hidden_space,
        name="Hidden product",
    )
    visible_product = InventoryProduct.objects.create(
        makerspace=visible_space,
        name="Visible product",
    )
    superadmin = get_user_model().objects.create_user(
        username="scope-superadmin",
        email="scope-superadmin@example.com",
        password="test-pass",
        role=User.Role.SUPERADMIN,
        access_status=User.AccessStatus.ACTIVE,
        is_staff=True,
        is_superuser=True,
    )
    request = RequestFactory().get("/control/inventory/inventoryproduct/")
    request.user = superadmin

    queryset = admin.site._registry[InventoryProduct].get_queryset(request)

    assert hidden_product not in queryset
    assert visible_product in queryset


def test_makerspace_admin_lists_disabled_makerspace_for_governance_visibility():
    hidden_space = Makerspace.objects.create(
        name="Hidden",
        slug="hidden-admin-visible",
        superadmin_access_enabled=False,
    )
    visible_space = Makerspace.objects.create(
        name="Visible",
        slug="visible-admin-visible",
    )
    superadmin = get_user_model().objects.create_user(
        username="scope-visible-superadmin",
        email="scope-visible-superadmin@example.com",
        password="test-pass",
        role=User.Role.SUPERADMIN,
        access_status=User.AccessStatus.ACTIVE,
        is_staff=True,
        is_superuser=True,
    )
    request = RequestFactory().get("/control/makerspaces/makerspace/")
    request.user = superadmin
    request.resolver_match = SimpleNamespace(url_name="makerspaces_makerspace_changelist")

    queryset = admin.site._registry[Makerspace].get_queryset(request)

    assert hidden_space in queryset
    assert visible_space in queryset


def test_makerspace_changelist_shows_hidden_and_visible_makerspaces(client):
    hidden_space = Makerspace.objects.create(
        name="Hidden Changelist",
        slug="hidden-changelist",
        superadmin_access_enabled=False,
    )
    visible_space = Makerspace.objects.create(
        name="Visible Changelist",
        slug="visible-changelist",
    )
    superadmin = get_user_model().objects.create_user(
        username="changelist-superadmin",
        email="changelist-superadmin@example.com",
        password="test-pass",
        role=User.Role.SUPERADMIN,
        access_status=User.AccessStatus.ACTIVE,
        is_staff=True,
        is_superuser=True,
    )
    client.force_login(superadmin)

    response = client.get(reverse("admin:makerspaces_makerspace_changelist"))

    assert response.status_code == 200
    html = response.content.decode()
    assert hidden_space.name in html
    assert visible_space.name in html


def test_makerspace_change_page_denies_hidden_and_allows_visible(client):
    hidden_space = Makerspace.objects.create(
        name="Hidden Change",
        slug="hidden-change",
        superadmin_access_enabled=False,
    )
    visible_space = Makerspace.objects.create(
        name="Visible Change",
        slug="visible-change",
    )
    superadmin = get_user_model().objects.create_user(
        username="change-page-superadmin",
        email="change-page-superadmin@example.com",
        password="test-pass",
        role=User.Role.SUPERADMIN,
        access_status=User.AccessStatus.ACTIVE,
        is_staff=True,
        is_superuser=True,
    )
    client.force_login(superadmin)

    hidden_response = client.get(
        reverse("admin:makerspaces_makerspace_change", args=[hidden_space.pk])
    )
    visible_response = client.get(
        reverse("admin:makerspaces_makerspace_change", args=[visible_space.pk])
    )

    assert hidden_response.status_code in {302, 403, 404}
    assert visible_response.status_code == 200


def test_makerspace_autocomplete_hides_disabled_makerspaces(client):
    hidden_space = Makerspace.objects.create(
        name="Hidden Autocomplete",
        slug="hidden-autocomplete",
        superadmin_access_enabled=False,
    )
    visible_space = Makerspace.objects.create(
        name="Visible Autocomplete",
        slug="visible-autocomplete",
    )
    superadmin = get_user_model().objects.create_user(
        username="autocomplete-superadmin",
        email="autocomplete-superadmin@example.com",
        password="test-pass",
        role=User.Role.SUPERADMIN,
        access_status=User.AccessStatus.ACTIVE,
        is_staff=True,
        is_superuser=True,
    )
    client.force_login(superadmin)

    response = client.get(
        reverse("admin:autocomplete"),
        {
            "app_label": "inventory",
            "model_name": "category",
            "field_name": "makerspace",
            "term": "Autocomplete",
        },
    )

    assert response.status_code == 200
    result_text = {row["text"] for row in response.json()["results"]}
    assert str(hidden_space) not in result_text
    assert str(visible_space) in result_text


def test_unarchive_rejects_hidden_makerspace():
    superadmin = get_user_model().objects.create_user(
        username="hidden-unarchive-superadmin",
        email="hidden-unarchive-superadmin@example.com",
        password="test-pass",
        role=User.Role.SUPERADMIN,
        access_status=User.AccessStatus.ACTIVE,
        is_staff=True,
        is_superuser=True,
    )
    hidden_space = Makerspace.objects.create(
        name="Hidden Unarchive",
        slug="hidden-unarchive",
        superadmin_access_enabled=False,
        archived_at=timezone.now(),
        archived_by=superadmin,
    )

    with pytest.raises(ValidationError, match="Cannot unarchive a hidden makerspace."):
        lifecycle.unarchive(hidden_space, superadmin)



def test_verification_run_and_event_admins_hide_disabled_makerspace_rows():
    from apps.audit.models import AuditVerificationRun, AuditVerificationRunEvent

    assert NESTED_MAKERSPACE_LOOKUPS["audit.auditverificationrunevent"] == "run__makerspace_id"
    hidden_space = Makerspace.objects.create(
        name="Hidden runs", slug="hidden-vrun-scope", superadmin_access_enabled=False,
    )
    visible_space = Makerspace.objects.create(name="Visible runs", slug="visible-vrun-scope")
    runs, events = {}, {}
    for space in (hidden_space, visible_space):
        run = AuditVerificationRun.objects.create(
            makerspace=space, snapshot_max_id=0, filter_fingerprint="f" * 64,
        )
        runs[space.slug] = run
        events[space.slug] = AuditVerificationRunEvent.objects.create(run=run, state="QUEUED")
    superadmin = get_user_model().objects.create_user(
        username="vrun-scope-superadmin", email="vrun-scope-superadmin@example.com",
        password="test-pass", role=User.Role.SUPERADMIN, access_status=User.AccessStatus.ACTIVE,
        is_staff=True, is_superuser=True,
    )
    request = RequestFactory().get("/control/audit/auditverificationrun/")
    request.user = superadmin

    run_rows = admin.site._registry[AuditVerificationRun].get_queryset(request)
    event_rows = admin.site._registry[AuditVerificationRunEvent].get_queryset(request)

    assert runs["hidden-vrun-scope"] not in run_rows and runs["visible-vrun-scope"] in run_rows
    assert events["hidden-vrun-scope"] not in event_rows
    assert events["visible-vrun-scope"] in event_rows
    run_admin = admin.site._registry[AuditVerificationRun]
    assert not run_admin.has_add_permission(request)
    assert not run_admin.has_change_permission(request)
    assert not run_admin.has_delete_permission(request)
