# poebrotracker

A 3.5" USB touchscreen that sits next to the keyboard and shows the value of a Path of Exile 1 stash, as computed by WealthyExile: total in divines, divines/hour, session gain, most valuable items, plus fully custom pages built in a local settings page.

**Status:** scoping done, building in progress. Hardware not received yet.

- [docs/SCOPE.md](docs/SCOPE.md): what we're building and the decisions made (start here)
- [docs/BRIEF.md](docs/BRIEF.md): the original brief
- [pc/README.md](pc/README.md): run the PC app and its previews

## Layout

| Folder | What |
|---|---|
| `pc/` | Windows background app (Python): fetches WealthyExile, renders the pages, serves the settings page, drives the screen over USB |
| `firmware/` | ESP32-S3 firmware (PlatformIO, Arduino): stores and shows the pages, handles touch, animations and backgrounds |
| `docs/` | Brief, scope, and later the protocol and install guide |

## Secrets

The WealthyExile session cookie lives only in the user's settings file (`%APPDATA%\stashdisplay\settings.json` on Windows). It is never committed and never sent to the screen.

Game icons and the Fontin font are downloaded on first run into `%APPDATA%\stashdisplay\cache` and are never committed (see [docs/SCOPE.md](docs/SCOPE.md) §4b).
