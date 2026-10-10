import json
import time

import jwt
import requests
from cryptography.fernet import InvalidToken


class PushProviderError(Exception):
    def __init__(self, message, *, invalid_token=False):
        super().__init__(message)
        self.invalid_token = invalid_token


def send_fcm(settings_row, token, title, body, data):
    try:
        account = json.loads(settings_row.get_fcm_service_account())
        if not isinstance(account, dict):
            raise ValueError
        required = {key: account.get(key) for key in (
            "client_email", "private_key", "token_uri", "project_id"
        )}
        if not all(isinstance(value, str) and value.strip() for value in required.values()) or not required["token_uri"].startswith("https://"):
            raise ValueError
        now = int(time.time())
        # Inside the try: a service account whose private_key is not a usable RSA key is a
        # configuration error, not an unclassified exception out of the sender.
        assertion = jwt.encode({
            "iss": required["client_email"],
            "scope": "https://www.googleapis.com/auth/firebase.messaging",
            "aud": required["token_uri"], "iat": now, "exp": now + 300,
        }, required["private_key"], algorithm="RS256")
    except (InvalidToken, ValueError, TypeError, jwt.PyJWTError) as exc:
        raise PushProviderError("FCM configuration is unavailable.") from exc
    try:
        oauth = requests.post(required["token_uri"], data={
            "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
            "assertion": assertion,
        }, timeout=10)
        payload = oauth.json() if oauth.status_code == 200 else {}
        access_token = payload.get("access_token") if isinstance(payload, dict) else None
        if not isinstance(access_token, str) or not access_token.strip():
            raise PushProviderError("FCM authorization failed.")
        response = requests.post(
            f"https://fcm.googleapis.com/v1/projects/{required['project_id']}/messages:send",
            headers={"Authorization": f"Bearer {access_token}"},
            json={"message": {"token": token, "notification": {
                "title": title, "body": body,
            }, "data": data}}, timeout=10,
        )
    except (requests.RequestException, ValueError, TypeError) as exc:
        raise PushProviderError("FCM request failed.") from exc
    if response.status_code == 200:
        return
    try:
        payload = response.json()
        error = payload.get("error", {}) if isinstance(payload, dict) else {}
        if not isinstance(error, dict):
            error = {}
        details = error.get("details", [])
        invalid = error.get("status") == "NOT_FOUND" or (
            isinstance(details, list) and any(
                isinstance(detail, dict) and detail.get("errorCode") == "UNREGISTERED"
                for detail in details
            )
        )
    except (ValueError, TypeError):
        invalid = False
    raise PushProviderError("FCM delivery failed.", invalid_token=invalid)
