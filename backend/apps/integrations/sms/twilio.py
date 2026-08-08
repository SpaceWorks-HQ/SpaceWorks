"""Twilio SMS provider -- the one shipped implementation of the SmsProvider seam.

Uses stdlib urllib to match apps/integrations/webhooks.py; the codebase has no
`requests` dependency and this adds none.
"""

import base64
import json
import logging
from urllib import error as urllib_error
from urllib import parse as urllib_parse
from urllib import request as urllib_request

logger = logging.getLogger(__name__)

API_ROOT = "https://api.twilio.com/2010-04-01"
TIMEOUT_SECONDS = 10


class TwilioSmsProvider:
    key = "twilio"

    def __init__(self, settings_row):
        self._row = settings_row

    def is_configured(self) -> bool:
        row = self._row
        if row is None:
            return False
        # get_auth_token() DECRYPTS. A rotated/missing API_CLIENT_ENC_KEY or corrupt
        # ciphertext raises here; treat an unreadable credential as not-configured so
        # phone login disappears from the config payload rather than 500ing the login
        # screen. Same swallow as dispatch_channels._channel_configured.
        try:
            token = row.get_auth_token()
        except Exception:
            logger.warning("sms_credentials_unreadable", extra={"provider": self.key})
            return False
        return bool(row.account_sid and token and row.from_number)

    def send(self, *, to: str, body: str) -> bool:
        if not self.is_configured():
            return False
        row = self._row
        url = f"{API_ROOT}/Accounts/{urllib_parse.quote(row.account_sid)}/Messages.json"
        payload = urllib_parse.urlencode(
            {"To": to, "From": row.from_number, "Body": body}
        ).encode("utf-8")
        credentials = base64.b64encode(
            f"{row.account_sid}:{row.get_auth_token()}".encode("utf-8")
        ).decode("ascii")
        req = urllib_request.Request(
            url,
            data=payload,
            headers={
                "Authorization": f"Basic {credentials}",
                "Content-Type": "application/x-www-form-urlencoded",
            },
            method="POST",
        )
        try:
            with urllib_request.urlopen(req, timeout=TIMEOUT_SECONDS) as response:
                return response.status < 400
        except urllib_error.HTTPError as exc:
            # Log the status but never the body: Twilio echoes the destination number
            # back in its error payload, and that is PII in a log line.
            logger.warning(
                "sms_send_rejected",
                extra={"provider": self.key, "status": exc.code},
            )
            return False
        except Exception:
            logger.warning("sms_send_failed", extra={"provider": self.key})
            return False
