# Built-in event animations

Put the default animations here. They ship with the app and are sent to the screen's flash:

- `levelup.gif`: played when one of the friend's characters levels up
- `death.gif`: played when one of them is slain

Guidelines:
- 480×320. Other sizes are cropped to fill the screen, centred.
- About 1 MB or less each: they share the screen's ~11 MB with the page backgrounds.
- Around 15 fps until the real frame rate is measured on the hardware.
- No text is drawn on top, so bake in anything you want shown.
- A GIF plays once. One shorter than 3 s loops until 3 s; anything past 10 s is cut.

Until a file exists, the screen shows a text card instead ("Level 92", "Slain").
The friend can replace either one in the settings page.
