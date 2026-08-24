"""Proved PostgreSQL catalog-deparser equivalences.

These rewrites are deliberately narrower than a SQL formatter.  Text that does
not match a proved round-trip equivalence is left byte-exact, so catalog drift
still fails closed.
"""

import re


_LITERAL = r"'(?:''|[^'])*'"
_VARCHAR_ELEMENT = re.compile(
    rf"\s*(?P<literal>{_LITERAL})\s*::\s*character varying\s*\Z"
)
_TEXT_ELEMENT = re.compile(
    rf"(?:"
    rf"\s*(?P<literal_plain>{_LITERAL})\s*::\s*character varying\s*::\s*text\s*"
    rf"|"
    rf"\s*\(\s*(?P<literal_wrapped>{_LITERAL})\s*::\s*character varying\s*\)"
    rf"\s*::\s*text\s*"
    rf")\Z"
)
_TEXT_ARRAY_CAST = re.compile(r"::\s*text\s*\[\s*\]")
_CANONICAL_IDENTITY = "postgres-varchar-array-text-deparse-v1"


def canonicalize_varchar_array_text_casts(definition: str) -> str:
    """Unify PostgreSQL's two equivalent varchar-array-to-text renderings.

    Only literal arrays whose *every* element has the proved cast shape are
    rewritten.  Literal values and all surrounding predicate text stay exact.
    """

    chunks = []
    cursor = 0
    while True:
        array_at = definition.find("ARRAY[", cursor)
        if array_at < 0:
            chunks.append(definition[cursor:])
            break
        chunks.append(definition[cursor:array_at])
        close_at = _array_close(definition, array_at + len("ARRAY["))
        if close_at is None:
            chunks.append(definition[array_at:])
            break
        elements = _split_elements(
            definition[array_at + len("ARRAY["):close_at]
        )
        replacement = _canonical_element_cast_array(elements)
        if replacement is not None:
            chunks.append(replacement)
            cursor = close_at + 1
            continue
        array_start, cast_end = _array_level_text_cast(
            definition, array_at, close_at
        )
        replacement = _canonical_array_level_cast(elements)
        if cast_end is not None and replacement is not None:
            if array_start < array_at:
                chunks[-1] = chunks[-1][:-(array_at - array_start)]
            chunks.append(replacement)
            cursor = cast_end
            continue
        chunks.append(definition[array_at:close_at + 1])
        cursor = close_at + 1
    return "".join(chunks)


def _canonical_element_cast_array(elements):
    literals = []
    for element in elements:
        match = _TEXT_ELEMENT.fullmatch(element)
        if match is None:
            return None
        literals.append(match.group("literal_plain") or match.group("literal_wrapped"))
    return _render(literals)


def _canonical_array_level_cast(elements):
    literals = []
    for element in elements:
        match = _VARCHAR_ELEMENT.fullmatch(element)
        if match is None:
            return None
        literals.append(match.group("literal"))
    return _render(literals)


def _render(literals):
    return f"@{_CANONICAL_IDENTITY}[{','.join(literals)}]"


def _array_level_text_cast(definition, array_at, close_at):
    position = _skip_space(definition, close_at + 1)
    array_start = array_at
    if position < len(definition) and definition[position] == ")":
        opening = array_at - 1
        while opening >= 0 and definition[opening].isspace():
            opening -= 1
        if opening < 0 or definition[opening] != "(":
            return array_start, None
        array_start = opening
        position = _skip_space(definition, position + 1)
    match = _TEXT_ARRAY_CAST.match(definition, position)
    if match is None:
        return array_start, None
    return array_start, match.end()


def _array_close(definition, position):
    in_literal = False
    while position < len(definition):
        character = definition[position]
        if character == "'":
            if in_literal and position + 1 < len(definition) and definition[position + 1] == "'":
                position += 2
                continue
            in_literal = not in_literal
        elif character == "]" and not in_literal:
            return position
        position += 1
    return None


def _split_elements(body):
    result = []
    start = 0
    depth = 0
    in_literal = False
    position = 0
    while position < len(body):
        character = body[position]
        if character == "'":
            if in_literal and position + 1 < len(body) and body[position + 1] == "'":
                position += 2
                continue
            in_literal = not in_literal
        elif not in_literal:
            if character == "(":
                depth += 1
            elif character == ")":
                depth -= 1
                if depth < 0:
                    return ()
            elif character == "," and depth == 0:
                result.append(body[start:position])
                start = position + 1
        position += 1
    if in_literal or depth != 0:
        return ()
    result.append(body[start:])
    return tuple(result)


def _skip_space(value, position):
    while position < len(value) and value[position].isspace():
        position += 1
    return position
