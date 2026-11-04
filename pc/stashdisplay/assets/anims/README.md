# Built-in event animations

Put the default animations here. They ship with the app and are sent to the screen's flash:

- `start.gif`: the screen starting (power-on, and each time the PC connects), and the game starting
- `levelup.gif`: played when one of the friend's characters levels up
- `death.gif`: played when one of them is slain
- `lastportal.gif`: played when going back into an atlas map with one portal left
- `idle.png`: the idle cat, which the screen bounces around while the PC is idle (not a GIF: the screen moves and turns it itself)

Guidelines:
- 480×320. Other sizes are cropped to fill the screen, centred.
- A GIF with see-through pixels plays over the current page instead, which stays underneath, dimmed. They are fitted inside the screen, on its bottom edge, with what they show centred left to right. Pixels are either opaque or see-through (below half alpha counts as see-through).
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

## How `lastportal.gif` was made

From `images/run-bitch-run.gif` (a film clip the owner picked, 498×222, 10 fps, 2.5 s, not committed). Each frame is cropped to fill 480×320 (cover, centred), then all frames are mapped to one shared 64-colour palette without dithering and saved through `gif.encode()`. Live footage changes every pixel in every frame, so at the full 255 colours it was 2.9 MB; with 64 it is 1.8 MB and looks the same on the screen. From `pc/`:

```
.venv/Scripts/python -c "
from PIL import Image, ImageSequence
from stashdisplay.link import gif
from stashdisplay.media import compose_background
with Image.open('../images/run-bitch-run.gif') as im:
    frames = [compose_background(f, 'cover', 50, 50) for f in ImageSequence.Iterator(im)]
strip = Image.new('RGB', (480 * len(frames), 320))
for i, f in enumerate(frames): strip.paste(f, (480 * i, 0))
palette = strip.quantize(64, method=Image.Quantize.MEDIANCUT)
frames = [f.quantize(palette=palette, dither=Image.Dither.NONE).convert('RGB') for f in frames]
open('stashdisplay/assets/anims/lastportal.gif', 'wb').write(gif.encode(frames, [100] * len(frames)))
"
```

It plays twice (`EVENT_LOOPS`): 5 s.

## How `idle.png` was made

The tabby on the left of the owner's night photo of two cats on the window sill (`images/idle-photo.jpg`, 900×1600, not committed). The cat was cropped out first (x 110 to 460, y 630 to 875), so the ginger cat beside it could not confuse the model, then cut out with rembg and its `birefnet-general` model (it keeps the whiskers; `isnet-general-use` lost them), in the same throwaway venv as the death GIF, and trimmed to its visible pixels: 230×199. The bottom edge is straight, where the sill hides the paws.

The app scales it to 150 px wide (`IDLE_WIDTH` in `link/content.py`) and sends it in the overlay format, about 13 kB. Keep any replacement no wider than the cat in its photo, or it gets blurry.

Until a file exists, the screen shows a text card instead ("Level 92", "Slain", "Path of Exile"); with no start animation, nothing plays.
The friend can replace each one in the settings page.
