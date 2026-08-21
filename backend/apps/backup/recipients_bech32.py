"""Minimal Bech32 primitives for native age X25519 recipients."""

_ALPHABET = "qpzry9x8gf2tvdw0s3jn54khce6mua7l"
_VALUES = {character: index for index, character in enumerate(_ALPHABET)}
_BECH32_CONST = 1
_BECH32M_CONST = 0x2BC830A3


class Bech32DecodeError(ValueError):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


def decode(value):
    separator = value.rfind("1")
    if (
        not 8 <= len(value) <= 90
        or any(ord(character) < 33 or ord(character) > 126 for character in value)
        or separator < 1
        or separator + 7 > len(value)
    ):
        raise Bech32DecodeError("invalid_bech32")

    hrp = value[:separator]
    try:
        combined = [_VALUES[character] for character in value[separator + 1 :]]
    except KeyError as exc:
        raise Bech32DecodeError("invalid_bech32") from exc

    checksum = _polymod(_expand_hrp(hrp) + combined)
    if checksum == _BECH32M_CONST:
        raise Bech32DecodeError("bech32m_checksum")
    if checksum != _BECH32_CONST:
        raise Bech32DecodeError("invalid_checksum")
    return hrp, combined[:-6]


def encode(hrp, payload):
    values = _expand_hrp(hrp) + payload + [0] * 6
    polymod = _polymod(values) ^ _BECH32_CONST
    checksum = [(polymod >> 5 * (5 - index)) & 31 for index in range(6)]
    return hrp + "1" + "".join(_ALPHABET[value] for value in payload + checksum)


def convert_bits(values, from_bits, to_bits, *, pad):
    accumulator = 0
    bit_count = 0
    converted = []
    maximum = (1 << to_bits) - 1
    for value in values:
        if value < 0 or value >> from_bits:
            return None
        accumulator = accumulator << from_bits | value
        bit_count += from_bits
        while bit_count >= to_bits:
            bit_count -= to_bits
            converted.append(accumulator >> bit_count & maximum)
    if pad:
        if bit_count:
            converted.append(accumulator << (to_bits - bit_count) & maximum)
    elif bit_count >= from_bits or accumulator << (to_bits - bit_count) & maximum:
        return None
    return converted


def _expand_hrp(hrp):
    return [ord(character) >> 5 for character in hrp] + [0] + [
        ord(character) & 31 for character in hrp
    ]


def _polymod(values):
    generators = (0x3B6A57B2, 0x26508E6D, 0x1EA119FA, 0x3D4233DD, 0x2A1462B3)
    checksum = 1
    for value in values:
        top = checksum >> 25
        checksum = (checksum & 0x1FFFFFF) << 5 ^ value
        for index, generator in enumerate(generators):
            if top >> index & 1:
                checksum ^= generator
    return checksum
