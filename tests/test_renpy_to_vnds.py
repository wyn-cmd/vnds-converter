#!/usr/bin/env python3
"""Tests for the Ren'Py to VNDS script converter.

The tests drive the real command line entry point, then assert on the .scr that
lands on disk, because that is what the DS would read.

Run directly, or via tests/run-tests.sh.
"""

import importlib.util
import os
import shutil
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
CONVERTER = os.path.join(HERE, os.pardir, "scripts", "renpy-to-vnds.py")

# Loading the converter as a module would otherwise leave a __pycache__ folder
# next to it, which is not something to publish.
sys.dont_write_bytecode = True


def load_converter():
    spec = importlib.util.spec_from_file_location("renpy_to_vnds", CONVERTER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


MODULE = load_converter()


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(text)
    return path


class ConverterTestCase(unittest.TestCase):
    """Base class that runs the converter into a temporary output folder."""

    def setUp(self):
        self.work = tempfile.mkdtemp(prefix="vnds-renpy-test-")
        self.addCleanup(shutil.rmtree, self.work, ignore_errors=True)

    def convert(self, files, extra=()):
        """files: {name: source text}. Returns {name: .scr text}."""
        sources = []
        for name, text in files.items():
            sources.append(write(os.path.join(self.work, "src", name), text))
        out = os.path.join(self.work, "out")
        argv = [*sources, "-o", out, *extra]
        stderr = sys.stderr
        stdout = sys.stdout
        try:
            sys.stderr = open(os.devnull, "w", encoding="utf-8")
            sys.stdout = open(os.devnull, "w", encoding="utf-8")
            code = MODULE.main(argv)
        finally:
            sys.stderr.close()
            sys.stdout.close()
            sys.stderr = stderr
            sys.stdout = stdout
        self.last_code = code

        produced = {}
        for name in os.listdir(out):
            if name.endswith(".scr"):
                with open(os.path.join(out, name), encoding="utf-8") as handle:
                    produced[name] = handle.read()
        self.out_dir = out
        return produced

    def report_for(self, scr_name):
        path = os.path.join(self.out_dir, scr_name[:-4] + ".report.txt")
        with open(path, encoding="utf-8") as handle:
            return handle.read()

    def lines_of(self, scr_text):
        return [line for line in scr_text.splitlines() if line.strip()]


class VocabularyTests(ConverterTestCase):
    """The converter must only ever emit commands that real games use."""

    FIXTURE = '''\
define e = Character("Eileen")
label start:
    "It begins."
    e "Hello there."
    e happy "Still me."
    scene bg room
    scene bg hall with dissolve
    show eileen happy
    show eileen sad at left
    hide eileen
    play music "theme.mp3"
    play sound "door.ogg"
    stop music
    stop sound
    $ flag = 1
    $ flag += 1
    pause 0.5
    if flag == 1:
        "One."
    menu:
        "Go left":
            "Left."
            jump ending
        "Go right":
            "Right."
            jump ending
label ending:
    "Done."
    jump start
'''

    def test_only_witnessed_commands_are_emitted(self):
        produced = self.convert({"script.rpy": self.FIXTURE})
        self.assertIn("main.scr", produced)
        unknown = []
        for line in self.lines_of(produced["main.scr"]):
            word = line.split()[0]
            if word not in MODULE.VNDS_COMMANDS:
                unknown.append(line)
        self.assertEqual(unknown, [], f"emitted commands with no evidence: {unknown}")

    def test_no_comments_or_invented_markers(self):
        produced = self.convert({"script.rpy": self.FIXTURE})
        text = produced["main.scr"]
        for marker in ("#", "//", "rem ", "--"):
            self.assertNotIn(marker, text, f"output contains {marker}")

    def test_the_file_with_the_main_label_becomes_main_scr(self):
        produced = self.convert({"script.rpy": self.FIXTURE})
        self.assertEqual(list(produced), ["main.scr"])

    def test_a_file_without_the_main_label_keeps_its_name(self):
        produced = self.convert({"side.rpy": "label side:\n    \"Side.\"\n"})
        self.assertEqual(list(produced), ["side.scr"])


class StatementTests(ConverterTestCase):
    def test_narration_gets_a_continue(self):
        produced = self.convert({"s.rpy": '"Alone in the dark."\n'})
        self.assertEqual(self.lines_of(produced["s.scr"]),
                         ['text "Alone in the dark."', "text ~"])

    def test_character_definitions_supply_the_shown_name(self):
        produced = self.convert({
            "s.rpy": 'define e = Character("Eileen")\ne "Hi."\n'})
        self.assertIn('text Eileen "Hi."', produced["s.scr"])

    def test_attributes_on_a_say_line_do_not_break_it(self):
        produced = self.convert({
            "s.rpy": 'define e = Character("Eileen")\ne happy "Hi."\n'})
        self.assertIn('text Eileen "Hi."', produced["s.scr"])

    def test_an_undefined_speaker_is_flagged(self):
        self.convert({"s.rpy": 'bob "Hi."\n'})
        self.assertIn("no Character() definition", self.report_for("s.scr"))

    def test_scene_becomes_a_background_load(self):
        produced = self.convert({"s.rpy": "scene bg room\n"})
        self.assertEqual(self.lines_of(produced["s.scr"]), ["bgload bgroom.png"])

    def test_a_dissolve_adds_the_fade_argument(self):
        produced = self.convert({"s.rpy": "scene bg room with dissolve\n"})
        self.assertEqual(self.lines_of(produced["s.scr"]), ["bgload bgroom.png 30"])

    def test_show_becomes_setimg_at_the_default_position(self):
        produced = self.convert({"s.rpy": "show eileen happy\n"})
        self.assertEqual(self.lines_of(produced["s.scr"]),
                         ["setimg eileenhappy.png 78 27"])

    def test_at_left_moves_the_sprite(self):
        produced = self.convert({"s.rpy": "show eileen happy at left\n"})
        self.assertEqual(self.lines_of(produced["s.scr"]),
                         ["setimg eileenhappy.png 0 27"])

    def test_positions_can_be_configured_per_character(self):
        config = write(os.path.join(self.work, "cfg.json"),
                       '{"positions": {"eileen": 50}}')
        produced = self.convert({"s.rpy": "show eileen happy at left\n"},
                                extra=["-c", config])
        self.assertEqual(self.lines_of(produced["s.scr"]),
                         ["setimg eileenhappy.png 50 27"])

    def test_a_name_prompt_can_be_answered_from_the_config(self):
        # The DS cannot ask the player to type anything, so the answer has to be
        # settled before the script is written.
        config = write(os.path.join(self.work, "cfg.json"),
                       '{"inputs": {"name": "Alex"}}')
        produced = self.convert({"s.rpy": (
            "label start:\n"
            "    $ name = renpy.input(_(\"My name is:\"))\n"
            "    $ other = some_function()\n")},
            extra=["-c", config])
        lines = self.lines_of(produced["main.scr"])
        self.assertIn('setvar name = "Alex"', lines)
        # Anything with no answer configured is still refused rather than being
        # written out as an expression the DS would never evaluate.
        self.assertNotIn("setvar other", " ".join(lines))

    def test_hide_is_emulated_by_redrawing_what_stays(self):
        produced = self.convert({"s.rpy": (
            "label start:\n"
            "    scene bg room\n"
            "    show lake neutral\n"
            "    show bjorn\n"
            "    hide lake neutral\n")})
        lines = self.lines_of(produced["main.scr"])
        # The redraw reloads the background and re-places the sprites that stay,
        # which is the pattern the finished games use.
        self.assertEqual(lines, [
            "label start",
            "bgload bgroom.png",
            "setimg lakeneutral.png 78 27",
            "setimg bjorn.png 78 27",
            "bgload bgroom.png",
            "setimg bjorn.png 78 27",
        ])

    def test_hide_with_nothing_on_screen_emits_nothing(self):
        produced = self.convert({"s.rpy": "hide eileen\n"})
        self.assertEqual(self.lines_of(produced["s.scr"]), [])
        self.assertIn("hides redrawn", self.report_for("s.scr"))

    def test_hide_can_be_reported_instead(self):
        self.convert({"s.rpy": "hide eileen\n"}, extra=["--no-hide-redraw"])
        self.assertIn("no hide command", self.report_for("s.scr"))

    def test_audio_commands(self):
        produced = self.convert({"s.rpy": (
            'play music "theme.mp3"\n'
            'play sound "door.ogg"\n'
            "stop music\n"
            "stop sound\n")})
        # The audio stage writes mp3 whatever went in, so the ogg is asked for
        # by the name it will actually have.
        self.assertEqual(self.lines_of(produced["s.scr"]),
                         ["music theme.mp3", "sound door.mp3", "music ~", "sound ~"])

    def test_variables(self):
        produced = self.convert({"s.rpy": "$ flag = 1\n$ flag += 1\n"})
        self.assertEqual(self.lines_of(produced["s.scr"]),
                         ["setvar flag = 1", "setvar flag + 1"])

    def test_pause_becomes_a_delay_at_sixty_frames_a_second(self):
        produced = self.convert({"s.rpy": "pause 1.0\n"})
        self.assertEqual(self.lines_of(produced["s.scr"]), ["delay 60"])

    def test_a_label_becomes_a_label_and_a_goto_stays_local(self):
        produced = self.convert({"s.rpy": (
            "label start:\n"
            '    "Start."\n'
            "    jump chapter\n"
            "label chapter:\n"
            '    "Chapter."\n')})
        self.assertIn("goto chapter", produced["main.scr"])
        self.assertNotIn("jump chapter", produced["main.scr"])

    def test_a_jump_to_another_file_uses_the_cross_file_form(self):
        produced = self.convert({
            "main.rpy": "label start:\n    jump side\n",
            "side.rpy": "label side:\n    \"Side.\"\n",
        })
        # This is the form real games use: jump file.scr label
        self.assertIn("jump side.scr side", produced["main.scr"])

    def test_a_jump_to_a_missing_label_is_flagged(self):
        self.convert({"s.rpy": "label start:\n    jump nowhere\n"})
        self.assertIn("was not found", self.report_for("main.scr"))


class ChoiceTests(ConverterTestCase):
    FIXTURE = '''\
label start:
    menu:
        "Take the path":
            "You walk."
            jump ending
        "Turn back":
            "You leave."
        "Say nothing":
            "Silence."
label ending:
    "End."
'''

    def test_a_menu_becomes_one_choice_line_and_numbered_branches(self):
        produced = self.convert({"s.rpy": self.FIXTURE})
        lines = self.lines_of(produced["main.scr"])
        self.assertEqual(
            lines[1],
            'choice "Take the path"|"Turn back"|"Say nothing"')

    def test_each_branch_is_if_selected_cleartext_body_fi(self):
        produced = self.convert({"s.rpy": self.FIXTURE})
        lines = self.lines_of(produced["main.scr"])
        expected = [
            'choice "Take the path"|"Turn back"|"Say nothing"',
            "if selected == 1",
            "cleartext !",
            'text "You walk."',
            "text ~",
            "goto ending",
            "fi",
            "if selected == 2",
            "cleartext !",
            'text "You leave."',
            "text ~",
            "fi",
            "if selected == 3",
            "cleartext !",
            'text "Silence."',
            "text ~",
            "fi",
        ]
        self.assertEqual(lines[1:len(expected) + 1], expected)

    def test_cleartext_can_be_turned_off(self):
        produced = self.convert({"s.rpy": self.FIXTURE}, extra=["--no-cleartext"])
        self.assertNotIn("cleartext !", produced["main.scr"])

    def test_a_conditional_option_is_flagged(self):
        self.convert({"s.rpy": (
            "menu:\n"
            '    "Always" if flag:\n'
            '        "Shown."\n'
            '    "Other":\n'
            '        "Also shown."\n')})
        self.assertIn("cannot be conditional", self.report_for("s.scr"))


class ReportingTests(ConverterTestCase):
    def test_an_if_is_translated_and_closed(self):
        produced = self.convert({"s.rpy": (
            "label start:\n"
            "    if flag == 1:\n"
            '        "Yes."\n')})
        lines = self.lines_of(produced["main.scr"])
        self.assertIn("if flag == 1", lines)
        self.assertIn("fi", lines)
        self.assertLess(lines.index("if flag == 1"), lines.index("fi"))

    def test_a_python_condition_is_flagged_not_guessed(self):
        self.convert({"s.rpy": "if flag and other:\n    \"Hi.\"\n"})
        self.assertIn("compares one variable to a number", self.report_for("s.scr"))

    def test_else_is_reported(self):
        self.convert({"s.rpy": "if flag == 1:\n    \"A.\"\nelse:\n    \"B.\"\n"})
        self.assertIn("no else", self.report_for("s.scr"))

    def test_python_blocks_and_ui_are_skipped_by_name(self):
        self.convert({"s.rpy": (
            "init python:\n"
            "    x = 1\n"
            "image bg room = \"room.png\"\n"
            "transform slide:\n"
            "    xpos 0\n")})
        report = self.report_for("s.scr")
        self.assertIn("skipped statements: 2", report)
        self.assertIn("image declarations", report)
        self.assertIn("has no VNDS equivalent", report)

    def test_a_clean_file_reports_no_attention_needed(self):
        self.convert({"s.rpy": 'label start:\n    "Just dialogue."\n'})
        self.assertIn("none, the whole file converted", self.report_for("main.scr"))

    def test_exit_code_is_two_when_attention_is_needed(self):
        self.convert({"s.rpy": "label start:\n    call chapter\n"})
        self.assertEqual(self.last_code, 2)

    def test_allow_lossy_returns_zero(self):
        self.convert({"s.rpy": "label start:\n    call chapter\n"},
                     extra=["--allow-lossy"])
        self.assertEqual(self.last_code, 0)

    def test_a_clean_conversion_returns_zero(self):
        self.convert({"s.rpy": 'label start:\n    "Fine."\n'})
        self.assertEqual(self.last_code, 0)


class AssetMatchTests(ConverterTestCase):
    def setUp(self):
        super().setUp()
        self.assets = os.path.join(self.work, "assets", "foreground")
        write(os.path.join(self.assets, "eileenhappy.png"), "not really a png")
        write(os.path.join(self.work, "assets", "background", "bgroom.png"), "x")

    def test_a_matching_file_name_is_used_as_is(self):
        produced = self.convert({"s.rpy": "show eileen happy\n"},
                                extra=["-a", os.path.join(self.work, "assets")])
        self.assertIn("setimg eileenhappy.png", produced["s.scr"])

    def test_a_missing_asset_is_reported(self):
        self.convert({"s.rpy": "show nobody here\n"},
                     extra=["-a", os.path.join(self.work, "assets")])
        self.assertIn("no sprite file matches", self.report_for("s.scr"))

    def test_a_name_with_different_spacing_still_matches(self):
        write(os.path.join(self.work, "assets", "foreground", "eileen_sad.png"), "x")
        produced = self.convert({"s.rpy": "show eileen sad\n"},
                                extra=["-a", os.path.join(self.work, "assets")])
        self.assertIn("setimg eileen_sad.png", produced["s.scr"])


class SourceFormatTests(ConverterTestCase):
    def test_comments_are_stripped_before_parsing(self):
        produced = self.convert({"s.rpy": (
            "# a note at the top\n"
            'label start:   # trailing note\n'
            '    "Text with a # inside."  # and a note\n')})
        lines = self.lines_of(produced["main.scr"])
        self.assertEqual(lines[0], "label start")
        self.assertEqual(lines[1], 'text "Text with a # inside."')

    def test_runs_of_blank_lines_are_ignored(self):
        produced = self.convert({"s.rpy": '\n\n\n"Once."\n\n\n'})
        self.assertEqual(self.lines_of(produced["s.scr"]),
                         ['text "Once."', "text ~"])

    def test_indentation_defines_blocks(self):
        produced = self.convert({"s.rpy": (
            "label start:\n"
            "    if flag == 1:\n"
            '        "Nested."\n'
            '    "After the block."\n')})
        lines = self.lines_of(produced["main.scr"])
        self.assertEqual(lines, [
            "label start",
            "if flag == 1",
            'text "Nested."',
            "text ~",
            "fi",
            'text "After the block."',
            "text ~",
        ])


class NameCollisionTests(ConverterTestCase):
    """A game split across several script.rpy files must not lose any of them."""

    def test_two_files_with_one_basename_both_survive(self):
        # The first file becomes main.scr, which frees the name for the second,
        # so no collision arises and nothing is lost.
        produced = self.convert({
            "chapter1/script.rpy": 'label start:\n    "One."\n',
            "chapter2/script.rpy": 'label two:\n    "Two."\n',
        })
        self.assertEqual(sorted(produced), ["main.scr", "script.scr"])
        self.assertIn("One.", produced["main.scr"])
        self.assertIn("Two.", produced["script.scr"])

    def test_a_real_collision_is_renamed_and_explained(self):
        # Neither file holds the main label, so both want script.scr.
        produced = self.convert({
            "chapter1/script.rpy": 'label one:\n    "One."\n',
            "chapter2/script.rpy": 'label two:\n    "Two."\n',
        })
        self.assertEqual(sorted(produced), ["chapter2_script.scr", "script.scr"])
        self.assertIn("One.", produced["script.scr"])
        self.assertIn("Two.", produced["chapter2_script.scr"])
        self.assertIn("already writes script.scr",
                      self.report_for("chapter2_script.scr"))

    def test_a_cross_file_jump_uses_the_renamed_target(self):
        produced = self.convert({
            "a/script.rpy": 'label start:\n    jump three\n',
            "b/script.rpy": 'label two:\n    "Two."\n',
            "c/script.rpy": 'label three:\n    "Three."\n',
        })
        # b keeps script.scr, c is pushed to c_script.scr, and the jump follows.
        self.assertEqual(sorted(produced),
                         ["c_script.scr", "main.scr", "script.scr"])
        self.assertIn("jump c_script.scr three", produced["main.scr"])

    def test_two_start_labels_are_flagged(self):
        produced = self.convert({
            "a/script.rpy": 'label start:\n    "One."\n',
            "b/script.rpy": 'label start:\n    "Two."\n',
        })
        self.assertEqual(sorted(produced), ["main.scr", "script.scr"])
        self.assertIn("only one file can be main.scr",
                      self.report_for("script.scr"))


class ProjectScopeTests(ConverterTestCase):
    """Names Ren'Py defines once for the whole project, not per file."""

    def test_a_speaker_defined_in_another_file_is_known(self):
        produced = self.convert({
            "definitions.rpy": 'define lake = Character("Lake")\n',
            "day1.rpy": 'label one:\n    lake "Morning."\n',
        })
        self.assertIn('text Lake "Morning."', produced["day1.scr"])
        self.assertNotIn("no Character() definition", self.report_for("day1.scr"))

    def test_an_image_block_resolves_to_its_file(self):
        produced = self.convert({
            "images.rpy": ('image lake neutral:\n'
                           '    "images/sprites/lake/lake neutral.webp"\n'),
            "day1.rpy": "label one:\n    show lake neutral\n",
        })
        self.assertIn("setimg lakeneutral.png 78 27", produced["day1.scr"])

    def test_an_image_assignment_resolves_too(self):
        produced = self.convert({
            "images.rpy": 'image werewolf = "images/sprites/misc/werewolf.webp"\n',
            "day1.rpy": "label one:\n    scene werewolf\n",
        })
        self.assertIn("bgload werewolf.png", produced["day1.scr"])

    def test_an_image_expression_also_yields_a_path(self):
        produced = self.convert({
            "images.rpy": 'image gallery = im.Scale("gui/overlay/gallery idle.png", 20, 20)\n',
            "day1.rpy": "label one:\n    show gallery\n",
        })
        self.assertIn("setimg galleryidle.png", produced["day1.scr"])

    def test_trailing_attributes_fall_back_to_the_base_image(self):
        produced = self.convert({
            "images.rpy": ('image lake neutral:\n'
                           '    "images/sprites/lake/lake neutral.webp"\n'),
            "day1.rpy": "label one:\n    show lake neutral blush\n",
        })
        self.assertIn("setimg lakeneutral.png", produced["day1.scr"])

    def test_an_audio_alias_resolves_to_its_file(self):
        produced = self.convert({
            "audio.rpy": 'define audio.applause = "audio/applause.ogg"\n',
            "day1.rpy": "label one:\n    play sound applause\n",
        })
        self.assertIn("sound applause.mp3", produced["day1.scr"])

    def test_an_alias_filename_gets_its_spaces_stripped_like_the_audio_stage(self):
        produced = self.convert({
            "audio.rpy": 'define audio.rain = "audio/music/rainy weather.ogg"\n',
            "day1.rpy": "label one:\n    play music rain\n",
        })
        self.assertIn("music rainyweather.mp3", produced["day1.scr"])

    def test_an_alias_survives_the_audio_dot_prefix(self):
        produced = self.convert({
            "audio.rpy": 'define audio.applause = "audio/applause.ogg"\n',
            "day1.rpy": "label one:\n    play sound audio.applause\n",
        })
        self.assertIn("sound applause.mp3", produced["day1.scr"])


class ModernSyntaxTests(ConverterTestCase):
    """Shapes a real Ren'Py 7 or 8 script uses that older code did not."""

    def test_say_lines_with_at_attributes(self):
        produced = self.convert({
            "s.rpy": 'define rune = Character("Rune")\nrune @ smile "Hello."\n'})
        self.assertIn('text Rune "Hello."', produced["s.scr"])

    def test_say_lines_with_hyphenated_attributes(self):
        produced = self.convert({
            "s.rpy": 'define mikko = Character("Mikko")\nmikko serious arms-sides "Hi."\n'})
        self.assertIn('text Mikko "Hi."', produced["s.scr"])

    def test_say_lines_with_a_leading_hyphen_attribute(self):
        produced = self.convert({
            "s.rpy": 'define lake = Character("Lake")\nlake -blush meek "Oh."\n'})
        self.assertIn('text Lake "Oh."', produced["s.scr"])

    def test_text_tags_are_stripped(self):
        produced = self.convert({"s.rpy": '"A {i}quiet{/i} room."\n'})
        self.assertIn('text "A quiet room."', produced["s.scr"])

    def test_a_wait_tag_is_stripped_too(self):
        produced = self.convert({"s.rpy": '"Oh... {w=0.3}sure."\n'})
        self.assertIn('text "Oh... sure."', produced["s.scr"])

    def test_keep_tags_leaves_them_in_place(self):
        produced = self.convert({"s.rpy": '"A {i}quiet{/i} room."\n'},
                                extra=["--keep-tags"])
        self.assertIn('text "A {i}quiet{/i} room."', produced["s.scr"])

    def test_interpolation_becomes_a_dollar_variable(self):
        produced = self.convert({"s.rpy": '"Hello [name]."\n'})
        self.assertIn('text "Hello $name."', produced["s.scr"])

    def test_interpolation_running_into_a_word_is_braced(self):
        produced = self.convert({"s.rpy": '"[name]says hi."\n'})
        self.assertIn('text "{$name}says hi."', produced["s.scr"])

    def test_a_pause_call_becomes_a_delay(self):
        produced = self.convert({"s.rpy": "pause(2.0)\n"})
        self.assertEqual(self.lines_of(produced["s.scr"]), ["delay 120"])

    def test_a_standalone_transition_is_only_cosmetic(self):
        self.convert({"s.rpy": ("label start:\n    scene bg room\n"
                                "    with Dissolve(3.0)\n")})
        report = self.report_for("main.scr")
        self.assertIn("transitions skipped", report)
        self.assertIn("none, the whole file converted", report)

    def test_a_call_with_a_from_clause(self):
        produced = self.convert({
            "s.rpy": "label start:\n    call chapter from _call_chapter_1\n"})
        self.assertIn("goto chapter", produced["main.scr"])

    def test_a_custom_channel_is_mapped_and_flagged_once(self):
        produced = self.convert({"s.rpy": (
            'play nature "birds.ogg"\n'
            'play nature "wind.ogg"\n')})
        self.assertEqual(self.lines_of(produced["s.scr"]),
                         ["sound birds.mp3", "sound wind.mp3"])
        report = self.report_for("s.scr")
        self.assertIn("custom audio channel", report)
        self.assertEqual(report.count("custom audio channel"), 1)

    def test_stop_with_a_fadeout_clause_still_stops(self):
        produced = self.convert({"s.rpy": "stop music fadeout 3.0\n"})
        self.assertEqual(self.lines_of(produced["s.scr"]), ["music ~"])

    def test_a_play_with_fadein_is_understood(self):
        produced = self.convert({"s.rpy": 'play music "theme.mp3" fadein 2.0\n'})
        self.assertEqual(self.lines_of(produced["s.scr"]), ["music theme.mp3"])


class RealGameTests(ConverterTestCase):
    """Shapes that only turned up when pointing this at a real game."""

    def test_a_narrator_character_prints_no_name(self):
        produced = self.convert({
            "s.rpy": 'define nvl_n = Character(None, kind=nvl)\nnvl_n "It rained."\n'})
        self.assertIn('text "It rained."', produced["s.scr"])
        self.assertNotIn("no Character() definition", self.report_for("s.scr"))

    def test_a_speaker_name_with_interpolation_is_converted(self):
        produced = self.convert({
            "s.rpy": 'define mc = Character("[player_name]")\nmc "Hello."\n'})
        self.assertIn('text $player_name "Hello."', produced["s.scr"])

    def test_extend_becomes_its_own_line(self):
        produced = self.convert({"s.rpy": (
            '"First part."\n'
            'extend " and the rest."\n')})
        self.assertIn('text "and the rest."', produced["s.scr"])
        self.assertIn("extend lines", self.report_for("s.scr"))

    def test_a_layered_sprite_is_reported_once_and_not_drawn(self):
        produced = self.convert({
            "images.rpy": ('layeredimage lake:\n'
                           '    always "lake_body_sfw"\n'
                           '    group face:\n'
                           '        attribute neutral "lake_face_neutral"\n'),
            "day1.rpy": ("label one:\n"
                         "    show lake neutral\n"
                         "    show lake neutral\n"
                         "    show lake smile\n"),
        })
        self.assertNotIn("setimg", produced["day1.scr"])
        report = self.report_for("day1.scr")
        # Counted per line in the report, explained once on stderr for the run.
        self.assertIn("3  layered sprites skipped", report)
        self.assertIn("none, the whole file converted", report)

    def test_a_playlist_uses_the_first_track_and_says_so(self):
        produced = self.convert({"s.rpy": (
            'play music ["theme.mp3", "other.mp3"] fadein 1.0\n')})
        self.assertEqual(self.lines_of(produced["s.scr"]), ["music theme.mp3"])
        self.assertIn("playlist", self.report_for("s.scr"))

    def test_a_built_in_silence_file_is_not_referenced(self):
        produced = self.convert({"s.rpy": 'play music "<silence1.mp3>"\n'})
        self.assertEqual(self.lines_of(produced["s.scr"]), [])
        self.assertIn("built-in Ren'Py file", self.report_for("s.scr"))

    def test_a_filename_containing_fadein_is_not_treated_as_a_clause(self):
        produced = self.convert({"s.rpy": 'play music "dinnertime fadein (1).ogg"\n'})
        self.assertEqual(self.lines_of(produced["s.scr"]),
                         ["music dinnertimefadein(1).mp3"])

    def test_an_undeclared_image_falls_back_to_a_matching_file(self):
        write(os.path.join(self.work, "assets", "foreground", "lake neutral.png"), "x")
        produced = self.convert({"s.rpy": "show lake\n"},
                                extra=["-a", os.path.join(self.work, "assets")])
        self.assertIn("setimg lakeneutral.png", produced["s.scr"])
        self.assertIn("is not declared anywhere", self.report_for("s.scr"))


    def test_a_flattened_layered_sprite_is_used(self):
        write(os.path.join(self.work, "assets", "foreground", "lakeneutral.png"), "x")
        produced = self.convert({
            "images.rpy": ('layeredimage lake:\n'
                           '    always "lake_body_sfw"\n'
                           '    group face:\n'
                           '        attribute neutral "lake_face_neutral"\n'),
            "day1.rpy": "label one:\n    show lake neutral\n",
        }, extra=["-a", os.path.join(self.work, "assets")])
        self.assertIn("setimg lakeneutral.png 78 27", produced["day1.scr"])
        self.assertIn("layered sprites flattened",
                      self.report_for("day1.scr"))

    def test_a_displayable_is_not_mistaken_for_a_file(self):
        produced = self.convert({"s.rpy": (
            'show text "drowned in noise" as text4\n')})
        self.assertEqual(self.lines_of(produced["s.scr"]), [])
        self.assertIn("builds an image in code", self.report_for("s.scr"))


    def test_a_python_expression_is_not_written_as_a_setvar(self):
        produced = self.convert({"s.rpy": (
            "$ name = renpy.input('Your name?').strip()\n")})
        self.assertEqual(self.lines_of(produced["s.scr"]), [])
        self.assertIn("is not a value setvar can hold", self.report_for("s.scr"))

    def test_a_literal_value_still_becomes_a_setvar(self):
        produced = self.convert({"s.rpy": '$ name = "Arvo"\n$ count = 3\n'})
        self.assertEqual(self.lines_of(produced["s.scr"]),
                         ['setvar name = "Arvo"', "setvar count = 3"])

    def test_the_entry_label_is_moved_to_the_top_of_main_scr(self):
        produced = self.convert({"script.rpy": (
            "label helper:\n"
            '    "Not the entry point."\n'
            "label start:\n"
            '    "The game begins here."\n'
            "label later:\n"
            '    "Afterwards."\n')})
        lines = self.lines_of(produced["main.scr"])
        self.assertEqual(lines[0], "label start")
        self.assertEqual(lines[1], 'text "The game begins here."')
        self.assertIn("label helper", lines)
        self.assertIn("label later", lines)


if __name__ == "__main__":
    unittest.main(verbosity=2)
