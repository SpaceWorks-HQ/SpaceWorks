import re
from pathlib import Path

import pytest
from django.core.exceptions import ValidationError
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.admin_api.serializers_makerspaces import MakerspaceSerializer
from apps.audit.models import AuditLog
from apps.makerspaces.models import Makerspace, MakerspaceMembership, default_theme_config
from apps.makerspaces.platform import bootstrap_payload
from apps.makerspaces.theme_contrast import BODY_TEXT, FIXED_INKS, PRODUCT_FILL, SURFACES, contrast, contrast_failures, derive_palette
from apps.makerspaces.theme_validation import validate_theme_config
from tests.return_helpers import authenticated_client, make_member


def test_wcag_srgb_contrast_math():
    assert contrast((0, 0, 0), (255, 255, 255)) == 21
    assert contrast((255, 255, 255), (0, 0, 0)) == 21
    assert contrast((100, 100, 100), (100, 100, 100)) == 1
    assert contrast((117, 117, 117), (255, 255, 255)) == pytest.approx(4.6075, abs=.0001)


@pytest.mark.parametrize("primary", ["#000", "#fff", "#f3c3dd", "#004400", "#abc"])
def test_custom_palette_passes_every_text_and_ui_pair_in_both_modes(primary):
    theme = {"primary_color": primary, "accent_color": "#5a1633"}
    assert validate_theme_config(theme) == theme
    assert contrast_failures(theme) == []


def test_dark_derivation_matches_frontend_golden_values():
    theme = {"primary_color": "#f3c3dd", "accent_color": "#5a1633"}
    light, dark = derive_palette(theme, "light"), derive_palette(theme, "dark")
    assert light["fill"] == dark["fill"] == (243, 195, 221)
    assert light["foreground"] == dark["foreground"] == (0, 0, 0)
    assert light["ink"] == (90, 22, 51)
    assert dark["ink"] == (194, 169, 180)
    palette = derive_palette({"primary_color": "#004400"}, "light")
    assert palette["hover"] == (0, 63, 0)
    assert palette["active"] == (0, 57, 0)
    assert palette["foreground"] == (255, 255, 255)


def test_opaque_aa_is_not_enough_for_existing_translucent_counters():
    assert contrast((119, 119, 119), (0, 0, 0)) > 4.5
    with pytest.raises(ValidationError) as caught:
        validate_theme_config({"primary_color": "#777"})
    assert all(error.code == "theme_contrast" for error in caught.value.error_list)
    assert any("light: on-secondary/80 on secondary" in message for message in caught.value.messages)
    assert any("dark: on-secondary/80 on secondary" in message for message in caught.value.messages)


def test_serializer_and_control_model_refuse_unsafe_palette():
    serializer = MakerspaceSerializer(data={"theme_config": {"primary_color": "#777"}}, partial=True)
    assert not serializer.is_valid()
    assert serializer.errors["theme_config"]["code"] == "theme_contrast"
    space = Makerspace(name="Theme", slug="theme", theme_config={"primary_color": "#777"})
    with pytest.raises(ValidationError) as caught:
        space.clean()
    assert "theme_config" in caught.value.message_dict


def test_blank_defaults_use_product_palette_and_meet_aa():
    theme = default_theme_config()
    assert theme["primary_color"] == theme["accent_color"] == ""
    assert validate_theme_config(theme) == theme


def test_validation_surfaces_match_rendered_css_and_frontend_contract():
    # Both validators must guard the colours the browser actually renders. A
    # product neutral-surface edit must update the validation contract as well.
    frontend = Path(__file__).resolve().parents[3] / "frontend" / "src"
    if not frontend.exists():
        pytest.skip("Frontend source mount unavailable")
    css = re.sub(r"/\*.*?\*/", "", (frontend / "index.css").read_text(encoding="utf-8"), flags=re.S)
    ts = (frontend / "lib" / "brandColours.ts").read_text(encoding="utf-8")
    for mode, surfaces in SURFACES.items():
        selector = ":root {" if mode == "light" else ":root.dark {"
        start = css.index(selector)
        block = css[start:css.index("}", start)]
        for name, expected in zip(("bg", "surface", "panel"), surfaces):
            match = re.search(rf"--color-{name}:\s*([\d\s]+);", block)
            assert match
            assert tuple(map(int, match.group(1).split())) == expected
        source_line = next(line for line in ts.splitlines() if line.strip().startswith(f"{mode}:"))
        channels = tuple(map(int, re.findall(r"\d+", source_line)))
        assert channels == tuple(channel for surface in surfaces for channel in surface)
        assert f"--color-secondary: {' '.join(map(str, PRODUCT_FILL))};" in block
        for name, expected in zip(("ink", "muted"), BODY_TEXT[mode]):
            match = re.search(rf"--color-{name}:\s*([\d\s]+);", block)
            assert match
            assert tuple(map(int, match.group(1).split())) == expected
        body_source = ts.split("const BODY_TEXT", 1)[1].split("};", 1)[0]
        body_line = next(line for line in body_source.splitlines() if line.strip().startswith(f"{mode}:"))
        assert tuple(map(int, re.findall(r"\d+", body_line))) == tuple(channel for text in BODY_TEXT[mode] for channel in text)
        for name, expected in zip(("accent-ink", "success-ink", "warn-ink", "danger"), FIXED_INKS[mode]):
            match = re.search(rf"--color-{name}:\s*([\d\s]+);", block)
            assert match
            assert tuple(map(int, match.group(1).split())) == expected
        fixed_source = ts.split("const FIXED_INKS", 1)[1].split("};", 1)[0]
        fixed_line = next(line for line in fixed_source.splitlines() if line.strip().startswith(f"{mode}:"))
        assert tuple(map(int, re.findall(r"\d+", fixed_line))) == tuple(channel for text in FIXED_INKS[mode] for channel in text)
        for name, alpha in zip(("10", "15"), derive_palette({}, mode)["tint_alphas"]):
            match = re.search(rf"--brand-tint-{name}-alpha:\s*([\d.]+);", block)
            assert match
            assert float(match.group(1)) == pytest.approx(alpha)


def test_tint_strength_protects_normal_and_muted_text():
    palette = derive_palette({"primary_color": "#fff"}, "dark")
    assert palette["tint_alphas"] == pytest.approx((.048, .048))
    assert all(ratio >= minimum for pair, ratio, minimum in palette["pairs"] if pair.startswith("muted on"))


@pytest.mark.django_db
def test_theme_patch_contrast_400_does_not_write_or_audit():
    actor = User.objects.create_superuser(username="contrast-root", password="strong-password")
    space = Makerspace.objects.create(name="Contrast", slug="contrast")
    before = space.theme_config
    client = APIClient()
    client.force_authenticate(actor)
    response = client.patch(f"/api/v1/admin/makerspaces/{space.pk}", {
        "theme_config": {"primary_color": "#777", "accent_color": "#5a1633"},
    }, format="json")
    assert response.status_code == 400
    assert response.data["theme_config"]["code"] == "theme_contrast"
    assert any("on-secondary/80 on secondary" in message for message in response.data["theme_config"]["messages"])
    space.refresh_from_db()
    assert space.theme_config == before
    assert not AuditLog.objects.filter(makerspace=space, action="makerspace.updated").exists()


@pytest.mark.django_db
def test_dark_brand_fill_is_accepted_and_audited():
    actor = User.objects.create_superuser(username="dark-brand-root", password="strong-password")
    space = Makerspace.objects.create(name="Dark Brand", slug="dark-brand")
    client = APIClient()
    client.force_authenticate(actor)
    response = client.patch(f"/api/v1/admin/makerspaces/{space.pk}", {
        "theme_config": {"primary_color": "#004400", "accent_color": "#5a1633"},
    }, format="json")
    assert response.status_code == 200
    space.refresh_from_db()
    assert space.theme_config["primary_color"] == "#004400"
    entry = AuditLog.objects.get(makerspace=space, action="makerspace.updated")
    assert entry.actor == actor
    assert entry.meta == {"fields": ["theme_config"]}


@pytest.mark.django_db
@pytest.mark.parametrize("stored", [[], "malformed", {"primary_color": "red"}, {"primary_color": "#777"}])
def test_bootstrap_falls_back_for_invalid_restored_theme(stored):
    space = Makerspace.objects.create(name="Legacy Brand", slug="legacy-brand")
    Makerspace.objects.filter(pk=space.pk).update(theme_config=stored)
    space.refresh_from_db()
    assert bootstrap_payload(space)["theme"] == default_theme_config()


@pytest.mark.django_db
def test_bootstrap_colour_fallback_preserves_valid_mode_and_logo_without_writing():
    stored = {"mode": "dark", "primary_color": "#777", "accent_color": "#000",
              "logo_url": "https://example.com/legacy-logo.png"}
    space = Makerspace.objects.create(name="Legacy Logo", slug="legacy-logo", theme_config=stored)
    payload = bootstrap_payload(space)
    assert payload["theme"] == {**default_theme_config(), "mode": "dark", "logo_url": stored["logo_url"]}
    assert payload["makerspace"]["logo_url"] == stored["logo_url"]
    space.refresh_from_db()
    assert space.theme_config == stored
    assert not AuditLog.objects.filter(makerspace=space, action="makerspace.updated").exists()


@pytest.mark.django_db
def test_space_manager_can_update_only_their_own_theme_and_audits_the_actor():
    own = Makerspace.objects.create(name="Own Theme", slug="own-theme")
    other = Makerspace.objects.create(name="Other Theme", slug="other-theme")
    manager = make_member("theme-manager", own, role=User.Role.REQUESTER)
    client = authenticated_client(manager)
    theme = {"primary_color": "#004400", "accent_color": "#fff"}
    before = other.theme_config
    assert client.patch(f"/api/v1/admin/makerspaces/{other.pk}", {"theme_config": theme}, format="json").status_code == 404
    assert client.patch(f"/api/v1/admin/makerspaces/{own.pk}", {"theme_config": theme}, format="json").status_code == 200
    other.refresh_from_db()
    own.refresh_from_db()
    assert other.theme_config == before
    assert own.theme_config == theme
    assert not AuditLog.objects.filter(makerspace=other, action="makerspace.updated").exists()
    entry = AuditLog.objects.get(makerspace=own, action="makerspace.updated")
    assert entry.actor == manager
    assert entry.meta == {"fields": ["theme_config"]}


@pytest.mark.django_db
def test_inventory_manager_cannot_update_a_theme():
    space = Makerspace.objects.create(name="Staff Theme", slug="staff-theme")
    staff = make_member("theme-inventory", space, membership_role=MakerspaceMembership.Role.INVENTORY_MANAGER, role=User.Role.REQUESTER)
    before = space.theme_config
    response = authenticated_client(staff).patch(f"/api/v1/admin/makerspaces/{space.pk}", {"theme_config": {"primary_color": "#fff"}}, format="json")
    assert response.status_code == 404
    space.refresh_from_db()
    assert space.theme_config == before
    assert not AuditLog.objects.filter(makerspace=space, action="makerspace.updated").exists()


def test_links_and_semantic_inks_remain_readable_on_member_card_tints():
    from apps.makerspaces.theme_contrast import blend

    palette = derive_palette({"primary_color": "#f3c3dd", "accent_color": "#5a1633"}, "dark")
    mint_card = blend(SURFACES["dark"][2], (116, 221, 156), .15, False)
    assert contrast(palette["ink"], mint_card) >= 4.5
    pink_card = blend(SURFACES["dark"][2], palette["fill"], palette["tint_alphas"][1], False)
    assert all(contrast(ink, pink_card) >= 4.5 for ink in FIXED_INKS["dark"])


def test_secondary_tints_have_an_opaque_base_for_nested_member_cards():
    frontend = Path(__file__).resolve().parents[3] / "frontend" / "src"
    if not frontend.exists():
        pytest.skip("Frontend source mount unavailable")
    css = (frontend / "styles" / "components.css").read_text(encoding="utf-8")
    for alpha in ("10", "15"):
        fallback = float(alpha) / 100
        assert f"background-color: color-mix(in srgb, rgb(var(--color-secondary)) calc(var(--brand-tint-{alpha}-alpha, {fallback}) * 100%), rgb(var(--color-panel)));" in css
    directory = (frontend / "features" / "members" / "MemberDirectory.tsx").read_text(encoding="utf-8")
    assert 'className="desk-panel mt-2 border-secondary p-3"' in directory
