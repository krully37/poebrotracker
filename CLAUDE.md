# Stash Display (poebrotracker)

A USB-wired 3.5" desk screen (Guition JC3248W535, ESP32-S3) that shows a Path of Exile 1 stash value from WealthyExile. It is for a friend who uses Windows only. The owner develops on a Mac and flashes the firmware before handing the screen over.

- `docs/SCOPE.md`: the agreed scope, every decision so far, open questions (§9) and the build order (§10). Read it before starting a step.
- `docs/PROTOCOL.md`: the PC ↔ screen serial protocol. The tests in `pc/tests/test_link.py` win if the two disagree.
- `pc/`: the Python app (renderer, settings page, screen link, simulator). Setup and run commands are in `pc/README.md`.
- `firmware/`: the screen side (step 6, not started).

Status on 2026-10-27: steps 1–4b are done, and the `Client.txt` watcher is checked against a real English-client log on Windows (`docs/SCOPE.md` §9). Next is step 5, once the screen arrives. `git log` shows anything newer.

## How to work here

- **Stop and ask whenever there is doubt or more than one way to build something.** Before writing code for a new part, list the open design choices with a recommendation, and wait for answers. Only keep going alone when the choices left are trivial.
- Record decisions in `docs/SCOPE.md` (and `docs/PROTOCOL.md` for the protocol) as they are made.
- Run the tests before committing: `pc/.venv/bin/python -m pytest` (on Windows, `pc\.venv\Scripts\python -m pytest`).
- When trying the app, set `STASHDISPLAY_HOME` to a throwaway folder so the real settings are not touched.
- Commit as `krully37` <58934068+krully37@users.noreply.github.com> (set it with `git config` in a new clone).
- **Never leave commits unpushed without asking.** After every commit, push to `origin` if the owner asked for it; otherwise ask whether to push before ending the turn.

## Hard constraints

These come from the original brief and are not up for change without the owner saying so.

- **Nothing touches the game.** No memory reading, no input injection, no overlay. `Client.txt` is only tailed, read-only.
- **The WealthyExile cookie stays on the PC.** The screen only ever receives images. The cookie is never committed or logged, never sent to the settings page, and is stored with DPAPI on Windows. It is pasted by hand, never read from the browser's cookie store.
- **The settings server binds 127.0.0.1 only**, with the per-install token and Host/Origin checks on every request.
- **Polite polling.** WealthyExile about every 5 minutes, no hammering. poe.ninja at most every 30 minutes for prices and weekly for the icon index, with a descriptive User-Agent, honouring cache headers and ETags.
- **No personal cloud service.**
- **Game art and the Fontin font are downloaded and cached locally, never committed.**
- **Never work around bot protection** (Cloudflare checks and the like) on any site.
