"""Read-only tar and JSON policy checks for deployment import preflight."""

import hashlib
import hmac
import json
from pathlib import Path, PurePosixPath
import re
import tarfile

from apps.backup.import_preflight import ImportPreflightError


_DIGEST = re.compile(r"[0-9a-f]{64}")


def validate_bundle(bundle_path, manifest, manifest_file, secrets_file):
    try:
        with tarfile.open(bundle_path, mode="r:*") as archive:
            members = _regular_members(archive)
            _require_member_json(
                archive, members, "manifest.json", manifest_file, "manifest"
            )
            _require_member_json(
                archive, members, "keys/env.json", secrets_file, "continuity-secret"
            )
            components = _component_facts(manifest)
            component_paths = {item[0] for item in components}
            allowed = {"manifest.json", "keys/env.json", *component_paths}
            for name in members:
                if name not in allowed and not _is_main_object_member(name):
                    raise ImportPreflightError(
                        "undeclared_member",
                        "the outer bundle contains an undeclared member.",
                    )
            _validate_main_member_counts(manifest, members)
            _verify_components(archive, members, components)
    except ImportPreflightError:
        raise
    except (OSError, tarfile.TarError) as exc:
        raise ImportPreflightError(
            "component_policy", "the decrypted outer bundle is unreadable."
        ) from exc


def _verify_components(archive, members, components):
    for path, expected_size, expected_digest in components:
        member = members.get(path)
        if member is None:
            raise ImportPreflightError(
                "missing_component", f"declared component {path} is absent."
            )
        actual_digest = _member_sha256(archive, member)
        if member.size != expected_size or not hmac.compare_digest(
            actual_digest, expected_digest
        ):
            raise ImportPreflightError(
                "component_digest",
                f"declared component {path} does not match its digest.",
            )


def _validate_main_member_counts(manifest, members):
    main_id = manifest["main_component"]["component_id"]
    object_count = sum(_is_main_object_member(name) for name in members)
    expected_object_count = next(
        item["count"]
        for item in manifest["object_ledgers"]
        if item["component_id"] == main_id
    )
    expected_content_count = next(
        item["count"]
        for item in manifest["content_ledgers"]
        if item["component_id"] == main_id
    )
    # build_content_ledger runs before manifest.json is written. The readable
    # main therefore contains database.dump, keys/env.json, and its object files.
    if (
        object_count != expected_object_count
        or expected_content_count != object_count + 2
    ):
        raise ImportPreflightError(
            "component_policy",
            "the readable-main member counts differ from the signed ledgers.",
        )


def _regular_members(archive):
    members = {}
    for member in archive.getmembers():
        try:
            name = _member_name(member.name)
        except ValueError as exc:
            raise ImportPreflightError(
                "undeclared_member", "the outer bundle contains an unsafe member."
            ) from exc
        if member.isdir():
            if not _is_allowed_directory(name):
                raise ImportPreflightError(
                    "undeclared_member",
                    "the outer bundle contains an undeclared directory.",
                )
            continue
        if not member.isfile() or name in members:
            raise ImportPreflightError(
                "undeclared_member",
                "the outer bundle contains an unsafe or duplicate member.",
            )
        members[name] = member
    return members


def _component_facts(manifest):
    try:
        main = manifest["main_component"]
        if main["path"] != "database.dump":
            raise ValueError
        declared = [
            _component_fact(
                main["path"], main["size_bytes"], main["ciphertext_sha256"]
            )
        ]
        slices = manifest["slice_components"]
        for item in slices:
            if item["ciphertext_path"] != (
                f"slices/{item['component_id']}.tar.age"
            ):
                raise ValueError
            declared.append(
                _component_fact(
                    item["ciphertext_path"],
                    item["size_bytes"],
                    item["ciphertext_sha256"],
                )
            )
        if len({item[0] for item in declared}) != len(declared):
            raise ValueError
        mirrored = [
            _component_fact(item["path"], item["size"], item["sha256"])
            for item in manifest["contents"]
        ]
        if mirrored != declared:
            raise ValueError
        for ledger_name in ("object_ledgers", "content_ledgers"):
            if any(
                type(item.get("count")) is not int or item["count"] < 0
                for item in manifest[ledger_name]
            ):
                raise ValueError
        _validate_compatibility_slices(slices, manifest["slices"])
        return declared
    except (KeyError, TypeError, ValueError) as exc:
        raise ImportPreflightError(
            "component_policy",
            "the signed component declarations are invalid or inconsistent.",
        ) from exc


def _validate_compatibility_slices(primary, compatibility):
    if not isinstance(compatibility, list) or len(compatibility) != len(primary):
        raise ValueError
    for source, mirror in zip(primary, compatibility, strict=True):
        if not isinstance(mirror, dict) or (
            mirror.get("slice_id") != source["component_id"]
            or mirror.get("component_id") != source["component_id"]
            or mirror.get("makerspace_id") != source["makerspace_id"]
            or mirror.get("path") != source["ciphertext_path"]
            or mirror.get("size_bytes") != source["size_bytes"]
            or mirror.get("ciphertext_sha256") != source["ciphertext_sha256"]
            or mirror.get("recipient_fingerprints")
            != source["recipient_fingerprints"]
        ):
            raise ValueError


def _component_fact(path, size, digest):
    normalized = _member_name(path)
    if type(size) is not int or size <= 0:
        raise ValueError
    if not isinstance(digest, str) or _DIGEST.fullmatch(digest) is None:
        raise ValueError
    return normalized, size, digest


def _member_name(value):
    if not isinstance(value, str):
        raise ValueError
    stripped = value[2:] if value.startswith("./") else value
    path = PurePosixPath(stripped)
    if (
        not stripped
        or path.is_absolute()
        or ".." in path.parts
        or path.as_posix() != stripped
    ):
        raise ValueError
    return stripped


def _is_main_object_member(name):
    return name.startswith("objects/private/") or name.startswith(
        "objects/public_image/"
    )


def _is_allowed_directory(name):
    return name in {".", "keys", "objects", "slices"} or (
        name == "objects/private"
        or name.startswith("objects/private/")
        or name == "objects/public_image"
        or name.startswith("objects/public_image/")
    )


def _require_member_json(archive, members, name, external_path, label):
    member = members.get(name)
    if member is None:
        raise ImportPreflightError(
            "missing_component", f"required member {name} is absent."
        )
    embedded = _read_member_json(archive, member, label)
    external = read_json_file(external_path, label)
    if embedded != external:
        raise ImportPreflightError(
            "component_policy",
            f"the extracted {label} file differs from the outer bundle.",
        )


def _read_member_json(archive, member, label):
    source = archive.extractfile(member)
    if source is None:
        raise ImportPreflightError(
            "component_policy", f"the {label} member is unreadable."
        )
    try:
        return _decode_json(source.read(), label)
    except OSError as exc:
        raise ImportPreflightError(
            "component_policy", f"the {label} member is unreadable."
        ) from exc


def read_json_file(path, label):
    try:
        return _decode_json(Path(path).read_bytes(), label)
    except OSError as exc:
        raise ImportPreflightError(
            "component_policy", f"the extracted {label} file is unreadable."
        ) from exc


def _decode_json(raw, label):
    def unique_object(pairs):
        value = {}
        for key, item in pairs:
            if key in value:
                raise ValueError
            value[key] = item
        return value

    try:
        return json.loads(raw.decode("utf-8"), object_pairs_hook=unique_object)
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise ImportPreflightError(
            "component_policy", f"the {label} JSON is invalid."
        ) from exc


def _member_sha256(archive, member):
    source = archive.extractfile(member)
    if source is None:
        raise ImportPreflightError(
            "component_policy", "a declared component is unreadable."
        )
    digest = hashlib.sha256()
    while chunk := source.read(1024 * 1024):
        digest.update(chunk)
    return digest.hexdigest()
