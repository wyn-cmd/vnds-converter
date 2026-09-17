# vnds-converter

Turn a visual novel's assets into the formats VNDS reads on a Nintendo DS, and stop guessing why a converted game shows a blank screen.

I converted Ren'Py games to VNDS by hand, one folder at a time, with a pile of throwaway shell scripts. This is that pile, cleaned up: the same conversions, with the filename and overwrite traps handled properly, a dry run for anything destructive, and tests that prove the output sizes are the ones the DS actually needs. It also converts the script itself, so you are not staring at a finished asset folder wondering why the game still will not run.

**This repository contains no game assets.** No artwork, no audio, no fonts, no saves, not even a converted `.scr` from a real game. Only the scripts and the documentation, because the games this was built around belong to their authors and none of it can be redistributed from here. `scripts/check-no-media.sh` enforces that and runs in the test suite, so a stray asset cannot ride along by accident.

## What it does

Four stages, each usable alone or through `convert.sh`:

  `images.sh --mode background` forces backgrounds onto exactly 256x192, the DS screen, stretching by default or letterboxing with `--fit`
  `images.sh --mode foreground` scales sprites to a fixed height of 180 by default, keeping their aspect ratio and transparency
  `audio.sh` turns audio into MPEG-1 Layer 3 at 44100 Hz, and copies files that already are rather than re-encoding them
  `renpy-to-vnds.py` converts your Ren'Py script files into `.scr` files for the DS, and reports everything it could not translate instead of guessing
  `rename.sh` strips spaces out of filenames, recursively or one level deep, with a dry run

## Requirements

  bash 4 or newer
  ImageMagick, either `magick` or `convert`
  ffmpeg and ffprobe for the audio stage

On Debian or Ubuntu:

```
sudo apt install imagemagick ffmpeg
```

## Quick start

```
git clone https://github.com/wyn-cmd/vnds-converter
cd vnds-converter

./convert.sh --title "My Game" \
    --background ~/work/backgrounds \
    --foreground ~/work/sprites \
    --sound ~/work/audio \
    ~/vnds-games/my-game
```

That writes `background/`, `foreground/` and `sound/` into the game folder, then strips spaces from everything it produced. Add `--title` and it writes `info.txt` too. Add `--dry-run` first if you want to see the plan without touching anything.

Three things this does not make: `default.ttf`, `icon.png` and `thumbnail.png`. Everything else, including the script itself, is covered here. The full folder layout and the reasons behind each number are in [docs/vnds-layout.md](docs/vnds-layout.md).

## Converting the script

```
./scripts/renpy-to-vnds.py -o ~/vnds-games/my-game/script -a ~/work/assets *.rpy
```

Each `.rpy` becomes a `.scr`, and the file holding `label start` becomes `main.scr`. The converter only writes commands that appear in finished VNDS games, counted across eighteen real script files: `text`, `bgload`, `setimg`, `cleartext`, `if`, `fi`, `gsetvar`, `setvar`, `music`, `sound`, `jump`, `goto`, `label`, `choice` and `delay`. That is the entire language as it is actually used, so there is no `hide`, no `else`, and no comment syntax.

Names are resolved rather than guessed. Character definitions, `image` blocks, `image x = im.Scale(...)` declarations and `define audio.x = "..."` aliases are all read from every file you pass in, so on a real game the sprites and tracks the script asks for are the ones the asset stages produced. Pass every `.rpy` in the project for that to work, including the ones you would not convert.

Hide statements are emulated, not just reported: the background is loaded again and the sprites that remain are re-placed, which is exactly what the finished games do, since the language has no hide command.

When Ren'Py does something that vocabulary cannot express, the statement is left out of the `.scr` and written to a `.report.txt` beside it, with the line number, the reason and a suggestion. Drops are never silent. The exit code is 2 when anything needs a human, so you can gate on it.

Layered sprites are the one thing worth knowing before you start. A character assembled at runtime from a body file and a face file cannot be drawn by `setimg`, so those sprites are left out and named on stderr. Flatten each expression to a single png first.

Full mapping table and the list of what has no counterpart: [docs/renpy-to-vnds.md](docs/renpy-to-vnds.md).

## Running a single stage

```
# backgrounds, letterboxed instead of stretched
./scripts/images.sh --mode background --fit ~/work/backgrounds out/background

# sprites at a custom height
./scripts/images.sh --mode foreground --height 160 ~/work/sprites out/foreground

# audio at a lower bitrate
./scripts/audio.sh --bitrate 128k ~/work/audio out/sound

# see which filenames a cleanup would move, before it moves them
./scripts/rename.sh --recursive --dry-run ~/vnds-games/my-game
```

## Options

`convert.sh`

```
--background DIR        images to force onto the 256x192 screen
--foreground DIR        sprite images to scale to a fixed height
--sound DIR             audio to turn into MP3
--title NAME            write info.txt as title=NAME when it is missing
--foreground-height N   sprite height, default 180
--bitrate B             MP3 bitrate, default 192k
--fit                   letterbox backgrounds instead of stretching them
--keep-names            do not strip spaces from the produced filenames
--dry-run               show what would happen, change nothing
```

`images.sh` takes `--mode background|foreground`, `--height N`, `--fit`, `--dry-run`, plus a source folder and an optional output folder. `audio.sh` takes `--bitrate`, `--rate`, `--force` and `--dry-run`. `rename.sh` takes `--recursive` and `--dry-run`. Every script prints its own usage with `--help`.

## What this fixes

These came out of the original scripts, and each one cost me real time on a converted game:

  **Overwrites on colliding names.** `my art.png` and `myart.png` both become `myart.png`, and a PNG plus a JPG with the same base name collide too, since everything is rebaked to PNG. The old scripts overwrote silently. These report the conflict and exit non-zero so you decide which file you meant.
  **Spaces in filenames.** VNDS resolves assets by name from its script, so a stray space gives you a blank screen rather than an error. There is a dedicated stage for it now, with a preview.
  **A `find | while read` loop that split on whitespace.** Filenames with spaces or newlines are now read null-delimited, and the loop no longer runs in a subshell, so its counters survive.
  **Pointless re-encoding.** An MP3 that is already MPEG-1 Layer 3 at 44100 Hz is copied byte for byte instead of being decoded and re-encoded, which throws away quality for nothing.
  **MPEG-2 MP3s that the DS cannot play.** A file encoded at 22050 Hz looks like an ordinary MP3 on a laptop and fails on the DS. The sample rate is checked and the file is converted when it is the wrong variant.
  **Cover art and tags riding along.** Album art embedded in an MP3 is a second stream that the DS cannot show and that wastes card space, so it is dropped during conversion.
  **Missing tools discovered halfway through a batch.** Each script checks for ffmpeg or ImageMagick up front and tells you what to install.
  **Unsafe runs of a moving stage.** `--dry-run` everywhere, and a dry run genuinely changes nothing, including not creating output folders.

## Repo layout

```
convert.sh                    run every stage in order for one game
scripts/images.sh             backgrounds and sprites
scripts/audio.sh              audio into DS friendly MP3
scripts/renpy-to-vnds.py      Ren'Py scripts into VNDS .scr scripts
scripts/rename.sh             strip spaces from filenames
scripts/check-no-media.sh     fail if any asset has slipped into the repo
lib/common.sh                 shared logging, tool checks and error handling
docs/vnds-layout.md           the folder layout the DS build expects, and why
docs/renpy-to-vnds.md         the command mapping and what it refuses to guess
tests/run-tests.sh            fixtures, a full run, and assertions on the results
tests/test_renpy_to_vnds.py   converter tests
```

## Tests

```
bash tests/run-tests.sh
```

The suite builds its own fixtures with ffmpeg and ImageMagick, runs the whole pipeline into a temporary folder and then checks the results rather than trusting the exit code: that backgrounds come out exactly 256x192, that a 100x400 sprite becomes 45x180, that a 22050 Hz MP3 is brought to 44100, that a good MP3 is copied byte for byte, that a non-audio file is left behind, that colliding names fail loudly, and that no spaces survive in the output. If ffmpeg or ImageMagick is missing it says so and exits rather than reporting fake passes.

The same run executes the converter tests, 42 of them, which drive the real command line and assert on the `.scr` that lands on disk, including a check that the converter never emits a command outside the vocabulary witnessed in finished games. It also runs the no-media guard, so a stray asset fails the suite.

## Limits

The script converter covers the common Ren'Py statement set and refuses to guess at the rest, so a real game will produce a report with items to fix by hand. That is deliberate: a silent drop is unrecoverable, a listed drop is a twenty minute job.

Sprite x positions default to a guess of 0, 78 and 156, because the finished games the vocabulary came from were hand tuned. Set them per character in a config file if yours need specific placement.

No transition beyond a fade, no `hide`, no loops, and no text interpolation. There is no VNDS command for any of them.

One level deep. Each asset stage converts the files directly inside the folder you point it at, not a tree, which keeps the mapping between source and output obvious.

PNG only for images. BMP is accepted on the DS but is usually a waste of space, so it is not offered.

Your script references have to match the stripped filenames, or you pass `--keep-names`.

Tested on Linux with bash 5, Python 3.12 and ImageMagick 6. Nothing in it is Linux specific, but that is what it has been run on.

## License

MIT, see [LICENSE](LICENSE).
