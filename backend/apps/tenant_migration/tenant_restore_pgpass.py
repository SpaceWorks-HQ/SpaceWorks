"""Credential-minimal pg_restore process inputs."""

from contextlib import contextmanager
import os
from pathlib import Path
import tempfile
from urllib.parse import parse_qsl, unquote, urlsplit

from .tenant_restore_types import TenantRestoreRefused


_SAFE_PARENT_ENV = frozenset({
    "LANG", "LC_ALL", "LC_CTYPE", "PATH", "SSL_CERT_DIR", "SSL_CERT_FILE", "TZ",
})
_SAFE_QUERY_ENV = {
    "channel_binding": "PGCHANNELBINDING",
    "connect_timeout": "PGCONNECT_TIMEOUT",
    "gssencmode": "PGGSSENCMODE",
    "sslcert": "PGSSLCERT",
    "sslcrl": "PGSSLCRL",
    "sslcrldir": "PGSSLCRLDIR",
    "sslkey": "PGSSLKEY",
    "sslmode": "PGSSLMODE",
    "sslrootcert": "PGSSLROOTCERT",
    "target_session_attrs": "PGTARGETSESSIONATTRS",
}


def _escape_pgpass(value):
    if not isinstance(value, str) or any(character in value for character in "\x00\r\n"):
        raise TenantRestoreRefused("PostgreSQL restore credentials are invalid.")
    return value.replace("\\", "\\\\").replace(":", "\\:")


@contextmanager
def pg_restore_process_inputs(database_url):
    try:
        parsed = urlsplit(database_url)
        port_number = parsed.port
        query = parse_qsl(parsed.query, keep_blank_values=True, strict_parsing=True)
    except (TypeError, ValueError) as exc:
        raise TenantRestoreRefused("PostgreSQL restore URL is invalid.") from exc
    username = unquote(parsed.username or "")
    password = unquote(parsed.password or "")
    database = unquote(parsed.path.lstrip("/"))
    host = parsed.hostname or ""
    port = str(port_number or 5432)
    values = (host, port, database, username, password)
    query_names = [name for name, _value in query]
    if (
        parsed.scheme not in {"postgres", "postgresql"}
        or (port_number is not None and not 0 < port_number < 65536)
        or not all(values)
        or len(query_names) != len(set(query_names))
        or any(name not in _SAFE_QUERY_ENV for name in query_names)
        or any(any(character in value for character in "\x00\r\n") for _name, value in query)
    ):
        raise TenantRestoreRefused("PostgreSQL restore URL is incomplete.")
    with tempfile.TemporaryDirectory(prefix="spaceworks-pgpass-") as directory:
        password_path = Path(directory, "pgpass")
        fd = os.open(password_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(":".join(_escape_pgpass(value) for value in values) + "\n")
        environment = {
            key: value for key, value in os.environ.items() if key in _SAFE_PARENT_ENV
        }
        environment.update({
            "PGHOST": host,
            "PGPORT": port,
            "PGDATABASE": database,
            "PGUSER": username,
            "PGPASSFILE": str(password_path),
            **{_SAFE_QUERY_ENV[name]: value for name, value in query},
        })
        yield environment
