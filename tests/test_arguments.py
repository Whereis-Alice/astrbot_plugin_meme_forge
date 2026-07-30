from __future__ import annotations

import unittest

from astrbot_plugin_meme_forge.core.arguments import (
    MemeArgumentParser,
    option_specs_from_params,
)


class ParserFlags:
    def __init__(
        self,
        *,
        short: bool = False,
        long: bool = True,
        short_aliases: list[str] | None = None,
        long_aliases: list[str] | None = None,
    ):
        self.short = short
        self.long = long
        self.short_aliases = short_aliases or []
        self.long_aliases = long_aliases or []


class StringOption:
    def __init__(
        self,
        name: str,
        *,
        default: str | None = None,
        choices: list[str] | None = None,
        flags: ParserFlags | None = None,
    ):
        self.name = name
        self.default = default
        self.choices = choices
        self.description = None
        self.parser_flags = flags or ParserFlags()


class BooleanOption:
    def __init__(self, name: str, alias: str):
        self.name = name
        self.default = False
        self.description = None
        self.parser_flags = ParserFlags(long_aliases=[alias])


class IntegerOption:
    def __init__(self, name: str, minimum: int, maximum: int):
        self.name = name
        self.default = minimum
        self.minimum = minimum
        self.maximum = maximum
        self.description = None
        self.parser_flags = ParserFlags()


class Params:
    def __init__(self, options: list[object]):
        self.options = options


def bubble_tea_parser() -> MemeArgumentParser:
    params = Params(
        [
            StringOption(
                "position",
                default="right",
                choices=["left", "right", "both"],
                flags=ParserFlags(short=True),
            ),
            BooleanOption("left", "左手"),
            BooleanOption("right", "右手"),
            BooleanOption("both", "双手"),
        ]
    )
    return MemeArgumentParser(option_specs_from_params(params))


class MemeArgumentParserTests(unittest.TestCase):
    def test_natural_boolean_alias(self) -> None:
        parsed = bubble_tea_parser().parse("左手")
        self.assertEqual(parsed.options, {"left": True})
        self.assertEqual(parsed.texts, [])
        self.assertEqual(parsed.errors, [])

    def test_choice_key_value_and_cli_forms(self) -> None:
        parser = bubble_tea_parser()
        self.assertEqual(parser.parse("position=left").options, {"position": "left"})
        self.assertEqual(
            parser.parse("--position both").options,
            {"position": "both"},
        )
        self.assertEqual(parser.parse("-p right").options, {"position": "right"})

    def test_boolean_false_and_no_prefix(self) -> None:
        parser = bubble_tea_parser()
        self.assertEqual(parser.parse("--left=false").options, {"left": False})
        self.assertEqual(parser.parse("--no-left").options, {"left": False})

    def test_quoted_text_and_qq_target(self) -> None:
        parsed = bubble_tea_parser().parse('"今天 放假" @114514')
        self.assertEqual(parsed.texts, ["今天 放假"])
        self.assertEqual(parsed.target_ids, ["114514"])

    def test_invalid_range_and_unknown_option_are_reported(self) -> None:
        parser = MemeArgumentParser(
            option_specs_from_params(Params([IntegerOption("count", 1, 3)]))
        )
        parsed = parser.parse("count=9 --missing value")
        self.assertEqual(len(parsed.errors), 2)
        self.assertIn("不能大于 3", parsed.errors[0])
        self.assertIn("未知参数", parsed.errors[1])


if __name__ == "__main__":
    unittest.main()
