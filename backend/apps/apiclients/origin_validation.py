"""Canonical exact Origin-header values shared by every API-client grant path."""

from urllib.parse import urlsplit


def validate_exact_origins(values):
    if not isinstance(values, (list, tuple)) or not values:
        raise ValueError("At least one allowed origin is required.")
    canonical = []
    seen = set()
    for value in values:
        if (
            not isinstance(value, str)
            or value != value.strip()
            or any(ord(character) < 33 for character in value)
        ):
            raise ValueError("Origins must be exact http(s) URLs.")
        parts = urlsplit(value)
        if (
            parts.scheme not in {"http", "https"}
            or not parts.hostname
            or parts.username is not None
            or parts.password is not None
            or parts.path != ""
            or parts.query
            or parts.fragment
            or "\\" in parts.netloc
            or parts.netloc.endswith(":")
        ):
            raise ValueError(
                "Origins must be bare scheme://host[:port] values without credentials or paths."
            )
        try:
            port = parts.port
        except ValueError as exc:
            raise ValueError("Origin port is invalid.") from exc
        host = parts.hostname.lower()
        if "*" in host or any(character.isspace() for character in host):
            raise ValueError("Origin host must be exact and cannot contain a wildcard.")
        if ":" in host and not host.startswith("["):
            host = f"[{host}]"
        default_port = (parts.scheme == "http" and port == 80) or (
            parts.scheme == "https" and port == 443
        )
        origin = f"{parts.scheme}://{host}"
        if port is not None and not default_port:
            origin += f":{port}"
        if origin not in seen:
            canonical.append(origin)
            seen.add(origin)
    return canonical
