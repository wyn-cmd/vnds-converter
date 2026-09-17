# Converting the script, not just the assets

`scripts/renpy-to-vnds.py` turns Ren'Py script files into `.scr` files that VNDS reads.

## The rule it follows

It only ever writes commands that appear in finished VNDS games. That vocabulary was counted across every `.scr` file to hand, eighteen files from two converted games:

```
 3112  text        362  bgload      360  setimg      136  cleartext
  117  if          115  gsetvar     112  fi           80  music
   48  jump         41  sound        33  label        32  goto
   27  choice       12  delay         4  setvar
```

Fifteen commands, and that is the entire language as it is actually used. There is no comment syntax in it, which is why the converter never writes `#` or `//` into a `.scr`, and why there is no `hide`, `else`, `elif` or `return`.

When Ren'Py does something outside that vocabulary, the converter does not invent a command to cover it. It leaves the statement out of the `.scr` and records it in a `.report.txt` written beside the output. A converted script that quietly dropped a jump would be far worse than one that tells you it could not translate the jump.

## What maps to what

| Ren'Py | VNDS | Notes |
| --- | --- | --- |
| `label chapter:` | `label chapter` | |
| `"A line."` | `text "A line."` then `text ~` | every line gets a continue after it |
| `e "A line."` | `text Eileen "A line."` | names come from every `Character()` in the project, not just this file |
| `e @ happy "A line."` | `text Eileen "A line."` | the `@` form and hyphenated attributes are read, then dropped |
| `narrator "A line."` where the character is `Character(None)` | `text "A line."` | a narrator has no name to print |
| `extend " more."` | `text "more."` | the DS cannot append to a text buffer, so it becomes its own line |
| `scene bg room` | `bgload bgroom.png` | the filename comes from the `image` declaration when there is one |
| `scene bg room:` with a transform block | `bgload bgroom.png` | the block is dropped, the trailing colon is not part of the name |
| `scene bg room with dissolve` | `bgload bgroom.png 30` | a fade is an extra argument on `bgload` |
| `show eileen happy` | `setimg eileenhappy.png 78 27` | |
| `show eileen happy at left` | `setimg eileenhappy.png 0 27` | |
| `hide eileen` | `bgload <current>` then `setimg` for what stays | there is no hide command, so the layer is redrawn the way finished games do it |
| `play music "a.mp3"` | `music a.mp3` | |
| `play music a_alias` | `music thefile.mp3` | `define audio.x = "..."` aliases are resolved |
| `play nature "birds.ogg"` | `sound birds.mp3` | a custom channel is mapped to sound and mentioned once |
| `stop music fadeout 3.0` | `music ~` | |
| `pause 1.0` and `pause(1.0)` | `delay 60` | seconds to frames, 60 frames a second |
| `$ flag = 1` | `setvar flag = 1` | |
| `$ flag += 1` | `setvar flag + 1` | |
| `jump chapter` | `goto chapter` | when the label is in the same file |
| `jump chapter` | `jump other.scr chapter` | when the label is in another file you passed in |
| `call chapter from _call_chapter_1` | `goto chapter` | the `from` clause is ignored, and the missing return is reported |
| `if flag == 1:` | `if flag == 1` ... `fi` | |
| `menu:` with options | `choice "A"|"B"` then `if selected == 1` ... `fi` | one branch per option, numbered from 1 |
| `"[name]"` in dialogue | `$name`, or `{$name}` before a word | the manual says braces separate a variable from the text around it |
| `"{i}text{/i}"` | `text` | styling is stripped, since the DS renders none of it |

Names are resolved from the project, not guessed. Every `Character()`, every `image X:` block, `image X = "..."` or `image X = im.Scale("...")` form, and every `define audio.x = "..."` alias is read from all the files you pass in, before any conversion happens. That list is printed on the first line of a run, so you can see whether it found what you expected.

## What has no counterpart

Each of these is reported with the line number, an explanation, and a suggestion, and none of them is faked in the output.

  `layeredimage` sprites are the big one. A character assembled from a body file plus a face file plus a blush file cannot be drawn by `setimg`, which takes one image and no compositing. Every layered sprite is counted in the report and the names are listed once on stderr at the end of the run. The fix is to flatten each expression into a single png and show that instead.
  A displayable such as `show text "..." as text4` or `Solid(...)` builds an image in code, so there is no file to point at.
  `call` and `return` have no equivalent pair. Only `jump` and `goto` exist, so a call becomes a `goto` and the report says so.
  `else:` and `elif:` do not exist. An `if` closes with `fi` and nothing else, so convert an alternative into an explicit comparison, or reach that path through a `choice`.
  Conditions other than `variable == number` are refused, including `and`, `or`, `not` and truthiness tests.
  `python:` and `init python:` blocks are skipped entirely.
  `transform`, `screen`, `style`, `voice`, `nvl`, `window` and the rest of the presentation layer are skipped, since none of it exists on the DS.
  Menu options with an `if` condition are flagged, because a VNDS choice always shows every option.
  Built-in pseudo-files such as `"<silence1.mp3>"` are skipped rather than turned into a filename that could never exist.
  A playlist, as in `play music ["a.mp3", "b.mp3"]`, uses the first track and says so, since VNDS plays one file per command.

## Using it

```
# one file
./scripts/renpy-to-vnds.py --out-dir out script.rpy

# a whole game, checking every image and audio reference against your assets
./scripts/renpy-to-vnds.py -o out -a ~/vnds-games/my-game *.rpy
```

Pass every `.rpy` file in the project, including the ones you would not expect to convert. Character names, image declarations and audio aliases are read from all of them, so leaving out the file that declares your sprites means the converter has to guess their filenames. A file that produces no commands comes out as an empty `.scr` and you can delete it.

Point `-a` at the game folder you built with `convert.sh`, not at your raw art, because that is where the renamed files actually live.

Other flags worth knowing: `--keep-tags` leaves Ren'Py text styling in place instead of stripping it, `--no-hide-redraw` reports hide statements instead of emulating them, `--positions left:0,center:90,right:170` overrides the sprite positions, `--config file.json` sets them per character, and `--allow-lossy` returns 0 even when items need attention.

The file containing `label start` is written as `main.scr`, which is the entry point VNDS looks for. Every other file keeps its own name, so `chapter2.rpy` becomes `chapter2.scr` and a `jump` to one of its labels becomes `jump chapter2.scr <label>`.

The exit code is 0 when everything translated, and 2 when anything needs a human. That makes it usable in a script: convert, and stop if the report is not empty. `--allow-lossy` forces 0 if you would rather always continue.

## The report

Each `.scr` gets a `.report.txt` beside it with three sections: what was translated and how many of each, what needs manual attention with a suggestion per item, and what was skipped and why. If the second section is empty the file says so, which is the one worth aiming for.

## Sprite positions

`setimg` takes an x and a y, and the y is 27 in every single call across the games studied, which is what puts a 180 pixel tall sprite on a 192 pixel screen. Left, center and right default to 0, 78 and 156.

Those x values are a reasonable guess, not a discovery: the finished games were hand tuned, and they use numbers like 40, 50, 150 and -40 for particular characters. If your sprites need specific placement, write a config file:

```json
{
  "characters": {"e": "Eileen", "mc": "$mc"},
  "positions": {"e": 50, "mc": -40},
  "sprite_y": 27,
  "inputs": {"name": "Alex"},
  "fade_frames": 30,
  "fps": 60
}
```

Pass it with `--config`. A name beginning with `$` is emitted as a variable, which is how one of the studied games shows its player character's custom name.

The `inputs` entry answers a prompt for you. When a game asks the player to type something, usually their name, there is nothing the DS can do with it, because VNDS has no way to collect text. Instead of leaving the variable unset, the converter writes the configured value into the script as a plain assignment. Anything in your script that would have used what the player typed then reads a fixed answer. Pick whatever name you want to see, and expect it to be reported in the `.report.txt` so you know which line it replaced.
