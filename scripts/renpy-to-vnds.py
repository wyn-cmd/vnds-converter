#!/usr/bin/env python3
"""Convert Ren'Py script files into VNDS .scr script files.

The command set this emits is not guesswork. It is the vocabulary that appears in
finished VNDS games, counted across every script file the author had to hand:

    text (3112) bgload (362) setimg (360) cleartext (136) if (117) gsetvar (115)
    fi (112) music (80) jump (48) sound (41) label (33) goto (32) choice (27)
    delay (12) setvar (4)

Anything Ren'Py does that has no counterpart in that vocabulary is NOT invented.
It is left out of the .scr and listed in a .report.txt written beside it, so you
can fix it by hand. A converter that quietly drops a jump is worse than one that
refuses to guess.

The parse runs in two passes over a block tree. Pass one reads indentation into a
tree of statements, so a menu can be emitted as one choice line followed by its
branches, which is the shape VNDS expects. Pass two walks that tree and writes
commands.

Usage:
    renpy-to-vnds.py [options] FILE.rpy [FILE.rpy ...]

Options:
    -o, --out-dir DIR     where to write the .scr files (default: beside the input)
    -a, --assets DIR      asset folder to match image and audio names against
    -c, --config FILE     JSON with character names and sprite positions
    --main-label NAME     label that becomes main.scr (default: start)
    --no-cleartext        do not add cleartext ! to choice branches
    --allow-lossy         exit 0 even when something needs manual attention
    --stdout              print the .scr instead of writing files
"""

import argparse
import json
import os
import re
import sys

# Every command word witnessed in finished VNDS games. A test enforces that
# nothing outside this set is ever written to a .scr file.
VNDS_COMMANDS = {
    "text", "bgload", "setimg", "cleartext", "if", "fi", "music", "sound",
    "jump", "goto", "label", "choice", "delay", "setvar", "gsetvar",
}

# The y coordinate every setimg call uses in the games studied, which drops a
# 180 pixel sprite onto a 192 pixel screen with a small margin.
DEFAULT_SPRITE_Y = 27

# x coordinates for the three usual positions on a 256 pixel wide screen.
DEFAULT_POSITIONS = {"left": 0, "center": 78, "right": 156}

# What a setvar can hold: a number or a quoted string, since the DS has no
# interpreter to evaluate anything else.
LITERAL_VALUE = re.compile(r"""^(?:-?\d+(?:\.\d+)?|["'][^"']*["']|True|False)$""")

REPORT_ORDER = [
    "labels", "dialogue lines", "scene changes", "sprites shown", "sprites hidden",
    "hides redrawn", "layered sprites flattened", "music", "sound", "choices",
    "conditions", "jumps", "variables",
    "delays", "character definitions", "image declarations", "audio aliases",
    "text tags removed", "interpolations converted",
]

# Ren'Py statements with no VNDS counterpart. Reported, never translated into
# something invented.
UNSUPPORTED_PREFIXES = (
    "init", "python", "transform", "screen", "style", "layeredimage", "translate",
    "voice", "nvl", "camera", "camera ", "show screen", "hide screen", "call screen",
    "onlayer", "default", "persistent", "image", "animation", "frame", "key",
    "play voice", "queue voice", "window show", "window hide", "window auto",
    "nvl clear", "renpy.", "extend ", "define config", "pause music",
)


class Report:
    """Collects what was translated and what was not."""

    def __init__(self, source):
        self.source = source
        self.translated = {}
        self.attention = []
        self.skipped = []

    def count(self, category, amount=1):
        self.translated[category] = self.translated.get(category, 0) + amount

    def needs_attention(self, line_number, statement, reason, suggestion=None):
        self.attention.append((line_number, statement.strip(), reason, suggestion))

    def skipped_statement(self, line_number, statement, reason):
        self.skipped.append((line_number, statement.strip(), reason))

    def text(self):
        out = [f"report for {os.path.basename(self.source)}", ""]

        out.append("translated")
        if self.translated:
            for category in REPORT_ORDER:
                if category in self.translated:
                    out.append(f"  {self.translated[category]:5d}  {category}")
            for category in sorted(set(self.translated) - set(REPORT_ORDER)):
                out.append(f"  {self.translated[category]:5d}  {category}")
        else:
            out.append("  nothing")
        out.append(f"  {sum(self.translated.values()):5d}  total")
        out.append("")

        out.append(f"needs manual attention: {len(self.attention)}")
        if self.attention:
            for number, statement, reason, suggestion in self.attention:
                out.append(f"  line {number}: {statement[:88]}")
                out.append(f"      {reason}")
                if suggestion:
                    out.append(f"      do this: {suggestion}")
        else:
            out.append("  none, the whole file converted")
        out.append("")

        out.append(f"skipped statements: {len(self.skipped)}")
        if self.skipped:
            for number, statement, reason in self.skipped:
                out.append(f"  line {number}: {statement[:88]}")
                out.append(f"      {reason}")
        else:
            out.append("  none")
        out.append("")
        return "\n".join(out)


class Node:
    """One non-blank script line, with the lines indented under it."""

    __slots__ = ("number", "indent", "text", "children")

    def __init__(self, number, indent, text):
        self.number = number
        self.indent = indent
        self.text = text
        self.children = []


def strip_comment(line):
    """Drop a trailing # comment, ignoring any # inside a quoted string."""
    out = []
    quote = None
    index = 0
    while index < len(line):
        char = line[index]
        if quote:
            if char == "\\":
                out.append(char)
                index += 1
                if index < len(line):
                    out.append(line[index])
                index += 1
                continue
            if char == quote:
                quote = None
            out.append(char)
        elif char in "\"'":
            quote = char
            out.append(char)
        elif char == "#":
            break
        else:
            out.append(char)
        index += 1
    return "".join(out).rstrip()


def unquote(text):
    """Turn a Ren'Py string literal into plain text."""
    text = text.strip()
    for quote in ('"""', "'''", '"', "'"):
        if text.startswith(quote) and text.endswith(quote) and len(text) >= 2 * len(quote):
            return text[len(quote):-len(quote)]
    return text


def parse_tree(path):
    """Read a file into a list of top level Nodes, nesting by indentation."""
    with open(path, encoding="utf-8", errors="replace") as handle:
        raw_lines = handle.readlines()

    roots = []
    stack = []

    for number, raw in enumerate(raw_lines, start=1):
        line = strip_comment(raw.rstrip("\n"))
        if not line.strip():
            continue
        indent = len(line) - len(line.lstrip())
        node = Node(number, indent, line.strip())

        while stack and stack[-1].indent >= indent:
            stack.pop()
        if stack:
            stack[-1].children.append(node)
        else:
            roots.append(node)
        stack.append(node)

    return roots


def split_say(text):
    """Split a say statement into (speaker tag, string literal)."""
    if text.startswith(('"', "'")):
        return None, text
    match = re.match(
        r'^([A-Za-z_][A-Za-z0-9_]*)'
        r'((?:\s+(?:@\s*)?[A-Za-z0-9_-]+)*)'
        r'\s+(["\'].*)$',
        text)
    if match:
        return match.group(1), match.group(3)
    return None, None


def normalize_asset(expr, kind="image"):
    """Ren'Py image or audio expression to a VNDS filename."""
    cleaned = re.sub(r"\s+", "", expr.strip()).replace("/", "_")
    if kind == "image" and not cleaned.lower().endswith((".png", ".jpg", ".jpeg")):
        cleaned += ".png"
    return cleaned


def to_output_name(basename, extension):
    """Reproduce the filename the asset stages will produce."""
    stem = os.path.splitext(os.path.basename(basename.strip()))[0]
    return re.sub(r"[\s\t]+", "", stem) + extension


def build_asset_index(asset_dir):
    """Map normalised names to real filenames when an asset folder is given."""
    index = {}
    if not asset_dir or not os.path.isdir(asset_dir):
        return index
    for dirpath, _, filenames in os.walk(asset_dir):
        for name in filenames:
            if name.startswith("._"):
                continue
            stem, ext = os.path.splitext(name)
            key = re.sub(r"[\s_-]+", "", stem).lower() + ext.lower()
            index.setdefault(key, os.path.join(dirpath, name))
    return index


def find_asset(index, wanted):
    stem, ext = os.path.splitext(wanted)
    return index.get(re.sub(r"[\s_-]+", "", stem).lower() + ext.lower())


def split_transform_block(expression):
    """Separate an image name from an ATL block opener."""
    stripped = expression.strip()
    if stripped.endswith(":"):
        return stripped[:-1].strip(), True
    return expression, False


def collect_characters(paths):
    """Map speaker tags to display names across every file given."""
    names = {}
    pattern = re.compile(
        r'^\s*define\s+([A-Za-z_][A-Za-z0-9_]*)\s*=\s*Character\(\s*'
        r'(?:(["\'])(.*?)\2|(None))',
        re.M)
    for path in paths:
        try:
            with open(path, encoding="utf-8", errors="replace") as handle:
                text = handle.read()
        except OSError:
            continue
        for match in pattern.finditer(text):
            if match.group(4):
                names.setdefault(match.group(1), None)
            else:
                names.setdefault(match.group(1), match.group(3))
    return names


def parse_layered_images(paths):
    """Find layeredimage declarations, which are sprites built from layers."""
    layered = {}
    for path in paths:
        try:
            with open(path, encoding="utf-8", errors="replace") as handle:
                lines = handle.read().splitlines()
        except OSError:
            continue
        current = None
        for line in lines:
            start = re.match(r"^layeredimage\s+(.+?)\s*:\s*$", line)
            if start:
                current = start.group(1).strip()
                layered.setdefault(current, {})
                continue
            if current is None:
                continue
            if line.strip() and not line.startswith((" ", "\t")):
                current = None
                continue
            attribute = re.match(r'^\s+(?:group\s+\w+:|)?\s*attribute\s+([A-Za-z0-9_-]+)\s+"([^"]+)"', line)
            if attribute:
                layered[current][attribute.group(1)] = attribute.group(2)
    return layered


def parse_image_map(paths):
    """Map declared image names to the files they load."""
    images = {}
    for path in paths:
        try:
            with open(path, encoding="utf-8", errors="replace") as handle:
                lines = handle.read().splitlines()
        except OSError:
            continue
        for index, line in enumerate(lines):
            match = re.match(r"^\s*image\s+(.+?)\s*[:=]\s*(.*)$", line)
            if not match:
                continue
            name = match.group(1).strip()
            rest = strip_comment(match.group(2)).strip()
            source = None

            if rest.startswith(('"', "'")):
                source = unquote(rest)
            else:
                for quoted in re.finditer(r'["\']([^"\']+)["\']', rest):
                    candidate = quoted.group(1)
                    if "/" in candidate or re.search(
                            r"\.(png|jpe?g|webp|avif|bmp)$", candidate, re.I):
                        source = candidate
                        break

            if source is None and not rest:
                for following in lines[index + 1:index + 8]:
                    if not following.strip():
                        break
                    quoted = re.search(r'["\']([^"\']+)["\']', following)
                    if quoted:
                        source = quoted.group(1)
                        break
                    if not following.startswith((" ", "\t")):
                        break

            if source:
                images[name] = os.path.basename(source.strip())
    return images


def parse_audio_map(paths):
    """Map audio aliases to their files."""
    audio = {}
    pattern = re.compile(
        r'^\s*define\s+audio\.([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(["\'])(.*?)\2', re.M)
    for path in paths:
        try:
            with open(path, encoding="utf-8", errors="replace") as handle:
                text = handle.read()
        except OSError:
            continue
        for match in pattern.finditer(text):
            audio.setdefault(match.group(1), match.group(3))
    return audio


def convert_interpolation(text):
    """Turn Ren'Py [variable] interpolation into the VNDS $variable form."""
    made = 0
    pieces = []
    index = 0
    pattern = re.compile(r"\[([^\[\]]+)\]")

    protected = text.replace("[[", "\x00")

    while True:
        found = pattern.search(protected, index)
        if not found:
            pieces.append(protected[index:])
            break
        pieces.append(protected[index:found.start()])
        name = found.group(1).split("!")[0].strip()
        following = protected[found.end():found.end() + 1]
        if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name):
            made += 1
            if following and re.match(r"[A-Za-z0-9_]", following):
                pieces.append("{$" + name + "}")
            else:
                pieces.append("$" + name)
        else:
            pieces.append(found.group(0))
        index = found.end()

    return "".join(pieces).replace("\x00", "["), made


def strip_text_tags(text):
    """Remove Ren'Py text styling such as {i} or {w=0.3}, keeping {$var}."""
    return re.sub(r"\{(?!\$[A-Za-z_])[^}]*\}", "", text)


class Converter:
    def __init__(self, options, report, labels_by_file, source_path, output_names,
                 project):
        self.options = options
        self.report = report
        self.labels_by_file = labels_by_file
        self.source_path = source_path
        self.output_names = output_names
        self.characters = dict(project["characters"])
        self.characters.update(options["characters"])
        self.images = project["images"]
        self.audio_aliases = project["audio"]
        self.layered = project["layered"]
        self.output = []
        self.current_background = None
        self.visible_sprites = {}
        self.reported_channels = set()
        self.reported_layered = set()

    def declared_image(self, expression):
        """The file behind an image name, longest matching name first."""
        if not self.images:
            return None
        words = re.sub(r"\s+", " ", expression.strip()).split()
        for length in range(len(words), 0, -1):
            candidate = " ".join(words[:length])
            if candidate in self.images:
                return self.images[candidate]
        return None

    def flattened_sprite(self, expression):
        """The flattened png for a layered sprite, if the asset folder holds one."""
        index = self.options["assets"]
        if not index:
            return None
        wanted = normalize_asset(expression, "image")
        found = find_asset(index, wanted)
        if not found:
            stem = re.sub(r"[\s_-]+", "", os.path.splitext(wanted)[0]).lower()
            candidates = [key for key in index if key.startswith(stem)]
            if candidates:
                found = index[sorted(candidates, key=len)[0]]
        return to_output_name(os.path.basename(found), ".png") if found else None

    def layered_name(self, expression):
        """The layeredimage a show statement refers to, if any."""
        if not self.layered:
            return None
        words = re.sub(r"\s+", " ", expression.strip()).split()
        for length in range(len(words), 0, -1):
            candidate = " ".join(words[:length])
            if candidate in self.layered:
                return candidate
        return None

    def asset(self, expr, kind, node):
        into_audio = kind in ("music", "sound")

        if not into_audio:
            declared = self.declared_image(expr)
            if declared:
                return to_output_name(declared, ".png")
            wanted = normalize_asset(expr, "image")
        else:
            name = expr.strip()
            if name.startswith("audio."):
                name = name[len("audio."):]
            name = self.audio_aliases.get(name, name)
            wanted = to_output_name(name, ".mp3")

        index = self.options["assets"]
        if index:
            found = find_asset(index, wanted)
            if not found and not into_audio:
                stem = re.sub(r"[\s_-]+", "", os.path.splitext(wanted)[0]).lower()
                candidates = [key for key in index if key.startswith(stem)]
                if candidates:
                    found = index[sorted(candidates, key=len)[0]]
                    self.report.needs_attention(
                        node.number, node.text,
                        f"'{expr.strip()}' is not declared anywhere, so a file with a "
                        "matching name was used",
                        f"check that {os.path.basename(found)} is the image you meant")
            if found:
                return to_output_name(os.path.basename(found),
                                      ".mp3" if into_audio else ".png")
            self.report.needs_attention(
                node.number, node.text,
                f"no {kind} file matches '{wanted}' in the asset folder",
                f"add the file, or point --assets at the folder that holds it")
        return wanted

    def speaker(self, tag, node):
        if tag in self.characters:
            name = self.characters[tag]
            if not name:
                return None
            name, _ = convert_interpolation(name)
            if not self.options["keep_tags"]:
                name = strip_text_tags(name)
            return name
        self.report.needs_attention(
            node.number, node.text,
            f"character '{tag}' has no Character() definition, so its shown name is a guess",
            f'add define {tag} = Character("Display Name") to your script')
        return tag

    def emit(self, nodes):
        for node in nodes:
            self.statement(node)

    def statement(self, node):
        text = node.text

        define_match = re.match(
            r'^define\s+([A-Za-z_][A-Za-z0-9_]*)\s*=\s*Character\(\s*(["\'])(.*?)\2',
            text)
        if define_match:
            self.characters[define_match.group(1)] = define_match.group(3)
            self.report.count("character definitions")
            return

        label_match = re.match(r"^label\s+([A-Za-z_][A-Za-z0-9_]*)\s*:", text)
        if label_match:
            self.output.append(f"label {label_match.group(1)}")
            self.report.count("labels")
            self.emit(node.children)
            return

        if text.startswith("image "):
            self.report.count("image declarations")
            return
        if re.match(r"^define\s+audio\.", text):
            self.report.count("audio aliases")
            return
        if text.startswith("with "):
            self.report.count("transitions skipped")
            return
        if re.match(r"^(?:nvl\b|window\b|camera\b)", text):
            self.report.count("cosmetic statements skipped")
            return

        if text.startswith("scene "):
            return self.scene(node)

        if text.startswith("show ") or text.startswith("hide "):
            return self.sprite(node)

        if re.match(r"^(?:play|stop|queue)\s+\S", text):
            return self.audio(node)

        if re.match(r"^pause\b", text):
            return self.pause(node)

        if text == "menu:" or text.startswith("menu "):
            return self.menu(node)

        jump_match = re.match(r"^jump\s+(\S+)\s*$", text)
        if jump_match:
            self.jump(node, jump_match.group(1))
            return

        call_match = re.match(r"^call\s+(\S+)(?:\s+from\s+\S+)?\s*$", text)
        if call_match:
            self.report.needs_attention(
                node.number, text,
                "VNDS has no call and return pair, only jump and goto",
                f"inline {call_match.group(1)}, or use goto if it is never returned from")
            self.goto_label(node, call_match.group(1))
            self.report.count("jumps")
            return

        if text == "return" or text.startswith("return "):
            self.report.needs_attention(
                node.number, text,
                "VNDS has no return, so the story has to continue with a jump",
                "jump back to your menu script, or goto the label that carries on")
            self.report.count("jumps")
            return

        assign_match = re.match(
            r"^\$\s*([A-Za-z_][A-Za-z0-9_]*)\s*([+\-*/]=)\s*(.+)$", text)
        simple_match = re.match(
            r"^\$\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.+)$", text)
        chosen = assign_match or simple_match
        if chosen:
            name = chosen.group(1)
            value = chosen.group(3).strip() if assign_match else chosen.group(2).strip()
            if not LITERAL_VALUE.match(value):
                default = self.options["inputs"].get(name)
                if default is not None:
                    self.output.append(f'setvar {name} = "{default}"')
                    self.report.needs_attention(
                        node.number, text,
                        f"the DS cannot ask for '{name}', so it was set to "
                        f"\"{default}\" from the config",
                        "change the inputs entry in your config to answer differently")
                    self.report.count("variables")
                    return
                self.report.needs_attention(
                    node.number, text,
                    f"'{value[:40]}' is not a value setvar can hold",
                    "work out the value yourself and write the number or a quoted string")
                self.report.count("variables")
                return
            if assign_match:
                operator = chosen.group(2)[0]
                self.output.append(f"setvar {name} {operator} {value}")
            else:
                self.output.append(f"setvar {name} = {value}")
            self.report.count("variables")
            return

        if text.startswith("$"):
            self.report.needs_attention(
                node.number, text,
                "only a plain assignment can be written as setvar",
                "reduce the expression to a constant, or handle it in your VNDS script")
            self.report.count("variables")
            return

        if text.startswith("if ") and text.endswith(":"):
            return self.conditional(node)

        if text.startswith("while ") or text.startswith("for "):
            self.report.needs_attention(
                node.number, text,
                "VNDS has no loops; the script is a flat list of commands",
                "unroll the loop, or move the repetition into choice and goto")
            return

        if text.startswith("elif "):
            self.report.needs_attention(
                node.number, text,
                "VNDS has no elif, each branch needs its own if closed by fi",
                "close the branch above with fi and open a new if")
            return

        if text == "else:":
            self.report.needs_attention(
                node.number, text,
                "VNDS has no else, an if block closes with fi and no alternative",
                "write the inverse condition as its own if, or reach the path through choice")
            self.emit(node.children)
            return

        if text == "extend" or text.startswith("extend "):
            literal = text[len("extend"):].strip()
            if literal.startswith(('"', "'")):
                self.dialogue(node, None, literal)
            self.report.count("extend lines")
            return

        tag, literal = split_say(text)
        if literal is not None:
            return self.dialogue(node, tag, literal)

        for prefix in UNSUPPORTED_PREFIXES:
            if text.startswith(prefix):
                self.report.skipped_statement(
                    node.number, text,
                    f"'{prefix}' has no VNDS equivalent")
                return
        self.report.skipped_statement(node.number, text,
                                      "not recognised by the converter")

    def dialogue(self, node, tag, literal):
        text = unquote(literal)
        text, substitutions = convert_interpolation(text)
        if substitutions:
            self.report.count("interpolations converted", substitutions)
        tags = len(re.findall(r"\{[^}]*\}", text))
        if tags:
            if self.options["keep_tags"]:
                self.report.count("text tags kept", tags)
            else:
                text = strip_text_tags(text)
                self.report.count("text tags removed", tags)
        speech = text.replace('\\"', "'").replace("\\n", " ").replace('"', "'").strip()
        name = self.speaker(tag, node) if tag else None
        if name:
            self.output.append(f'text {name} "{speech}"')
        else:
            self.output.append(f'text "{speech}"')
        self.output.append("text ~")
        self.report.count("dialogue lines")

    def scene(self, node):
        text = node.text
        rest = text[len("scene "):]
        rest, transform_block = split_transform_block(rest)
        if transform_block:
            self.report.count("transform blocks dropped")
        with_clause = None
        with_match = re.search(r"\s+with\s+(\S+)\s*$", rest)
        if with_match:
            with_clause = with_match.group(1)
            rest = rest[:with_match.start()].strip()
        filename = self.asset(rest, "background", node)
        if with_clause and with_clause.lower().startswith("dissolve"):
            with_clause = "dissolve"
        if with_clause and with_clause.lower() not in ("none", "dissolve", "fade"):
            self.report.needs_attention(
                node.number, text,
                f"transition '{with_clause}' has no VNDS equivalent",
                "the DS has one hard cut and one fade, so a fade was used instead")
        if with_clause:
            self.output.append(f"bgload {filename} {self.options['fade_frames']}")
        else:
            self.output.append(f"bgload {filename}")
        self.current_background = filename
        self.visible_sprites.clear()
        self.report.count("scene changes")

    def sprite(self, node):
        text = node.text
        verb = "show" if text.startswith("show ") else "hide"
        rest = text[len(verb) + 1:]
        rest, transform_block = split_transform_block(rest)
        if transform_block:
            self.report.count("transform blocks dropped")
        position = None
        position_match = re.search(r"\s+at\s+(\S+)\s*$", rest)
        if position_match:
            position = position_match.group(1)
            rest = rest[:position_match.start()].strip()
        with_match = re.search(r"\s+with\s+(\S+)\s*$", rest)
        if with_match:
            rest = rest[:with_match.start()].strip()
        parts = rest.split()
        tag = parts[0] if parts else ""

        if verb == "hide":
            self.report.count("sprites hidden")
            self.visible_sprites.pop(tag, None)
            if not self.options["hide_redraw"]:
                self.report.needs_attention(
                    node.number, text,
                    "VNDS has no hide command and the redraw helper is switched off",
                    f"after hiding {tag}, re-issue setimg for each sprite still on screen")
                return
            self.redraw_sprites()
            return

        layered = self.layered_name(rest)
        if layered:
            filename = self.flattened_sprite(rest)
            if not filename:
                self.report.count("layered sprites skipped")
                self.reported_layered.add(layered)
                return
            self.report.count("layered sprites flattened")
        else:
            displayable = re.match(
                r"^(text|Solid|Null|Composite|Transform|Frame|Movie|Image)\b", rest)
            if displayable:
                self.report.count("displayables skipped")
                self.report.needs_attention(
                    node.number, text,
                    f"'{displayable.group(1)}' builds an image in code instead of loading a file",
                    "render it to a png yourself and show that file")
                return

            filename = self.asset(rest, "sprite", node)

        if tag in self.options["positions"]:
            x = self.options["positions"][tag]
        elif position and position in self.options["positions"]:
            x = self.options["positions"][position]
        else:
            x = self.options["positions"]["center"]
            if position not in (None, "center"):
                self.report.needs_attention(
                    node.number, text,
                    f"position '{position}' is not left, center or right",
                    f'add "{tag}": <x> to the positions map in your config')
        self.output.append(f"setimg {filename} {x} {self.options['sprite_y']}")
        self.visible_sprites[tag] = (filename, x)
        self.report.count("sprites shown")

    def redraw_sprites(self):
        """Redraw the layer the way the finished games do when a sprite leaves."""
        if self.current_background:
            self.output.append(f"bgload {self.current_background}")
        for filename, x in self.visible_sprites.values():
            self.output.append(f"setimg {filename} {x} {self.options['sprite_y']}")
        self.report.count("hides redrawn")

    def channel_command(self, channel, node):
        """VNDS has two audio channels, so custom ones have to pick a side."""
        if channel == "music":
            return "music"
        if channel in ("sound", "audio", "sfx", "voice"):
            return "sound"
        if channel not in self.reported_channels:
            self.reported_channels.add(channel)
            self.report.needs_attention(
                node.number, node.text,
                f"'{channel}' is a custom audio channel and VNDS has only music and sound",
                "it was mapped to sound, check that it does not cut the music off")
        return "sound"

    def audio(self, node):
        match = re.match(r"^(play|stop|queue)\s+(\S+)\s*(.*)$", node.text)
        if not match:
            self.report.skipped_statement(node.number, node.text,
                                          "audio statement not understood")
            return
        action, channel, rest = match.groups()
        command = self.channel_command(channel, node)

        if action == "stop":
            self.output.append(f"{command} ~")
            self.report.count(command)
            return

        quoted = re.match(r'^(["\'])(.*?)\1(.*)$', rest)
        if quoted:
            expr = quoted.group(2)
        elif rest.lstrip().startswith("["):
            first = re.search(r'["\']([^"\']+)["\']', rest)
            if not first:
                self.report.skipped_statement(node.number, node.text,
                                              "playlist without a readable track name")
                return
            expr = first.group(1)
            self.report.needs_attention(
                node.number, node.text,
                "this is a playlist, and VNDS plays one file per command",
                f"only {os.path.basename(expr)} was used, add the rest by hand if they matter")
        else:
            expr = re.sub(r"\s+(?:fadein|fadeout|volume|loop|noloop)\s+\S+", " ", rest)
            expr = re.sub(r"\b(?:loop|noloop)\b", " ", expr).strip()

        if not expr:
            self.report.skipped_statement(node.number, node.text,
                                          "play statement without a file")
            return

        if expr.startswith("<"):
            self.report.skipped_statement(
                node.number, node.text,
                f"'{expr}' is a built-in Ren'Py file with nothing behind it")
            return

        self.output.append(f"{command} {self.asset(expr, command, node)}")
        self.report.count(command)

    def pause(self, node):
        value = re.sub(r"^pause\s*\(?\s*|\)\s*$", "", node.text).strip() or "0.5"
        try:
            seconds = float(value)
        except ValueError:
            seconds = 0.5
        frames = max(1, int(round(seconds * self.options["fps"])))
        self.output.append(f"delay {frames}")
        self.report.count("delays")

    def menu(self, node):
        options = []
        for child in node.children:
            match = re.match(r'^(["\'])(.*?)\1(?:\s+if\s+(.*?))?\s*:\s*$', child.text)
            if match:
                options.append((child, match.group(2), match.group(3)))
            else:
                self.report.skipped_statement(
                    child.number, child.text, "menu option is not a plain label")
        self.report.count("choices")

        if not options:
            self.report.needs_attention(
                node.number, node.text, "menu has no options the converter understood")
            return

        choice_line = "choice " + "|".join(f'"{label}"' for _, label, _ in options)
        self.output.append(choice_line)

        for index, (child, label, condition) in enumerate(options, start=1):
            if condition:
                self.report.needs_attention(
                    child.number, child.text,
                    "VNDS choices cannot be conditional, every option always shows",
                    "check the option by hand, or split the menu in two")
            self.output.append(f"if selected == {index}")
            if not self.options["no_cleartext"]:
                self.output.append("cleartext !")
            self.emit(child.children)
            self.output.append("fi")

    def jump(self, node, target):
        if target.endswith(".scr") or "." in target:
            self.output.append(f"jump {target}")
            self.report.count("jumps")
            return
        self.goto_label(node, target)
        self.report.count("jumps")

    def goto_label(self, node, target):
        """A label in this file is a goto, one in another file is a jump."""
        own_labels = self.labels_by_file.get(self.source_path, set())
        if target in own_labels:
            self.output.append(f"goto {target}")
            return
        for path, labels in self.labels_by_file.items():
            if path != self.source_path and target in labels:
                other = self.output_names.get(
                    path, os.path.splitext(os.path.basename(path))[0] + ".scr")
                self.output.append(f"jump {other} {target}")
                return
        self.report.needs_attention(
            node.number, node.text,
            f"label '{target}' was not found in any file passed to the converter",
            "pass the file that defines it, or fix the spelling")
        self.output.append(f"goto {target}")

    def conditional(self, node):
        condition = node.text[3:-1].strip()
        if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*\s*[!=]=\s*-?\d+", condition):
            self.output.append(f"if {condition}")
            self.report.count("conditions")
            self.emit(node.children)
            self.output.append("fi")
            return
        self.report.needs_attention(
            node.number, node.text,
            "a VNDS condition compares one variable to a number",
            "restructure as 'if myvar == 1', or branch with choice instead")
        self.emit(node.children)
        self.output.append("fi")


def collect_labels(paths):
    """Map each file to the labels it defines, for cross file jumps."""
    labels = {}
    for path in paths:
        found = set()
        for node in parse_tree(path):
            match = re.match(r"^label\s+([A-Za-z_][A-Za-z0-9_]*)\s*:", node.text)
            if match:
                found.add(match.group(1))
        labels[path] = found
    return labels


def assign_output_names(sources, labels_by_file, main_label):
    """Pick a unique .scr name per input file before anything is written."""
    main_file = None
    for path in sources:
        if main_label in labels_by_file.get(path, set()):
            main_file = main_file or path

    names = {}
    used = {}
    collisions = []
    extra_mains = [p for p in sources
                   if p != main_file and main_label in labels_by_file.get(p, set())]

    for path in sources:
        if path == main_file:
            wanted = "main.scr"
        else:
            wanted = os.path.splitext(os.path.basename(path))[0] + ".scr"

        if wanted not in used:
            names[path] = wanted
            used[wanted] = path
            continue

        parent = os.path.basename(os.path.dirname(os.path.abspath(path))) or "root"
        candidate = f"{parent}_{wanted}"
        counter = 2
        while candidate in used:
            candidate = f"{parent}_{counter}_{wanted}"
            counter += 1
        names[path] = candidate
        used[candidate] = path
        collisions.append((path, wanted, candidate, used[wanted]))

    return names, collisions, extra_mains


def move_main_label_first(lines, main_label):
    """Put the entry label at the top of main.scr."""
    marker = f"label {main_label}"
    if not lines or lines[0] == marker or marker not in lines:
        return lines
    start = lines.index(marker)
    end = next((i for i in range(start + 1, len(lines)) if lines[i].startswith("label ")),
               len(lines))
    return lines[start:end] + lines[:start] + lines[end:]


def default_config():
    return {
        "characters": {},
        "positions": dict(DEFAULT_POSITIONS),
        "inputs": {},
        "sprite_y": DEFAULT_SPRITE_Y,
        "fade_frames": 30,
        "fps": 60,
        "no_cleartext": False,
        "keep_tags": False,
        "hide_redraw": True,
    }


def parse_config(path, options):
    with open(path, encoding="utf-8") as handle:
        data = json.load(handle)
    for key in ("characters", "positions", "inputs"):
        if key in data:
            options[key].update(data[key])
    for key in ("sprite_y", "fade_frames", "fps"):
        if key in data:
            options[key] = data[key]
    for key in ("keep_tags", "hide_redraw", "no_cleartext"):
        if key in data:
            options[key] = bool(data[key])
    return options


def count_statements(lines):
    """Count real statements, ignoring the continue prompts the converter adds."""
    return sum(1 for line in lines if line.strip() != "text ~")


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Convert Ren'Py scripts into VNDS .scr scripts.")
    parser.add_argument("inputs", nargs="+", help="Ren'Py .rpy files")
    parser.add_argument("-o", "--out-dir", help="where to write the .scr files")
    parser.add_argument("-a", "--assets", help="asset folder to match names against")
    parser.add_argument("-c", "--config", help="JSON config with names and positions")
    parser.add_argument("--main-label", default="start",
                        help="label that becomes main.scr (default: start)")
    parser.add_argument("--keep-tags", action="store_true",
                        help="keep Ren'Py text styling such as {i} instead of stripping it")
    parser.add_argument("--no-hide-redraw", action="store_true",
                        help="report hide statements instead of emulating them")
    parser.add_argument("--no-cleartext", action="store_true",
                        help="do not add cleartext ! to choice branches")
    parser.add_argument("--allow-lossy", action="store_true",
                        help="exit 0 even when something needs manual attention")
    parser.add_argument("--stdout", action="store_true",
                        help="print the result instead of writing files")
    args = parser.parse_args(argv)

    options = default_config()
    if args.no_cleartext:
        options["no_cleartext"] = True
    if args.keep_tags:
        options["keep_tags"] = True
    if args.no_hide_redraw:
        options["hide_redraw"] = False
    if args.config:
        try:
            options = parse_config(args.config, options)
        except (OSError, json.JSONDecodeError) as e:
            print(f"error: failed to load config file '{args.config}': {e}", file=sys.stderr)
            return 1
    options["assets"] = build_asset_index(args.assets) if args.assets else None

    sources = [path for path in args.inputs if os.path.isfile(path)]
    for path in set(args.inputs) - set(sources):
        print(f"error: {path} is not a file", file=sys.stderr)
    if not sources:
        return 1

    labels_by_file = collect_labels(sources)
    project = {
        "characters": collect_characters(sources),
        "images": parse_image_map(sources),
        "audio": parse_audio_map(sources),
        "layered": parse_layered_images(sources),
    }
    print(f"read {len(project['characters'])} character names, "
          f"{len(project['images'])} image files, "
          f"{len(project['audio'])} audio aliases and "
          f"{len(project['layered'])} layered sprites from the project",
          file=sys.stderr)

    output_names, collisions, extra_mains = assign_output_names(
        sources, labels_by_file, args.main_label)
    collisions_by_file = {}
    for path, wanted, renamed, owner in collisions:
        collisions_by_file.setdefault(path, []).append((wanted, renamed, owner))

    problems = 0
    hides_redrawn = 0
    layered_seen = set()
    for source in sources:
        report = Report(source)

        for wanted, renamed, owner in collisions_by_file.get(source, []):
            report.needs_attention(
                0, os.path.basename(source),
                f"another input already writes {wanted} "
                f"({os.path.basename(owner)}), so this one was written as {renamed}",
                f"update any 'jump {wanted}' reference to '{renamed}'")
        if source in extra_mains:
            report.needs_attention(
                0, os.path.basename(source),
                f"'{args.main_label}' appears here too, but only one file can be main.scr",
                "merge the duplicate start labels, or rename one of them")

        converter = Converter(options, report, labels_by_file, source, output_names,
                              project)
        converter.emit(parse_tree(source))
        output = converter.output

        out_name = output_names[source]
        if out_name == "main.scr":
            output = move_main_label_first(output, args.main_label)

        if args.stdout:
            print("\n".join(output))
            print("", file=sys.stderr)
            print(report.text(), file=sys.stderr)
        else:
            out_dir = args.out_dir or os.path.dirname(os.path.abspath(source))
            os.makedirs(out_dir, exist_ok=True)
            scr_path = os.path.join(out_dir, out_name)
            report_path = scr_path[:-4] + ".report.txt"
            try:
                with open(scr_path, "w", encoding="utf-8") as handle:
                    handle.write("\n".join(output) + "\n")
                with open(report_path, "w", encoding="utf-8") as handle:
                    handle.write(report.text())
            except OSError as e:
                print(f"error: failed to write output files for '{source}': {e}", file=sys.stderr)
                problems += 1
                continue
            print(f"{os.path.basename(source)} -> {os.path.basename(scr_path)} "
                  f"({count_statements(output)} statements, "
                  f"{len(report.attention)} need attention, "
                  f"{len(report.skipped)} skipped)")
            print(f"    wrote {report_path}")

        if report.attention:
            problems += 1
        hides_redrawn += report.translated.get("hides redrawn", 0)
        layered_seen.update(converter.reported_layered)

    if layered_seen:
        names = ", ".join(sorted(layered_seen)[:8])
        more = f" and {len(layered_seen) - 8} more" if len(layered_seen) > 8 else ""
        print(f"\n{len(layered_seen)} layered sprite(s) were left out: {names}{more}.\n"
              "A layeredimage is assembled from separate body and face files at runtime, "
              "and setimg draws one image with no way to compose layers. Flatten each "
              "expression to a single png, then point the script at that file instead.",
              file=sys.stderr)

    if hides_redrawn:
        print(f"\n{hides_redrawn} hide statement(s) were emulated by reloading the "
              "background and redrawing the sprites that stay. That is the pattern the "
              "finished games use, but the DS has no hide command, so check one scene "
              "on hardware before converting the whole thing.", file=sys.stderr)

    if problems:
        print(f"\n{problems} file(s) converted with items needing manual attention. "
              f"Read the .report.txt beside each .scr.", file=sys.stderr)
        return 0 if args.allow_lossy else 2
    return 0


if __name__ == "__main__":
    sys.exit(main())