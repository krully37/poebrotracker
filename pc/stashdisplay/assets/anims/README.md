# Built-in event animations

Put the default animations here. They ship with the app and are sent to the screen's flash:

- `start.gif`: the screen starting (power-on, and each time the PC connects), and the game starting
- `levelup.gif`: played when one of the friend's characters levels up
- `death.gif`: played when one of them is slain

Guidelines:
- 480×320. Other sizes are cropped to fill the screen, centred.
- A GIF with see-through pixels plays over the current page instead, which stays underneath, dimmed. Other sizes are fitted inside the screen, in the bottom-right corner. Pixels are either opaque or see-through (below half alpha counts as see-through).
- About 1 MB or less each: they share the screen's ~11 MB with the page backgrounds.
- Around 15 fps until the real frame rate is measured on the hardware.
- No text is drawn on top, so bake in anything you want shown.
- A GIF plays once, except the level-up one, which plays twice (`EVENT_LOOPS` in `link/content.py`). Anything shorter than 3 s loops until 3 s; anything past 10 s is cut.

## How `levelup.gif` was made

From `images/lvlup.mp4` (the owner's phone video of the cat, 360×640, not committed). The video loops, so the paw reaching into the tray (7.8 s to the end) is joined to the paw coming back to the mouth (start to 2.6 s). From `pc/`:

```
.venv/Scripts/python tools/anim_from_video.py ../images/lvlup.mp4 stashdisplay/assets/anims/levelup.gif --crop 270:180:45:205 --part 7.8- --part -2.6
```

Result: 480×320, 15 fps, 3.9 s (7.7 s on screen with two loops), about 650 KB. To pick a crop and the parts, look at a contact sheet of the video first, for example `ffmpeg -i IN.mp4 -vf "fps=4,scale=180:-1,tile=6x6" -frames:v 1 sheet.png`. `tools/anim_from_video.py` explains the options.

## How `start.gif` was made

The owner's cat, spinning. In `images/spin.mp4` (not committed) the real spin, 0:08 to 0:10, is too motion-blurred to read as a cat, so one sharp frame from just after it (about 0:11.1) was cut out and turned instead. The cut-out, `images/spin_cat_cutout.png` (not committed), was made with SAM 2 in a throwaway Python environment (four points on the cat, two on the floor), which is not a dependency of this app. From `pc/`:

```
.venv/Scripts/python tools/spin_gif.py ../images/spin_cat_cutout.png stashdisplay/assets/anims/start.gif --turns 5 --frames 12
```

Result: 480×320 on black, clockwise, 15 fps, 5 turns of 0.8 s (4 s, ending on the first pose), about 940 KB. The screen keeps one copy when the game start uses the same animation.

## How `death.gif` was made

From `images/death.mp4` (the owner's phone video of the cat, 360×640, not committed), 4 s to 6 s at 15 fps. The cat is cut out of each frame with [rembg](https://github.com/danielgatis/rembg) and its `birefnet-general-lite` model (`isnet-general-use` and `u2net` lost the cat in the blurry frames). rembg is not a dependency of the app; use a throwaway venv:

```
python -m venv rembg-venv
rembg-venv/Scripts/python -m pip install "rembg[cpu]"
ffmpeg -ss 4 -t 2 -i ../images/death.mp4 -vf fps=15 frames/%03d.png
rembg-venv/Scripts/rembg p -m birefnet-general-lite -ppm frames cut
```

The 30 cut-out frames (RGBA PNGs) are then saved as one GIF: alpha below 128 becomes the transparent colour, frames last 70 ms, and the last one (the scream) is held for 0.97 s so the clip lasts exactly 3 s and never restarts. That GIF goes through `gif_over_page()` in `link/content.py`, which scales it to 180×320 and puts it in the bottom-right corner of a 480×320 frame. Result: 3.0 s, about 510 KB. The cutout's straight bottom and right edges (where the cat runs off the video) sit on the screen's edges.

Until a file exists, the screen shows a text card instead ("Level 92", "Slain", "Path of Exile"); with no start animation, nothing plays.
The friend can replace each one in the settings page.
