"""Typed views over the extras sections of Watson's config file."""

from __future__ import annotations

import datetime
import re
from dataclasses import dataclass

from ..config import ConfigParser


class SettingsError(Exception):
    """An extras config value is missing or malformed."""


_DURATION_RE = re.compile(r"^([+-])?((?:\d+[dhms])+)$")
_DURATION_PART_RE = re.compile(r"(\d+)([dhms])")
_UNITS = {"d": "days", "h": "hours", "m": "minutes", "s": "seconds"}


def parse_duration(value: str, *, signed: bool = False) -> datetime.timedelta:
    """Parse ``90m``, ``1h30m``, ``2d`` ... into a timedelta.

    With ``signed``, a leading ``+`` or ``-`` is allowed (for handler
    offsets such as ``-15m``).
    """
    text = value.strip().lower()
    match = _DURATION_RE.match(text)
    if not match or (match.group(1) and not signed):
        raise SettingsError(
            f"invalid duration '{value}'; use e.g. 90m, 1h30m or 2d"
            + (" (optionally signed, e.g. -15m)" if signed else "")
        )
    delta = datetime.timedelta()
    for amount, unit in _DURATION_PART_RE.findall(match.group(2)):
        delta += datetime.timedelta(**{_UNITS[unit]: int(amount)})
    return -delta if match.group(1) == "-" else delta


def format_duration(delta: datetime.timedelta) -> str:
    """Render a timedelta as ``1h30m`` (minutes resolution)."""
    total = int(abs(delta.total_seconds()) // 60)
    hours, minutes = divmod(total, 60)
    sign = "-" if delta.total_seconds() < 0 else ""
    if hours and minutes:
        return f"{sign}{hours}h{minutes:02d}m"
    if hours:
        return f"{sign}{hours}h"
    return f"{sign}{minutes}m"


@dataclass(frozen=True)
class ReminderSettings:
    enabled: bool
    grace: datetime.timedelta
    repeat: datetime.timedelta


@dataclass(frozen=True)
class HandlerSpec:
    name: str  # "toast" | "autostop" | "prompt"
    offset: datetime.timedelta
    index: int


@dataclass(frozen=True)
class Policy:
    name: str
    trigger: str  # "elapsed" | "offhours"
    after: datetime.timedelta
    stop_at: str  # "onset" | "fire"
    handlers: tuple[HandlerSpec, ...]


HANDLER_NAMES = ("toast", "autostop", "prompt")
TRIGGERS = ("elapsed", "offhours")
POLICY_PREFIX = "policy:"


def _get_duration(config, section, option, default, *, signed=False):
    raw = config.get(section, option)
    if raw is None or not raw.strip():
        return default
    try:
        return parse_duration(raw, signed=signed)
    except SettingsError as e:
        raise SettingsError(f"[{section}] {option}: {e}") from None


def reminder_settings(config: ConfigParser) -> ReminderSettings:
    return ReminderSettings(
        enabled=config.getboolean("reminder", "enabled", True),
        grace=_get_duration(
            config, "reminder", "grace", datetime.timedelta(minutes=10)
        ),
        repeat=_get_duration(
            config, "reminder", "repeat", datetime.timedelta(minutes=30)
        ),
    )


def poll_interval(config: ConfigParser) -> datetime.timedelta:
    return _get_duration(
        config, "extras", "poll_interval", datetime.timedelta(minutes=5)
    )


def notifier_name(config: ConfigParser) -> str:
    return (config.get("extras", "notifier", "auto") or "auto").strip().lower()


def remind_deferred(config: ConfigParser) -> bool:
    return config.getboolean("review", "remind_deferred", True)


def parse_handlers(section: str, raw: str) -> tuple[HandlerSpec, ...]:
    specs = []
    for index, token in enumerate(raw.split()):
        name, _, offset = token.partition("@")
        name = name.strip().lower()
        if name not in HANDLER_NAMES:
            raise SettingsError(
                f"[{section}] handlers: unknown handler '{name}' "
                f"(expected one of {', '.join(HANDLER_NAMES)})"
            )
        try:
            delta = (
                parse_duration(offset, signed=True) if offset else datetime.timedelta()
            )
        except SettingsError as e:
            raise SettingsError(f"[{section}] handlers: {e}") from None
        specs.append(HandlerSpec(name=name, offset=delta, index=index))
    if not specs:
        raise SettingsError(f"[{section}] handlers: at least one handler is required")
    return tuple(specs)


def load_policies(config: ConfigParser) -> list[Policy]:
    """Read every ``[policy:NAME]`` section."""
    policies = []
    for section in config.sections():
        if not section.startswith(POLICY_PREFIX):
            continue
        name = section[len(POLICY_PREFIX) :].strip()
        if not name:
            raise SettingsError(f"[{section}]: the policy needs a name")
        trigger = (config.get(section, "trigger") or "").strip().lower()
        if trigger not in TRIGGERS:
            raise SettingsError(
                f"[{section}] trigger: expected one of {', '.join(TRIGGERS)}"
            )
        after = _get_duration(config, section, "after", None)
        if after is None or after <= datetime.timedelta():
            raise SettingsError(f"[{section}] after: a positive duration is required")
        default_stop = "onset" if trigger == "offhours" else "fire"
        stop_at = (config.get(section, "stop_at") or default_stop).strip().lower()
        if stop_at not in ("onset", "fire"):
            raise SettingsError(f"[{section}] stop_at: expected 'onset' or 'fire'")
        if trigger == "elapsed" and stop_at == "onset":
            raise SettingsError(
                f"[{section}] stop_at: 'onset' is the frame start for elapsed "
                "policies, so it would erase the whole frame; use 'fire'"
            )
        handlers = parse_handlers(section, config.get(section, "handlers") or "")
        policies.append(
            Policy(
                name=name,
                trigger=trigger,
                after=after,
                stop_at=stop_at,
                handlers=handlers,
            )
        )
    return policies
