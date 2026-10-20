import json
import re


def partial_json_strings(buffer: str, key: str) -> list[str]:
    """Every value of string field `key` that has started in a partial JSON document, decoded as
    far as it has arrived ("answer" for the original format, "text" for each sentence).

    Used only for provisional display while the model streams; the final answer always comes from
    parsing and validating the complete JSON. Stops before an incomplete escape sequence.
    """
    pattern = re.compile('"' + re.escape(key) + r'"\s*:\s*"')
    return [_decode_from(buffer[m.end() :]) for m in pattern.finditer(buffer)]


def partial_json_string(buffer: str) -> str:
    """The "answer" value of a partial ModelAnswer JSON, as far as it has arrived."""
    values = partial_json_strings(buffer, "answer")
    return values[0] if values else ""


def _decode_from(raw: str) -> str:
    end = 0
    while end < len(raw):
        char = raw[end]
        if char == "\\":
            if end + 1 >= len(raw):
                break
            if raw[end + 1] == "u":
                if end + 6 > len(raw):
                    break
                end += 6
                continue
            end += 2
            continue
        if char == '"':
            break
        end += 1
    try:
        return str(json.loads('"' + raw[:end] + '"'))
    except json.JSONDecodeError:
        return ""
