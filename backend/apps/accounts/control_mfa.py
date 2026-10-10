"""Django admin's session bridge: password session has no control authority until MFA."""

from django.contrib.auth.decorators import login_required
from django.http import HttpResponseForbidden
from django.shortcuts import redirect, render
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_protect
from rest_framework.exceptions import APIException
from rest_framework.throttling import SimpleRateThrottle

from apps.accounts import mfa_challenges, mfa_policy
from apps.accounts.audit_events import fingerprint
from apps.accounts.mfa_sessions import context


class ControlMFAThrottle(SimpleRateThrottle):
    scope = "mfa_verify"

    def get_cache_key(self, request, view):
        return self.cache_format % {"scope": self.scope, "ident": fingerprint(
            f"control:{self.get_ident(request)}:{request.user.pk}")}


def session_verified(request):
    try:
        mfa_policy.assert_verified(request.user, {"mfa_version": request.session.get("mfa_version")})
        return True
    except APIException:
        return False


@login_required(login_url="/control/login/")
@csrf_protect
@never_cache
def control_mfa(request):
    user = request.user
    if (not user.is_superuser or not user.is_active or user.access_status != "active"
            or user.is_tenant_dump_stub or user.must_change_password):
        return HttpResponseForbidden()
    if session_verified(request):
        return redirect("/control/")
    if not ControlMFAThrottle().allow_request(request, None):
        return render(request, "accounts/control_mfa.html", {"error": "Too many attempts. Try again later."}, status=429)
    challenge = request.session.get("mfa_challenge")
    if not challenge:
        challenge = mfa_challenges.start(user, context=context(request, surface="control"))["challenge"]
        request.session["mfa_challenge"] = challenge
    row = mfa_policy.credential(user)
    enrolling = not bool(row and row.enabled_at)
    data = {"enrolling": enrolling}
    try:
        if request.method == "POST":
            code = str(request.POST.get("code", ""))[:64]
            result = mfa_challenges.finish(challenge, code, request, enrolling=enrolling)
            request.session.cycle_key()
            request.session["mfa_version"] = result["mfa_version"]
            request.session.pop("mfa_challenge", None)
            if result.get("recovery_codes"):
                return render(request, "accounts/control_mfa.html", {"recovery_codes": result["recovery_codes"]})
            return redirect("/control/")
        if enrolling:
            data.update(mfa_challenges.enroll(challenge, request))
    except APIException:
        # Restart requires a fresh password login; do not endlessly reset the attempt cap.
        data["error"] = "Verification failed. If this challenge expired, sign out and sign in again."
    return render(request, "accounts/control_mfa.html", data)
