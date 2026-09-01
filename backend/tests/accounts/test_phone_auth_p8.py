"""Phase 8 -- phone as a login identity.

Tests external behaviour: the enumeration contract, the verified-only gate, the
member-surface restriction, and that the whole feature stays dormant when no SMS
provider is configured.
"""

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.accounts.models_phone import PhoneChallengePurpose, PhoneVerificationChallenge
from apps.accounts.phone_numbers import InvalidPhoneNumber, normalize_e164
from apps.integrations.models_sms import PlatformSmsSettings
from tests.return_helpers import make_user

pytestmark = pytest.mark.django_db

LOGIN_START = "/api/v1/auth/phone/login/start"
LOGIN_CONFIRM = "/api/v1/auth/phone/login/confirm"
LINK_START = "/api/v1/auth/phone/link/start"
LINK_CONFIRM = "/api/v1/auth/phone/link/confirm"
UNLINK = "/api/v1/auth/phone"
CONFIG = "/api/v1/config"

NUMBER = "+14155552671"
OTHER_NUMBER = "+14155559999"


@pytest.fixture
def sms_on(monkeypatch):
    """Configure SMS and capture every outbound text instead of sending it."""
    PlatformSmsSettings.objects.update_or_create(
        pk=1,
        defaults={
            "is_enabled": True,
            "provider": "twilio",
            "account_sid": "AC_test",
            "from_number": "+15005550006",
        },
    )
    row = PlatformSmsSettings.objects.get(pk=1)
    row.set_auth_token("token-test")
    row.save()

    sent = []

    def _fake_send(*, to, body):
        sent.append({"to": to, "body": body})
        return True

    monkeypatch.setattr("apps.accounts.services_phone.send_sms", _fake_send)
    return sent


def code_from(sent):
    """Pull the 6-digit code out of the captured message body."""
    import re

    return re.search(r"\b(\d{6})\b", sent[-1]["body"]).group(1)


def verified_member(username="phone-member", number=NUMBER):
    user = make_user(username, role=User.Role.REQUESTER, password="pw-strong-123")
    user.phone_e164 = number
    user.save(update_fields=["phone_e164"])
    # Two steps on purpose: save() clears phone_verified_at whenever phone_e164 changes,
    # so the stamp is written afterwards through the queryset -- the same shape the real
    # linking service uses.
    User.objects.filter(pk=user.pk).update(phone_verified_at=timezone.now())
    user.refresh_from_db()
    return user


# --- normalisation ---------------------------------------------------------------


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("+14155552671", "+14155552671"),
        ("+1 (415) 555-2671", "+14155552671"),
        ("0014155552671", "+14155552671"),
        ("  +14155552671  ", "+14155552671"),
    ],
)
def test_normalisation_canonicalises_equivalent_spellings(raw, expected):
    # Different spellings of one number must collide on the unique index rather than
    # becoming two accounts.
    assert normalize_e164(raw) == expected


@pytest.mark.parametrize("raw", ["4155552671", "+0155552671", "", "abc", "+1234", None])
def test_normalisation_rejects_ambiguous_or_malformed_numbers(raw):
    with pytest.raises(InvalidPhoneNumber):
        normalize_e164(raw)


# --- dormancy --------------------------------------------------------------------


def test_phone_login_is_absent_from_config_until_sms_is_configured():
    body = APIClient().get(CONFIG).json()
    assert "phone_login" not in body


def test_phone_login_appears_in_config_once_configured(sms_on):
    assert APIClient().get(CONFIG).json()["phone_login"] == {"enabled": True}


def test_login_start_404s_when_sms_is_unconfigured():
    response = APIClient().post(LOGIN_START, {"phone": NUMBER}, format="json")
    assert response.status_code == 404


def test_disabling_the_master_switch_hides_the_feature_without_losing_credentials(sms_on):
    PlatformSmsSettings.objects.filter(pk=1).update(is_enabled=False)
    assert "phone_login" not in APIClient().get(CONFIG).json()
    # The credential survives, so re-enabling does not require re-entering it.
    assert PlatformSmsSettings.objects.get(pk=1).get_auth_token() == "token-test"


# --- enumeration contract --------------------------------------------------------


def test_login_start_response_is_identical_for_known_and_unknown_numbers(sms_on):
    verified_member()
    client = APIClient()
    known = client.post(LOGIN_START, {"phone": NUMBER}, format="json")
    unknown = client.post(LOGIN_START, {"phone": OTHER_NUMBER}, format="json")
    assert known.status_code == unknown.status_code == 200
    assert known.json() == unknown.json()
    # Only the known number was actually texted.
    assert [msg["to"] for msg in sms_on] == [NUMBER]


def test_login_start_does_not_reveal_a_suspended_account(sms_on):
    user = verified_member()
    User.objects.filter(pk=user.pk).update(
        access_status=User.AccessStatus.SUSPENDED
    )
    response = APIClient().post(LOGIN_START, {"phone": NUMBER}, format="json")
    assert response.status_code == 200
    assert sms_on == []  # no text, and no distinguishable response


def test_login_start_treats_a_malformed_number_as_a_generic_ack(sms_on):
    response = APIClient().post(LOGIN_START, {"phone": "not-a-number"}, format="json")
    assert response.status_code == 200
    assert sms_on == []


# --- the verified-only gate ------------------------------------------------------


def test_an_unverified_number_cannot_be_used_to_sign_in(sms_on):
    user = make_user("unverified-phone", role=User.Role.REQUESTER)
    # A number present but never verified -- e.g. written straight into the column.
    User.objects.filter(pk=user.pk).update(phone_e164=NUMBER, phone_verified_at=None)
    APIClient().post(LOGIN_START, {"phone": NUMBER}, format="json")
    assert sms_on == []


def test_free_text_phone_is_not_a_login_identity(sms_on):
    """The contact field must never authenticate anyone."""
    user = make_user("contact-only", role=User.Role.REQUESTER)
    user.phone = NUMBER
    user.save(update_fields=["phone"])
    APIClient().post(LOGIN_START, {"phone": NUMBER}, format="json")
    assert sms_on == []


# --- the happy path --------------------------------------------------------------


def test_verified_number_signs_the_member_in_with_a_member_surface_token(sms_on):
    user = verified_member()
    client = APIClient()
    client.post(LOGIN_START, {"phone": NUMBER}, format="json")
    response = client.post(
        LOGIN_CONFIRM, {"phone": NUMBER, "code": code_from(sms_on)}, format="json"
    )
    assert response.status_code == 200
    assert response.json()["user"]["id"] == user.pk

    from rest_framework_simplejwt.tokens import AccessToken

    # Hardcoded member surface: an SMS code must never mint a staff session.
    assert AccessToken(response.json()["access"])["surface"] == "member"


def test_a_code_is_single_use(sms_on):
    verified_member()
    client = APIClient()
    client.post(LOGIN_START, {"phone": NUMBER}, format="json")
    code = code_from(sms_on)
    assert client.post(LOGIN_CONFIRM, {"phone": NUMBER, "code": code}, format="json").status_code == 200
    assert client.post(LOGIN_CONFIRM, {"phone": NUMBER, "code": code}, format="json").status_code == 400


def test_a_code_issued_for_one_number_does_not_validate_against_another(sms_on):
    verified_member()
    verified_member("other-member", OTHER_NUMBER)
    client = APIClient()
    client.post(LOGIN_START, {"phone": NUMBER}, format="json")
    code = code_from(sms_on)
    # The digest is domain-separated by number, so replaying it elsewhere fails.
    response = client.post(
        LOGIN_CONFIRM, {"phone": OTHER_NUMBER, "code": code}, format="json"
    )
    assert response.status_code == 400


def test_a_link_code_cannot_be_redeemed_at_the_login_endpoint(sms_on):
    user = verified_member()
    client = APIClient()
    client.force_authenticate(user=user)
    client.post(LINK_START, {"phone": OTHER_NUMBER}, format="json")
    code = code_from(sms_on)
    anon = APIClient()
    # Purpose discrimination: an abandoned link code must not sign anyone in.
    assert anon.post(
        LOGIN_CONFIRM, {"phone": OTHER_NUMBER, "code": code}, format="json"
    ).status_code == 400


def test_suspension_between_request_and_confirm_denies_the_session(sms_on):
    user = verified_member()
    client = APIClient()
    client.post(LOGIN_START, {"phone": NUMBER}, format="json")
    code = code_from(sms_on)
    User.objects.filter(pk=user.pk).update(access_status=User.AccessStatus.RESTRICTED)
    assert client.post(
        LOGIN_CONFIRM, {"phone": NUMBER, "code": code}, format="json"
    ).status_code == 400


def test_mistyping_the_code_does_not_consume_the_send_budget(sms_on):
    """Guessing and requesting have separate per-number budgets.

    Sharing one bucket meant three typos locked a member out for an hour while holding
    a valid code. Four wrong guesses must still leave a fresh code obtainable.
    """
    verified_member()
    client = APIClient()
    client.post(LOGIN_START, {"phone": NUMBER}, format="json")
    for _ in range(4):
        assert client.post(
            LOGIN_CONFIRM, {"phone": NUMBER, "code": "000000"}, format="json"
        ).status_code == 400
    assert client.post(LOGIN_START, {"phone": NUMBER}, format="json").status_code == 200
    assert client.post(
        LOGIN_CONFIRM, {"phone": NUMBER, "code": code_from(sms_on)}, format="json"
    ).status_code == 200


def test_attempts_are_capped_per_challenge(sms_on):
    verified_member()
    client = APIClient()
    client.post(LOGIN_START, {"phone": NUMBER}, format="json")
    real_code = code_from(sms_on)
    for _ in range(5):
        client.post(LOGIN_CONFIRM, {"phone": NUMBER, "code": "000000"}, format="json")
    # The challenge is burnt: even the correct code no longer works.
    assert client.post(
        LOGIN_CONFIRM, {"phone": NUMBER, "code": real_code}, format="json"
    ).status_code == 400


# --- linking ---------------------------------------------------------------------


def test_linking_verifies_the_number_and_makes_login_possible(sms_on):
    user = make_user("to-link", role=User.Role.REQUESTER)
    client = APIClient()
    client.force_authenticate(user=user)
    assert client.post(LINK_START, {"phone": NUMBER}, format="json").status_code == 200
    response = client.post(
        LINK_CONFIRM, {"phone": NUMBER, "code": code_from(sms_on)}, format="json"
    )
    assert response.status_code == 200
    user.refresh_from_db()
    assert user.phone_e164 == NUMBER
    assert user.phone_verified_at is not None


def test_linking_normalises_before_storing(sms_on):
    user = make_user("to-link-messy", role=User.Role.REQUESTER)
    client = APIClient()
    client.force_authenticate(user=user)
    client.post(LINK_START, {"phone": "+1 (415) 555-2671"}, format="json")
    client.post(
        LINK_CONFIRM, {"phone": "+1 415-555-2671", "code": code_from(sms_on)}, format="json"
    )
    user.refresh_from_db()
    assert user.phone_e164 == NUMBER


def test_linking_does_not_overwrite_an_existing_contact_number(sms_on):
    user = make_user("keeps-contact", role=User.Role.REQUESTER)
    user.phone = "extension 4021"
    user.save(update_fields=["phone"])
    client = APIClient()
    client.force_authenticate(user=user)
    client.post(LINK_START, {"phone": NUMBER}, format="json")
    client.post(LINK_CONFIRM, {"phone": NUMBER, "code": code_from(sms_on)}, format="json")
    user.refresh_from_db()
    assert user.phone == "extension 4021"  # what staff were told to dial survives
    assert user.phone_e164 == NUMBER


def test_linking_a_number_owned_by_someone_else_reveals_nothing_at_start(sms_on):
    """The link endpoint must not become a membership oracle.

    Answering "that belongs to someone else" here would let any logged-in member probe
    which numbers are on the platform — precisely what the login path refuses to leak.
    The collision is caught at confirm instead, under the row lock.
    """
    verified_member("owner")
    other = make_user("prober", role=User.Role.REQUESTER)
    client = APIClient()
    client.force_authenticate(user=other)

    taken = client.post(LINK_START, {"phone": NUMBER}, format="json")
    free = client.post(LINK_START, {"phone": OTHER_NUMBER}, format="json")
    assert taken.status_code == free.status_code == 200
    assert taken.json() == free.json()


def test_confirming_a_number_owned_by_someone_else_is_refused(sms_on):
    """Where the collision is actually enforced — after the code checks out."""
    owner = verified_member("real-owner")
    other = make_user("prober2", role=User.Role.REQUESTER)
    client = APIClient()
    client.force_authenticate(user=other)
    client.post(LINK_START, {"phone": NUMBER}, format="json")

    response = client.post(
        LINK_CONFIRM, {"phone": NUMBER, "code": code_from(sms_on)}, format="json"
    )
    assert response.status_code == 400
    other.refresh_from_db()
    assert other.phone_e164 == ""
    # The real owner keeps the number.
    owner.refresh_from_db()
    assert owner.phone_e164 == NUMBER


def test_editing_the_number_clears_its_verified_stamp():
    """The model hook, not just the service -- /control/ can edit this field."""
    user = verified_member()
    user.phone_e164 = OTHER_NUMBER
    user.save(update_fields=["phone_e164"])
    user.refresh_from_db()
    assert user.phone_verified_at is None


def test_unlinking_clears_the_identity(sms_on):
    user = verified_member()
    client = APIClient()
    client.force_authenticate(user=user)
    assert client.delete(UNLINK).status_code == 200
    user.refresh_from_db()
    assert user.phone_e164 == ""
    assert user.phone_verified_at is None


def test_two_accounts_cannot_hold_the_same_verified_number():
    from django.db import IntegrityError, transaction

    verified_member("first-owner")
    second = make_user("second-owner", role=User.Role.REQUESTER)
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            second.phone_e164 = NUMBER
            second.save(update_fields=["phone_e164"])


def test_many_accounts_may_have_no_number():
    """The partial constraint must not treat blank as a colliding value."""
    make_user("blank-one", role=User.Role.REQUESTER)
    make_user("blank-two", role=User.Role.REQUESTER)
    assert User.objects.filter(phone_e164="").count() >= 2


def test_challenge_rows_never_store_the_raw_code(sms_on):
    verified_member()
    APIClient().post(LOGIN_START, {"phone": NUMBER}, format="json")
    code = code_from(sms_on)
    row = PhoneVerificationChallenge.objects.get(purpose=PhoneChallengePurpose.LOGIN)
    assert code not in row.code_digest
    assert len(row.code_digest) == 64
