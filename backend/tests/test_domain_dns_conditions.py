"""Custom-domain verification under real DNS failure shapes (cloud lane).

Existing tests replace `_resolve_txt` and `resolves_to_origin` wholesale with lambdas. These
drive the real resolver code with only `dns.resolver.Resolver` replaced, so the timeout,
NXDOMAIN, NoAnswer, non-UTF-8 and CNAME/A-record branches actually run. Verification must
only ever answer VERIFIED or FAILED -- never raise into the staff request.
"""

import dns.exception
import dns.resolver
import pytest
from django.test import override_settings

from apps.makerspaces import domain_verification
from apps.makerspaces.models import Makerspace
from tests.return_helpers import make_space

pytestmark = pytest.mark.django_db

MANAGED = {"PLATFORM_DOMAIN_SUFFIX": ".space-works.tech"}


class _Txt:
    def __init__(self, *parts):
        self.strings = parts


class _Target:
    def __init__(self, target):
        self.target = target


class _Address:
    def __init__(self, ip):
        self.ip = ip

    def __str__(self):
        return self.ip


def _resolver(monkeypatch, answers):
    """`answers[(name, rdtype)]` is a list of rdata or an exception instance to raise."""

    class FakeResolver:
        timeout = lifetime = None

        def resolve(self, name, rdtype):
            result = answers.get((str(name), rdtype), dns.resolver.NXDOMAIN())
            if isinstance(result, BaseException):
                raise result
            return result

    monkeypatch.setattr(domain_verification.dns.resolver, "Resolver", FakeResolver)


def _space(slug, domain="tools.example.org"):
    space = make_space(slug)
    space.frontend_domain = domain
    space.save(update_fields=["frontend_domain"])
    space.refresh_from_db()
    return space


@override_settings(**MANAGED)
def test_a_timeout_on_every_label_fails_with_a_dns_detail(monkeypatch):
    space = _space("dns-timeout")
    _resolver(monkeypatch, {
        ("_spaceworks-verify.tools.example.org", "TXT"): dns.exception.Timeout(),
        ("_osmm-verify.tools.example.org", "TXT"): dns.exception.Timeout(),
    })

    status, _, detail = domain_verification.verify_domain(space)

    assert status == Makerspace.DomainStatus.FAILED
    assert detail.startswith("DNS lookup failed")


@override_settings(**MANAGED)
def test_one_label_erroring_while_the_other_holds_the_token_still_verifies(monkeypatch):
    space = _space("dns-mixed")
    token = space.domain_verification_token.encode()
    _resolver(monkeypatch, {
        ("_spaceworks-verify.tools.example.org", "TXT"): [_Txt(token)],
        ("_osmm-verify.tools.example.org", "TXT"): dns.exception.Timeout(),
    })

    status, _, _ = domain_verification.verify_domain(space)

    assert status == Makerspace.DomainStatus.VERIFIED


@override_settings(**MANAGED)
def test_a_split_txt_record_is_joined_before_comparison(monkeypatch):
    space = _space("dns-split")
    token = space.domain_verification_token.encode()
    _resolver(monkeypatch, {
        ("_spaceworks-verify.tools.example.org", "TXT"): [_Txt(token[:5], token[5:])],
    })

    status, _, _ = domain_verification.verify_domain(space)

    assert status == Makerspace.DomainStatus.VERIFIED


@override_settings(**MANAGED)
def test_a_non_utf8_txt_answer_fails_cleanly(monkeypatch):
    space = _space("dns-binary")
    _resolver(monkeypatch, {
        ("_spaceworks-verify.tools.example.org", "TXT"): [_Txt(b"\xff\xfe\xfd")],
        ("_osmm-verify.tools.example.org", "TXT"): dns.resolver.NoAnswer(),
    })

    status, _, _ = domain_verification.verify_domain(space)

    assert status == Makerspace.DomainStatus.FAILED


@override_settings(**MANAGED, PLATFORM_ORIGIN_HOST="origin.space-works.tech")
def test_resolves_to_origin_accepts_a_cname_to_the_origin(monkeypatch):
    space = _space("dns-cname")
    _resolver(monkeypatch, {
        ("tools.example.org", "CNAME"): [_Target("origin.space-works.tech.")],
    })

    assert domain_verification.resolves_to_origin(space) is True


@override_settings(**MANAGED, PLATFORM_ORIGIN_HOST="origin.space-works.tech")
def test_resolves_to_origin_accepts_a_shared_a_record(monkeypatch):
    space = _space("dns-a-overlap")
    _resolver(monkeypatch, {
        ("tools.example.org", "CNAME"): dns.resolver.NoAnswer(),
        ("tools.example.org", "A"): [_Address("203.0.113.7")],
        ("origin.space-works.tech", "A"): [_Address("203.0.113.7"), _Address("203.0.113.8")],
    })

    assert domain_verification.resolves_to_origin(space) is True


@override_settings(**MANAGED, PLATFORM_ORIGIN_HOST="origin.space-works.tech")
def test_resolves_to_origin_rejects_a_domain_pointing_elsewhere(monkeypatch):
    space = _space("dns-elsewhere")
    _resolver(monkeypatch, {
        ("tools.example.org", "CNAME"): dns.resolver.NoAnswer(),
        ("tools.example.org", "A"): [_Address("198.51.100.1")],
        ("origin.space-works.tech", "A"): [_Address("203.0.113.7")],
    })

    assert domain_verification.resolves_to_origin(space) is False


@pytest.mark.parametrize(
    "error", [dns.exception.Timeout(), dns.resolver.NXDOMAIN(), dns.resolver.NoNameservers()],
    ids=["timeout", "nxdomain", "no-nameservers"],
)
@override_settings(**MANAGED, PLATFORM_ORIGIN_HOST="origin.space-works.tech")
def test_resolves_to_origin_is_false_on_any_resolver_failure(monkeypatch, error):
    space = _space(f"dns-origin-{type(error).__name__.lower()}")
    _resolver(monkeypatch, {("tools.example.org", "CNAME"): error})

    assert domain_verification.resolves_to_origin(space) is False


@override_settings(**MANAGED, PLATFORM_ORIGIN_HOST="origin.space-works.tech")
def test_a_matching_txt_with_the_domain_pointing_elsewhere_fails(monkeypatch):
    space = _space("dns-txt-but-elsewhere")
    token = space.domain_verification_token.encode()
    _resolver(monkeypatch, {
        ("_spaceworks-verify.tools.example.org", "TXT"): [_Txt(token)],
        ("tools.example.org", "CNAME"): dns.resolver.NoAnswer(),
        ("tools.example.org", "A"): [_Address("198.51.100.1")],
        ("origin.space-works.tech", "A"): [_Address("203.0.113.7")],
    })

    status, _, _ = domain_verification.verify_domain(space)

    assert status == Makerspace.DomainStatus.FAILED
