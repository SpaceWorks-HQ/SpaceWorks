"""Per-makerspace integration secrets: the encrypt-on-set, decrypt-on-get pair.

Split out of `models_makerspace.py` so that file stays under the ~300-line ceiling
before new fields land on `Makerspace`. These ten methods are one repeated shape over
five columns and carry no field definitions, so moving them changes no schema and
needs no migration.

They stay a mixin rather than module-level helpers because every one of them reads and
writes an attribute of the row it is called on; `makerspace.get_smtp_password()` is the
call site everywhere, and a free function would have to be handed the instance anyway.
"""

from apps.makerspaces.secrets import decrypt_value, encrypt_value


class MakerspaceSecretsMixin:
    """Encrypted accessors for the outbound-integration credentials.

    The columns hold ciphertext; nothing outside these methods should read them
    directly, which is what keeps `API_CLIENT_ENC_KEY` the single decryption door.
    """

    def set_telegram_bot_token(self, raw):
        self.telegram_bot_token = encrypt_value(raw)

    def get_telegram_bot_token(self):
        return decrypt_value(self.telegram_bot_token)

    def set_smtp_password(self, raw):
        self.smtp_password = encrypt_value(raw)

    def get_smtp_password(self):
        return decrypt_value(self.smtp_password)

    def set_slack_webhook_url(self, raw):
        self.slack_webhook_url = encrypt_value(raw)

    def get_slack_webhook_url(self):
        return decrypt_value(self.slack_webhook_url)

    def set_mattermost_webhook_url(self, raw):
        self.mattermost_webhook_url = encrypt_value(raw)

    def get_mattermost_webhook_url(self):
        return decrypt_value(self.mattermost_webhook_url)

    def set_discord_webhook_url(self, raw):
        self.discord_webhook_url = encrypt_value(raw)

    def get_discord_webhook_url(self):
        return decrypt_value(self.discord_webhook_url)
