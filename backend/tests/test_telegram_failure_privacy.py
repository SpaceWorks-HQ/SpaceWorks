"""The transport's own log must not expose the bot token before caller redaction."""

import logging
from types import SimpleNamespace
from urllib.error import URLError

import pytest

from apps.integrations import telegram


@pytest.mark.parametrize("error", [
    URLError("https://api.telegram.org/botprivate-token/sendMessage refused"),
    ValueError("private-token malformed status"),
])
def test_direct_telegram_failure_logs_only_the_exception_class(monkeypatch, caplog, error):
    space = SimpleNamespace(pk=1, telegram_bot_token="private-token", telegram_group_chat_id="-123")

    def urlopen(*args, **kwargs):
        raise error

    monkeypatch.setattr(telegram.urllib_request, "urlopen", urlopen)
    with caplog.at_level(logging.DEBUG), pytest.raises(telegram.TelegramDeliveryError):
        telegram.send_message(space, "message")
    assert "private-token" not in caplog.text
    assert any(getattr(record, "error_class", None) == type(error).__name__ for record in caplog.records)
