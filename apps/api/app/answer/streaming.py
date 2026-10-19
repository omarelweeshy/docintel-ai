import json
import re

_KEY = re.compile(r'"answer"\s*:\s*"')


def partial_json_string(buffer: str) -> str:
    """Decode as much of the "answer" string value as has arrived in a partial JSON object.

    Used only for provisional display while the model streams; the final answer always comes from
    parsing and validating the complete JSON. Stops before an incomplete escape sequence.
    """
    match = _KEY.search(buffer)
    if not match:
        return ""
    raw = buffer[match.end() :]
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
