"""
Prompt loading.

Prompts live in `prompts/*.md` at the repository root rather than inline in
Python. They are the part of this system most likely to change, most likely to
change behaviour when they do, and least readable buried in a source file. As
files they can be reviewed, diffed and versioned like anything else, and the
evaluation suite can attribute a change in accuracy to a change in a prompt.

Substitution is deliberately dumb: a literal replace of {{PLACEHOLDER}}
tokens. str.format and string.Template both assign meaning to characters that
appear naturally in these prompts - braces in JSON-ish examples, percent signs
in STRFTIME format strings, dollars in currency. A plain replace has no syntax
to collide with, which matters when the text being substituted is user input.
"""

from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

from ..core.paths import BASE_DIR


def _resolve_prompts_dir() -> Path:
    """
    Locate the prompts directory across both layouts, as with the frontend:
    /app/prompts in the container, <repo>/prompts locally.
    """
    candidates = [BASE_DIR / "prompts", BASE_DIR.parent / "prompts"]
    for candidate in candidates:
        if candidate.is_dir():
            return candidate
    return candidates[0]


PROMPTS_DIR = _resolve_prompts_dir()


def _strip_front_matter(text: str) -> str:
    """
    Remove the YAML front matter block used to record prompt metadata.

    The metadata is for humans and for the changelog; the model should never
    see it. Front matter is only stripped when the file actually opens with a
    delimiter, so a prompt without one is passed through untouched.
    """
    if not text.startswith("---"):
        return text
    parts = text.split("---", 2)
    if len(parts) < 3:
        return text
    return parts[2].lstrip("\n")


@lru_cache(maxsize=None)
def load_prompt(name: str) -> str:
    """
    Read a prompt by name, without its front matter.

    Trailing whitespace is preserved. It mattered under the text-generation
    API, where the SQL prompt's final newline told the model to start a new
    line with SQL on it - stripping it once took the suite from 89% to 11%.
    The chat API wraps each message in the model's own template, so it no
    longer matters, but there is no reason to alter what the file says.

    Cached: prompts do not change while the process runs, and re-reading a file
    on every request would put disk I/O in the path of every question.
    """
    path = PROMPTS_DIR / f"{name}.md"
    return _strip_front_matter(path.read_text(encoding="utf-8")).lstrip("\n")


@lru_cache(maxsize=None)
def prompt_meta(name: str) -> dict[str, str]:
    """
    The simple "key: value" lines of a prompt's front matter - in practice its
    name, version and date, which the evaluation suite records with each run
    so a change in accuracy can be traced to a change in a prompt.
    """
    text = (PROMPTS_DIR / f"{name}.md").read_text(encoding="utf-8")
    if not text.startswith("---"):
        return {}
    meta: dict[str, str] = {}
    for line in text.split("---", 2)[1].splitlines():
        match = re.match(r"^([a-z_]+):\s*(\S.*)$", line)
        if match:
            meta[match.group(1)] = match.group(2).strip()
    return meta


_PLACEHOLDER = re.compile(r"\{\{([A-Z_]+)\}\}")
_ROLE_MARKER = re.compile(r"<!--\s*role:\s*(system|user|assistant)\s*-->")


def _substitute(name: str, template: str, values: dict[str, str]) -> str:
    """
    Fill {{PLACEHOLDER}} tokens in one pass over the template.

    The check for unfilled placeholders is made against the template, not the
    result. Checking the result made any question containing a brace fail,
    because the user's own text was mistaken for an unfilled placeholder. One
    pass also means a value is never itself scanned for placeholders, so text
    a user types cannot pull another value into the prompt.
    """
    missing = sorted(set(_PLACEHOLDER.findall(template)) - set(values))
    if missing:
        raise ValueError(f"Unsubstituted placeholder in prompt '{name}': {missing}")
    return _PLACEHOLDER.sub(lambda match: values[match.group(1)], template)


def render(name: str, **values: str) -> str:
    """
    Load a prompt and substitute {{PLACEHOLDER}} tokens.

    Raises if a placeholder is left unsubstituted. A prompt silently sent to a
    model with a literal {{USER_QUERY}} in it is a bug that produces confident
    nonsense rather than an error, so it is worth failing loudly instead.
    """
    return _substitute(name, load_prompt(name), values)


def render_messages(name: str, **values: str) -> list[tuple[str, str]]:
    """
    Load a prompt as chat messages: a list of (role, text) pairs.

    A prompt marks where each message starts with an HTML comment such as
    <!-- role: system -->, which keeps the file readable as Markdown. A prompt
    with no markers is sent as a single user message.

    The prompt is split into messages before values are substituted, so a
    question containing a role marker stays text inside its own message and
    can never start a new one.
    """
    body = load_prompt(name)
    pieces = _ROLE_MARKER.split(body)

    # split() with one capture group gives [preamble, role, text, role, text...]
    messages: list[tuple[str, str]] = []
    if pieces[0].strip():
        messages.append(("user", pieces[0]))
    for role, text in zip(pieces[1::2], pieces[2::2]):
        messages.append((role, text))

    if not messages:
        raise ValueError(f"Prompt '{name}' is empty")

    # Placeholders are checked across the whole prompt, so a value supplied
    # for one message is not reported missing from another.
    missing = sorted(set(_PLACEHOLDER.findall(body)) - set(values))
    if missing:
        raise ValueError(f"Unsubstituted placeholder in prompt '{name}': {missing}")

    return [(role, _substitute(name, text, values).strip()) for role, text in messages]
