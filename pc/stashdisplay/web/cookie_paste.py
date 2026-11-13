"""Find the WealthyExile cookie in whatever was pasted into the settings page.

Finding the Cookie line in the browser's developer tools was the fiddly part of the setup, so the
box takes anything the tools can copy for the page's request (docs/SCOPE.md §4c):
- "Copy as cURL", bash or cmd (Chrome, Edge, Firefox): the `-b`/`--cookie` value, or a
  `-H "cookie: ..."` header;
- "Copy as PowerShell" (Chrome, Edge): its `System.Net.Cookie(name, value, ...)` lines;
- the request's headers copied whole, or only the Cookie line, with or without `Cookie:`;
- the Cookie header's value alone, as before.
The paste holds the session: nothing here is ever logged.
"""

import re
import shlex

_CURL = re.compile(r"curl(\.exe)?\s", re.IGNORECASE)
_HEADER_LINE = re.compile(r"^[ \t]*cookie[ \t]*:[ \t]*(.*?)[ \t]*\r?$", re.IGNORECASE | re.MULTILINE)
_HEADER_ARG = re.compile(r"\s*cookie\s*:\s*(.*)", re.IGNORECASE | re.DOTALL)
_PS_COOKIE = re.compile(r'System\.Net\.Cookie\(\s*"((?:[^"`]|`.)*)"\s*,\s*"((?:[^"`]|`.)*)"')
_PS_ESCAPE = re.compile(r"`(.)", re.DOTALL)
_CARET = re.compile(r"\^(.)", re.DOTALL)
# One `name=value` of a Cookie header: the name is an HTTP token, the value is printable ASCII
# without a space or `;`.
_PAIR = re.compile(r"[!#$%&'*+\-.^_`|~0-9A-Za-z]+=[!-:<-~]*")


def cookie_from_paste(text: str) -> str | None:
    """The Cookie header to send, or None when the paste holds no cookie."""
    text = (text or "").strip()
    if not text:
        return None
    if _CURL.match(text):
        found = _from_curl(text)
    elif _PS_COOKIE.search(text):
        found = [_ps(name) + "=" + _ps(value) for name, value in _PS_COOKIE.findall(text)]
    else:
        found = _HEADER_LINE.findall(text) or [text]
    return _header(found)


def _from_curl(text: str) -> list[str]:
    if '^"' in text:
        # cmd: undo cmd.exe's caret escapes; what is left is quoted like a C program's arguments.
        text = _CARET.sub(r"\1", text)
    else:
        # bash: lines end in a backslash, and $'...' is used for values with unusual characters.
        text = re.sub(r"\\\r?\n", " ", text)
        text = re.sub(r"(?<=\s)\$'", "'", text)
    try:
        args = shlex.split(text)
    except ValueError:  # an unclosed quote: the paste was cut short
        return []
    found = []
    it = iter(args)
    for arg in it:
        if arg in ("-b", "--cookie"):
            value = next(it, "")
            if "=" in value:  # otherwise it names a cookie file
                found.append(value)
        elif arg in ("-H", "--header"):
            m = _HEADER_ARG.fullmatch(next(it, ""))
            if m:
                found.append(m.group(1))
    return found


def _ps(s: str) -> str:
    return _PS_ESCAPE.sub(r"\1", s)


def _header(found: list[str]) -> str | None:
    parts = []
    for chunk in found:
        chunk = chunk.strip()
        if len(chunk) >= 2 and chunk[0] == chunk[-1] and chunk[0] in "\"'":
            chunk = chunk[1:-1]  # quotes around a copied value
        parts += [p.strip() for p in chunk.split(";") if p.strip()]
    if not parts or not all(_PAIR.fullmatch(p) for p in parts):
        return None
    return "; ".join(parts)
