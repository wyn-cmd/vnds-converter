# The VNDS game layout

This describes the folder structure and the file constraints that the converter produces. It was reverse engineered from two finished VNDS games rather than taken from an official specification, so treat it as a working description: it matches what the interpreter accepted for those games.

```
<game>/
  background/     one PNG per background, exactly 256x192
  foreground/     one PNG per sprite, scaled to a height of 180
  sound/          MP3, MPEG-1 Layer 3 at 44100 Hz
  script/         the VNDS script files that drive the game
  info.txt        title=<name of the game>
  default.ttf     the font the interpreter renders with
  icon.png        small icon shown in the game list
  thumbnail.png   larger image shown in the game list
```

The converter fills `background/`, `foreground/`, `sound/` and, when you pass `--title`, `info.txt`. Everything else is yours.

## Why the numbers are what they are

**Backgrounds are 256x192.** That is the original DS screen resolution, and a background has to cover it. Stretching is the default, which fills the screen but distorts anything that is not 4:3. `--fit` scales the image down until it fits and pads the rest with black, which keeps proportions and gives you letterbox bars instead.

**Sprites are scaled to height 180.** Sprites keep their aspect ratio, so only the height is set. 180 leaves 12 pixels of headroom inside the 192 pixel screen, which keeps a character from being clipped top and bottom.

**Audio is MPEG-1 Layer 3 at 44100 Hz.** MPEG-1 Layer 3 is what the DS build decodes. The sample rate is the reliable way to tell an MPEG-1 file from an MPEG-2 one, since MPEG-1 supports 32000, 44100 and 48000 Hz while MPEG-2 (and 2.5) top out at 24000. A file already in that exact form is copied across instead of re-encoded, because re-encoding to the same format only loses quality. Everything else is converted.

**Filenames have no spaces.** VNDS resolves assets by name out of its script files, and a space in a name is the most common reason a converted game shows a blank screen where an image should be. The converter strips spaces from the files it produces, which means the names your script references have to match the stripped ones. If your script was written against `5 - Small Stream Flowing.mp3`, it needs `5-SmallStreamFlowing.mp3` after conversion, or you pass `--keep-names` and live with the risk.

## Things that bite

**Two source files can collapse onto one output name.** `my art.png` and `myart.png` both become `myart.png` once spaces are gone, and converting a PNG and a JPG with the same base name produces the same collision. The scripts never overwrite in that case. They report the conflict and exit non-zero, so you can decide which file you meant. A silent overwrite here wastes hours later.

**Re-encoding an already fine MP3.** The audio stage checks the codec and rate first, so a good file is copied rather than re-encoded. Pass `--force` if you want everything re-encoded anyway.

**Embedded cover art.** An MP3 with album art carries a second stream. It is dropped during conversion, since the DS cannot display it and it just burns card space.

**Input formats are usually a mess.** Real folders contain WAV, OGG, M4A and MP3 side by side with spaces in every other filename. Run the rename stage first on your source folders, or convert and let the last stage clean up the results. Doing it to your sources is the safer habit, so your script references never move underneath you.

## Stage by stage

```
convert.sh --title "My Game" \
    --background ~/work/backgrounds \
    --foreground ~/work/sprites \
    --sound ~/work/audio \
    ~/vnds-games/my-game
```

Each stage can also be run on its own:

```
scripts/images.sh --mode background --fit ~/work/backgrounds out/background
scripts/images.sh --mode foreground --height 180 ~/work/sprites out/foreground
scripts/audio.sh --bitrate 192k ~/work/audio out/sound
scripts/rename.sh --recursive --dry-run ~/vnds-games/my-game
```

`--dry-run` is available everywhere and prints exactly what would change without touching a file. Use it on the rename stage at minimum, since that one moves files around.
