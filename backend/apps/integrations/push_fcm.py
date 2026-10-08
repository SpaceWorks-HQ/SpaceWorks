import json
import time

import jwt
import requests


class PushProviderError(Exception):
    def __init__(self, message, *, invalid_token=False):
        super().__init__(message)
        self.invalid_token = invalid_token


def send_fcm(settings_row, token, title, body, data):
    try:
        account = json.loads(settings_row.get_fcm_service_account())
        required = {key: account.get(key) for key in (
            "client_email", "private_key", "token_uri", "project_id"
        )}
        if not all(required.values()) or not str(required["token_uri"]).startswith("https://"):
            raise ValueError
        now = int(time.time())
        # Inside the try: a service account whose private_key is not a usable RSA key is a
        # configuration error, not an unclassified exception out of the sender.
        assertion = jwt.encode({
            "iss": required["client_email"],
            "scope": "https://www.googleapis.com/auth/firebase.messaging",
            "aud": required["token_uri"], "iat": now, "exp": now + 300,
        }, required["private_key"], algorithm="RS256")
    except (ValueError, TypeError, jwt.PyJWTError) as exc:
        raise PushProviderError("FCM configuration is unavailable.") from exc
    try:
        oauth = requests.post(required["token_uri"], data={
            "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
            "assertion": assertion,
        }, timeout=10)
        access_token = oauth.json().get("access_token") if oauth.status_code == 200 else None
        if not access_token:
            raise PushProviderError("FCM authorization failed.")
        response = requests.post(
            f"https://fcm.googleapis.com/v1/projects/{required['project_id']}/messages:send",
            headers={"Authorization": f"Bearer {access_token}"},
            json={"message": {"token": token, "notification": {
                "title": title, "body": body,
            }, "data": data}}, timeout=10,
        )
    except requests.RequestException as exc:
        raise PushProviderError("FCM request failed.") from exc
    if response.status_code == 200:
        return
    try:
        error = response.json().get("error", {})
        detail_text = json.dumps(error.get("details", []))
        invalid = error.get("status") == "NOT_FOUND" or "UNREGISTERED" in detail_text
    except ValueError:
        invalid = False
    raise PushProviderError("FCM delivery failed.", invalid_token=invalid)
