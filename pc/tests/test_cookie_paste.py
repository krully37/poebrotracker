import re
import shlex

import pytest

from stashdisplay.web.cookie_paste import cookie_from_paste

URL = "https://wealthyexile.com/stash"
# Made-up values, shaped like the site's: a Next.js session token and a Cloudflare cookie.
COOKIE = "__Secure-next-auth.session-token=eyJhbGciOi.J9-x_y%2Fz; cf_clearance=Ab.c-1700000000-1.2.1.1-x%3D"


def chrome_cmd(s: str) -> str:
    """How Chrome's "Copy as cURL (cmd)" quotes an argument (DevTools' escapeStringWin)."""
    s = s.replace("\\", "\\\\").replace('"', '\\"')
    s = re.sub(r"[^a-zA-Z0-9\s_\-:=+~'/.',?;()*`&]", lambda m: "^" + m.group(0), s)
    s = re.sub(r"%(?=[a-zA-Z0-9_])", "%^", s)
    return '^"' + s + '^"'


def test_the_value_alone_is_kept_as_it_was():
    assert cookie_from_paste(COOKIE) == COOKIE
    assert cookie_from_paste(f"  {COOKIE};\n") == COOKIE
    assert cookie_from_paste(f'"{COOKIE}"') == COOKIE


@pytest.mark.parametrize("line", [f"Cookie: {COOKIE}", f"cookie:{COOKIE}", f"COOKIE :  {COOKIE}"])
def test_the_cookie_line(line):
    assert cookie_from_paste(line) == COOKIE


def test_request_headers_copied_whole():
    chrome = f":authority: wealthyexile.com\r\n:method: GET\r\naccept: text/html\r\ncookie: {COOKIE}\r\nuser-agent: Mozilla/5.0\r\n"
    firefox = f"GET /stash HTTP/2\nHost: wealthyexile.com\nCookie: {COOKIE}\nConnection: keep-alive\n"
    assert cookie_from_paste(chrome) == COOKIE
    assert cookie_from_paste(firefox) == COOKIE


def test_response_headers_are_not_a_cookie():
    assert cookie_from_paste("content-type: text/html\nset-cookie: a=b; Path=/; HttpOnly\n") is None


def test_curl_bash_from_chrome():
    paste = (f"curl {shlex.quote(URL)} \\\n  -H 'accept: text/html' \\\n  -b {shlex.quote(COOKIE)} \\\n"
             "  -H 'user-agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64)'")
    assert cookie_from_paste(paste) == COOKIE


def test_curl_bash_with_a_cookie_header():
    paste = f"curl '{URL}' --compressed -H 'Accept: text/html' -H 'Cookie: {COOKIE}' -H 'TE: trailers'"
    assert cookie_from_paste(paste) == COOKIE


def test_curl_bash_with_dollar_quotes():
    paste = f"curl '{URL}' \\\n  -b $'{COOKIE}' \\\n  --data-raw $'x=1'"
    assert cookie_from_paste(paste) == COOKIE


def test_curl_cmd_from_chrome():
    paste = (f"curl {chrome_cmd(URL)} ^\n  -H {chrome_cmd('accept: text/html')} ^\n  -b {chrome_cmd(COOKIE)} ^\n"
             f"  -H {chrome_cmd('user-agent: Mozilla/5.0 (Windows NT 10.0)')}")
    assert "^%^" in paste  # the escaping under test is really there
    assert cookie_from_paste(paste) == COOKIE


def test_curl_cmd_with_a_cookie_header():
    paste = f"curl.exe {chrome_cmd(URL)} -H {chrome_cmd('Cookie: ' + COOKIE)}"
    assert cookie_from_paste(paste) == COOKIE


def test_powershell_from_chrome():
    paste = (
        "$session = New-Object Microsoft.PowerShell.Commands.WebRequestSession\n"
        '$session.UserAgent = "Mozilla/5.0"\n'
        '$session.Cookies.Add((New-Object System.Net.Cookie("__Secure-next-auth.session-token", '
        '"eyJhbGciOi.J9-x_y%2Fz", "/", "wealthyexile.com")))\n'
        '$session.Cookies.Add((New-Object System.Net.Cookie("cf_clearance", "Ab.c-1700000000-1.2.1.1-x%3D", '
        '"/", ".wealthyexile.com")))\n'
        f'Invoke-WebRequest -UseBasicParsing -Uri "{URL}" `\n-WebSession $session'
    )
    assert cookie_from_paste(paste) == COOKIE


@pytest.mark.parametrize("paste", [
    "", "   ", "hello", URL, f"{URL}?a=b", "curl 'https://wealthyexile.com/stash' -H 'accept: */*'",
    "curl 'https://wealthyexile.com/stash' -b 'a=b",  # cut short
    "curl x -b cookies.txt", "line one\nline two=3", "a=b; c d=e", "a=bé",
])
def test_no_cookie_in_the_paste(paste):
    assert cookie_from_paste(paste) is None
