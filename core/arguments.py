from __future__ import annotations

import re
import shlex
from dataclasses import dataclass, field
from typing import Any, Literal

OptionKind = Literal["bool", "str", "int", "float"]
OptionValue = bool | str | int | float


@dataclass(frozen=True, slots=True)
class OptionSpec:
    name: str
    kind: OptionKind
    default: OptionValue | None = None
    choices: tuple[str, ...] = ()
    minimum: int | float | None = None
    maximum: int | float | None = None
    description: str | None = None
    bare_aliases: tuple[str, ...] = ()
    flag_aliases: tuple[str, ...] = ()


@dataclass(slots=True)
class ParsedArguments:
    texts: list[str] = field(default_factory=list)
    options: dict[str, OptionValue] = field(default_factory=dict)
    target_ids: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


def _option_kind(option: Any) -> OptionKind:
    class_name = type(option).__name__.lower()
    if "boolean" in class_name or class_name.startswith("bool"):
        return "bool"
    if "integer" in class_name or class_name.startswith("int"):
        return "int"
    if "float" in class_name:
        return "float"
    if "string" in class_name or class_name.startswith("str"):
        return "str"

    default = getattr(option, "default", None)
    if isinstance(default, bool):
        return "bool"
    if isinstance(default, int):
        return "int"
    if isinstance(default, float):
        return "float"
    return "str"


def option_specs_from_params(params: Any) -> list[OptionSpec]:
    specs: list[OptionSpec] = []
    for option in list(getattr(params, "options", []) or []):
        name = str(getattr(option, "name", "")).strip()
        if not name:
            continue

        flags = getattr(option, "parser_flags", None)
        short_aliases = tuple(
            str(value).strip()
            for value in (getattr(flags, "short_aliases", []) or [])
            if str(value).strip()
        )
        long_aliases = tuple(
            str(value).strip()
            for value in (getattr(flags, "long_aliases", []) or [])
            if str(value).strip()
        )

        flag_aliases = list(short_aliases + long_aliases)
        if bool(getattr(flags, "short", False)) and name:
            flag_aliases.append(name[0])
        if bool(getattr(flags, "long", False)):
            flag_aliases.append(name)

        specs.append(
            OptionSpec(
                name=name,
                kind=_option_kind(option),
                default=getattr(option, "default", None),
                choices=tuple(
                    str(value) for value in (getattr(option, "choices", None) or [])
                ),
                minimum=getattr(option, "minimum", None),
                maximum=getattr(option, "maximum", None),
                description=getattr(option, "description", None),
                bare_aliases=tuple(
                    dict.fromkeys((name, *short_aliases, *long_aliases))
                ),
                flag_aliases=tuple(dict.fromkeys((name, *flag_aliases))),
            )
        )
    return specs


def tokenize_arguments(text: str) -> list[str]:
    normalized = text.translate(str.maketrans({"“": '"', "”": '"', "‘": "'", "’": "'"}))
    lexer = shlex.shlex(normalized, posix=True)
    lexer.whitespace_split = True
    lexer.commenters = ""
    try:
        return list(lexer)
    except ValueError:
        return normalized.split()


def command_tail(message_str: Any) -> str:
    """返回一条指令消息里“指令名之后”的原始参数串。

    为什么不直接用 AstrBot 的形参注入：
    AstrBot 在 ``pipeline/process_stage/method/star_request.py`` 里通过
    ``call_handler(event, handler, **params)`` 调用指令处理器，也就是**只按关键字**传参；
    而 ``star/filter/command.py`` 的 ``init_handler_md`` 会把 ``self``、``event`` 之后的
    每一个形参都登记成具名参数——包括 ``*args``（VAR_POSITIONAL）。于是形如
    ``async def h(self, event, selector=None, *args)`` 的处理器会被调成
    ``h(event, selector=..., args=...)``，直接抛 ``TypeError``。

    此外 4.26.x 调 ``inspect.signature(handler)``、4.27.x 调
    ``inspect.signature(handler, eval_str=True)``；本插件启用了
    ``from __future__ import annotations``，注解在两个版本里分别是字符串与真实对象，
    因此 ``GreedyStr`` 之类的注解写法在跨版本时行为不一致。

    结论：所有指令处理器只声明 ``(self, event)``，参数一律从原始消息文本里取。
    这样在任何核心版本上 ``handler_params`` 都是空字典，既不会被关键字注入，
    也不会触发“必要参数缺失”，更不会被核心悄悄把纯数字转成 ``int``。
    """
    normalized = re.sub(r"\s+", " ", str(message_str or "").strip())
    if not normalized:
        return ""
    _, _, tail = normalized.partition(" ")
    return tail.strip()


def command_tokens(message_str: Any) -> tuple[str, ...]:
    """把 :func:`command_tail` 的结果按空格切成参数列表（丢弃空串）。"""
    tail = command_tail(message_str)
    if not tail:
        return ()
    return tuple(token for token in tail.split(" ") if token)


def strip_trigger_prefix(text: str, prefix: str) -> str | None:
    normalized = text.strip()
    prefix = prefix.strip()
    if not prefix:
        return normalized
    if not normalized.startswith(prefix):
        return None
    remainder = normalized[len(prefix) :]
    if remainder and prefix[-1].isalnum() and not remainder[0].isspace():
        return None
    return remainder.strip()


class MemeArgumentParser:
    def __init__(self, specs: list[OptionSpec]):
        self.specs = specs
        self._bare_map: dict[str, OptionSpec] = {}
        self._flag_map: dict[str, OptionSpec] = {}
        choice_candidates: dict[str, list[OptionSpec]] = {}

        for spec in specs:
            for alias in spec.bare_aliases:
                self._bare_map[self._normalize(alias)] = spec
            for alias in spec.flag_aliases:
                self._flag_map[self._normalize(alias)] = spec
            for choice in spec.choices:
                choice_candidates.setdefault(self._normalize(choice), []).append(spec)

        self._choice_map = {
            choice: candidates[0]
            for choice, candidates in choice_candidates.items()
            if len(candidates) == 1
        }

    @staticmethod
    def _normalize(value: str) -> str:
        return value.strip().lstrip("-").casefold()

    def _resolve(self, name: str, *, as_flag: bool) -> OptionSpec | None:
        normalized = self._normalize(name)
        mapping = self._flag_map if as_flag else self._bare_map
        return mapping.get(normalized)

    @staticmethod
    def _parse_bool(value: str) -> bool:
        normalized = value.strip().casefold()
        if normalized in {"1", "true", "yes", "on", "是", "开", "开启"}:
            return True
        if normalized in {"0", "false", "no", "off", "否", "关", "关闭"}:
            return False
        raise ValueError("应为 true/false、yes/no、on/off 或 1/0")

    @classmethod
    def _convert(cls, spec: OptionSpec, value: str) -> OptionValue:
        if spec.kind == "bool":
            converted: OptionValue = cls._parse_bool(value)
        elif spec.kind == "int":
            converted = int(value)
        elif spec.kind == "float":
            converted = float(value)
        else:
            converted = value

        if spec.choices and str(converted) not in spec.choices:
            raise ValueError(f"可选值为: {', '.join(spec.choices)}")
        if spec.minimum is not None and converted < spec.minimum:  # type: ignore[operator]
            raise ValueError(f"不能小于 {spec.minimum}")
        if spec.maximum is not None and converted > spec.maximum:  # type: ignore[operator]
            raise ValueError(f"不能大于 {spec.maximum}")
        return converted

    def _set_value(
        self,
        result: ParsedArguments,
        spec: OptionSpec,
        raw_value: str,
    ) -> None:
        try:
            result.options[spec.name] = self._convert(spec, raw_value)
        except (TypeError, ValueError) as exc:
            result.errors.append(f"参数 {spec.name} 的值 {raw_value!r} 无效: {exc}")

    def parse(self, text: str) -> ParsedArguments:
        result = ParsedArguments()
        tokens = tokenize_arguments(text)
        index = 0

        while index < len(tokens):
            token = tokens[index]

            bracket_mention = re.fullmatch(r"<@!?([^<>\s]+)>", token)
            if bracket_mention:
                result.target_ids.append(bracket_mention.group(1))
                index += 1
                continue

            if token.startswith("@") and token[1:].isdigit():
                result.target_ids.append(token[1:])
                index += 1
                continue

            if "=" in token:
                raw_name, raw_value = token.split("=", 1)
                spec = self._resolve(raw_name, as_flag=raw_name.startswith("-"))
                if spec is None:
                    result.errors.append(f"未知参数: {raw_name.lstrip('-')}")
                else:
                    self._set_value(result, spec, raw_value)
                index += 1
                continue

            if token.startswith("-"):
                normalized = token.lstrip("-")
                negated = normalized.casefold().startswith("no-")
                lookup = normalized[3:] if negated else normalized
                spec = self._resolve(lookup, as_flag=True)
                if spec is None:
                    result.errors.append(f"未知参数: {normalized}")
                    index += 1
                    continue
                if negated:
                    if spec.kind != "bool":
                        result.errors.append(f"参数 {spec.name} 不支持 --no- 写法")
                    else:
                        result.options[spec.name] = False
                    index += 1
                    continue
                if spec.kind == "bool":
                    result.options[spec.name] = True
                    index += 1
                    continue
                if index + 1 >= len(tokens):
                    result.errors.append(f"参数 {spec.name} 缺少值")
                    index += 1
                    continue
                self._set_value(result, spec, tokens[index + 1])
                index += 2
                continue

            spec = self._resolve(token, as_flag=False)
            if spec is not None:
                if spec.kind == "bool":
                    result.options[spec.name] = True
                    index += 1
                    continue
                if index + 1 >= len(tokens):
                    result.errors.append(f"参数 {spec.name} 缺少值")
                    index += 1
                    continue
                self._set_value(result, spec, tokens[index + 1])
                index += 2
                continue

            choice_spec = self._choice_map.get(self._normalize(token))
            if choice_spec is not None:
                self._set_value(result, choice_spec, token)
            else:
                result.texts.append(token)
            index += 1

        result.target_ids = list(dict.fromkeys(result.target_ids))
        return result


def format_option_spec(spec: OptionSpec) -> str:
    aliases = [alias for alias in spec.bare_aliases if alias != spec.name]
    details: list[str] = []
    if spec.choices:
        details.append("可选值: " + "/".join(spec.choices))
    if aliases:
        details.append("别名: " + "/".join(aliases))
    if spec.minimum is not None or spec.maximum is not None:
        minimum = spec.minimum if spec.minimum is not None else "-∞"
        maximum = spec.maximum if spec.maximum is not None else "+∞"
        details.append(f"范围: {minimum}~{maximum}")
    if spec.default is not None:
        details.append(f"默认: {spec.default}")
    suffix = f" ({'; '.join(details)})" if details else ""
    return f"{spec.name}{suffix}"
