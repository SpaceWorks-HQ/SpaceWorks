import json
import logging

import jwt
import requests
import urllib3
from django.conf import settings
from django.core.cache import cache

logger = logging.getLogger(__name__)


class SocialTokenError(Exception):
    pass


class SocialProviderUnavailable(Exception):
    pass


def decode_rs256_token(raw_token, *, provider, jwks_url, issuer, audience):
    try:
        header = jwt.get_unverified_header(raw_token)
    except jwt.PyJWTError as exc:
        raise SocialTokenError("Invalid social identity token.") from exc
    if header.get("alg") != "RS256" or not header.get("kid"):
        raise SocialTokenError("Invalid social identity token.")
    last_error = None
    for refresh in (False, True):
        key = _key_for_kid(provider, jwks_url, header["kid"], refresh=refresh)
        if key is None:
            continue
        try:
            return jwt.decode(
                raw_token,
                key=key,
                algorithms=["RS256"],
                audience=audience,
                issuer=issuer,
                leeway=settings.SOCIAL_AUTH_CLOCK_SKEW_SECONDS,
                options={"require": ["exp", "iat", "iss", "aud", "sub"]},
            )
        except jwt.InvalidSignatureError as exc:
            last_error = exc
            continue
        except jwt.PyJWTError as exc:
            raise SocialTokenError("Invalid social identity token.") from exc
    raise SocialTokenError("Invalid social identity token.") from last_error


def _key_for_kid(provider, url, kid, *, refresh):
    jwks = _fetch_jwks(provider, url, refresh=refresh)
    for item in jwks:
        if item.get("kid") == kid and item.get("kty") == "RSA":
            try:
                return jwt.algorithms.RSAAlgorithm.from_jwk(json.dumps(item))
            except (ValueError, TypeError, jwt.PyJWTError) as exc:
                raise SocialTokenError("Invalid provider signing key.") from exc
    return None


def _fetch_jwks(provider, url, *, refresh):
    cache_key = f"social-jwks:{provider}"
    response = None
    try:
        if not refresh:
            try:
                cached = cache.get(cache_key)
            except Exception:
                logger.warning("social_jwks_cache_read_failed")
                cached = None
            if isinstance(cached, list) and all(isinstance(key, dict) for key in cached):
                return cached
        response = requests.get(
            url,
            timeout=settings.SOCIAL_AUTH_JWKS_TIMEOUT_SECONDS,
            stream=True,
            allow_redirects=False,
        )
        if response.status_code != 200:
            raise SocialProviderUnavailable("Identity provider is unavailable.")
        length = int(response.headers.get("Content-Length") or 0)
        if length > settings.SOCIAL_AUTH_JWKS_MAX_BYTES:
            raise SocialProviderUnavailable("Identity provider is unavailable.")
        body = response.raw.read(settings.SOCIAL_AUTH_JWKS_MAX_BYTES + 1)
        if len(body) > settings.SOCIAL_AUTH_JWKS_MAX_BYTES:
            raise SocialProviderUnavailable("Identity provider is unavailable.")
        data = json.loads(body)
        # A JSON array or scalar body used to reach `.get` and escape as AttributeError
        # (a 500) instead of "provider unavailable" (a 503).
        if not isinstance(data, dict):
            raise ValueError
        keys = data.get("keys")
        if not isinstance(keys, list) or len(keys) > 16 or not all(isinstance(key, dict) for key in keys):
            raise ValueError
        try:
            cache.set(cache_key, keys, settings.SOCIAL_AUTH_JWKS_CACHE_SECONDS)
        except Exception:
            logger.warning("social_jwks_cache_write_failed")
    except (
        requests.RequestException,
        # `response.raw.read` is urllib3, below requests' exception wrapping: a read
        # timeout or truncated body mid-stream raises urllib3's own errors (or OSError).
        urllib3.exceptions.HTTPError,
        OSError,
        ValueError,
        TypeError,
    ) as exc:
        raise SocialProviderUnavailable("Identity provider is unavailable.") from exc
    finally:
        if response is not None and hasattr(response, "close"):
            try:
                response.close()
            except Exception:
                logger.warning("social_jwks_response_close_failed")
    return keys
