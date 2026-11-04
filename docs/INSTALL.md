# Stash Display: install guide

The little screen shows your Path of Exile stash value. It needs one program on your Windows PC,
`StashDisplay.exe`, which reads your stash from WealthyExile and sends it to the screen over USB.
(Version française : [INSTALL.fr.md](INSTALL.fr.md).)

## 1. Install (2 minutes)

1. Put `StashDisplay.exe` in a folder of your own, for example `Documents\Stash Display`. There is
   nothing else to install.
2. Double-click it. Windows may say "Windows protected your PC" because the program is not
   signed: click **More info**, then **Run anyway**. Your antivirus may ask too; allow it.
3. A small icon appears next to the clock (look under the **^** arrow if you don't see it), and
   the settings page opens in your browser. That icon is the whole program: **right-click** it for
   the menu, **click** it to open the settings.
4. Plug the screen into the PC with its USB-C cable. No driver is needed: it plays its cat, then
   shows your pages once the program has found it.

## 2. Connect WealthyExile (3 minutes)

The program reads your stash on WealthyExile, so it needs your WealthyExile login, as a "cookie".

1. Log in to wealthyexile.com in your browser.
2. In the settings page, open the **Settings** tab. Next to **WealthyExile**, hover the **?**: it
   shows the steps to copy your cookie (F12, Network, reload, copy the Cookie line).
3. Paste it in the box, click **Save cookie**, then **Test**. It should say how many divines you
   have.

The cookie works like a password: never send it to anyone, not even to the person who made the
screen. It is stored encrypted on your PC and only ever goes to WealthyExile. When WealthyExile
logs you out (about once a month), the screen says **Cookie expired**: do these steps again.

## 3. Every day

- **Start with Windows**: right-click the icon and tick it once; the program then starts by
  itself.
- **Tap the screen** to sync WealthyExile now (a "Syncing WealthyExile..." message shows; new
  values come about 30 s later). Otherwise it updates every 5 minutes.
- **Swipe** left or right to change page. **Hold** your finger on div/h or the session gain to
  reset it.
- Level-ups, deaths and game starts play a little animation, read from the game's log file. The
  program never touches the game itself.
- When the PC is idle for 10 minutes, a cat bounces on the screen; touch it to get the pages back.

## 4. Maps

The **Maps** page (swipe to the last page) follows your maps, read from the same game log.

- **The current map**: its name, tier, a timer, the league mechanics met (Einhar, Alva,
  Delirium...), your deaths and portals. Side areas (Abyss, Vaal area, trials) count as part of the
  map.
- **The timer** counts only time inside the map. It shows **Paused** after 10 seconds without
  touching the keyboard or mouse, and **Outside the map** while you are in your hideout.
- **Maps this session** (today's under it), maps per hour, average map time and **div per map**
  (the session gain divided by the maps). Hold your finger on the map count to start a new session.
- **Back in your hideout after a map**, the program syncs WealthyExile by itself (at most once every
  5 minutes), so div per map stays current without tapping. It can be turned off in the settings
  page, under **Map tracker**.
- If the program starts while you are already in a map, the timer waits until you change area.

Your pages, backgrounds (images, GIFs, videos) and animations are all edited in the settings
page, with a live preview.

## If something is wrong

| The screen shows | What to do |
|---|---|
| "Waiting for the PC" | The program is not running, or the cable is unplugged. Start `StashDisplay.exe`. |
| "PC disconnected" (dim) | The program stopped or the cable was pulled. Start it again or replug the cable. |
| "Cookie expired" (top right) | WealthyExile logged you out. Paste a new cookie (part 2); the program reads it at once. Until then it stops asking WealthyExile and the screen keeps your last numbers. |
| "WealthyExile unavailable" | The site is down or asks for a check. Nothing to do: it tries again every 5 minutes. |
| "WealthyExile changed" | The site changed and the program cannot read it any more. Send the log (below). |
| "stale · 20m ago" | No new numbers for 15 minutes. Right-click the icon: its first line says why. |
| "waiting for data" | WealthyExile has not been read yet: check the cookie (part 2). |

The program writes a log at `%APPDATA%\stashdisplay\stashdisplay.log`: send it if you ask for help
(it never contains your cookie).

**PoE Pricer (optional).** If you run PoE Pricer, the program uses its divine price, and in the
settings page you can choose it as the source of your stash instead of WealthyExile.

## Uninstall

Right-click the icon, untick **Start with Windows**, click **Quit**, then delete
`StashDisplay.exe` and the folder `%APPDATA%\stashdisplay`.
