"""Markdown persistence for the curses todo CLI.

Format:

    # Project Name

    - [ ] Buy groceries @prio:high @due:2026-05-20 +errands #shopping
      - [ ] Milk
      - [x] Bread
    - [x] Submit expense report @prio:med +work

One H1 heading per project. Subtasks indented by two spaces. Tags:

    @prio:<word>     priority
    @due:YYYY-MM-DD  due date
    +<word>          inline project tag (separate from the H1 project)
    #<word>          free-form tag
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

from .seed import Project, Todo, seed_projects


# ----------------------------------------------------------------- regexes
_TODO_LINE_RE = re.compile(r"^(?P<indent>\s*)- \[(?P<box>[ xX])\] (?P<rest>.*)$")
_HEADING_RE = re.compile(r"^#\s+(?P<name>.+?)\s*$")
_PRIO_RE = re.compile(r"(?:^|\s)@prio:(\S+)")
_DUE_RE = re.compile(r"(?:^|\s)@due:(\S+)")
_PROJECT_TAG_RE = re.compile(r"(?:^|\s)\+(\S+)")
_HASH_TAG_RE = re.compile(r"(?:^|\s)#(\S+)")


# ----------------------------------------------------------------- types
@dataclass
class ParsedTodo:
    """Result of parsing one input line into its components."""
    label: str
    priority: Optional[str] = None
    due: Optional[str] = None
    project_tag: Optional[str] = None
    tags: List[str] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.tags is None:
            self.tags = []


# ----------------------------------------------------------------- parsing
def parse_input_line(text: str) -> ParsedTodo:
    """Split a free-form line into (label, priority, due, project_tag, tags).

    Tag tokens are stripped from the label. Tag order in the label is not
    preserved (re-emitted canonically by `format_input_line`).
    """
    prio_m = _PRIO_RE.search(text)
    due_m = _DUE_RE.search(text)
    proj_m = _PROJECT_TAG_RE.search(text)
    tags = _HASH_TAG_RE.findall(text)

    stripped = text
    stripped = _PRIO_RE.sub("", stripped)
    stripped = _DUE_RE.sub("", stripped)
    stripped = _PROJECT_TAG_RE.sub("", stripped)
    stripped = _HASH_TAG_RE.sub("", stripped)
    label = re.sub(r"\s+", " ", stripped).strip()

    return ParsedTodo(
        label=label,
        priority=prio_m.group(1) if prio_m else None,
        due=due_m.group(1) if due_m else None,
        project_tag=proj_m.group(1) if proj_m else None,
        tags=tags,
    )


def format_input_line(todo: Todo) -> str:
    """Canonical string form of a todo for re-editing: label + tags in order."""
    parts: List[str] = [todo.label] if todo.label else []
    if todo.priority:
        parts.append(f"@prio:{todo.priority}")
    if todo.due:
        parts.append(f"@due:{todo.due}")
    if todo.project_tag:
        parts.append(f"+{todo.project_tag}")
    for tag in todo.tags:
        parts.append(f"#{tag}")
    return " ".join(parts)


def apply_parsed(todo: Todo, parsed: ParsedTodo) -> None:
    """Overwrite metadata on `todo` from a `ParsedTodo`."""
    todo.label = parsed.label
    todo.priority = parsed.priority
    todo.due = parsed.due
    todo.project_tag = parsed.project_tag
    todo.tags = list(parsed.tags)


def new_todo_from_text(text: str) -> Todo:
    """Build a fresh `Todo` from a free-form line."""
    parsed = parse_input_line(text)
    return Todo(
        label=parsed.label,
        priority=parsed.priority,
        due=parsed.due,
        project_tag=parsed.project_tag,
        tags=list(parsed.tags),
    )


# ----------------------------------------------------------------- file I/O
def _format_todo_md(todo: Todo, indent: int) -> str:
    box = "[x]" if todo.done else "[ ]"
    pad = " " * indent
    suffix = format_input_line(todo)
    # `format_input_line` includes the label as the first token; reuse it
    # directly so we don't double-render label.
    return f"{pad}- {box} {suffix}".rstrip()


def serialize(projects: List[Project]) -> str:
    lines: List[str] = []
    for i, project in enumerate(projects):
        if i > 0:
            lines.append("")
        lines.append(f"# {project.name}")
        lines.append("")
        for top in project.todos:
            lines.append(_format_todo_md(top, indent=0))
            for sub in top.subtasks:
                lines.append(_format_todo_md(sub, indent=2))
    return "\n".join(lines) + "\n"


def _parse_todo_from_match(match: re.Match) -> Todo:
    rest = match.group("rest")
    parsed = parse_input_line(rest)
    todo = Todo(
        label=parsed.label,
        done=(match.group("box").lower() == "x"),
        priority=parsed.priority,
        due=parsed.due,
        project_tag=parsed.project_tag,
        tags=list(parsed.tags),
    )
    return todo


def parse(text: str) -> List[Project]:
    """Parse markdown text into a list of Projects.

    - Each `# Heading` starts a new project.
    - Lines matching `- [ ]` / `- [x]` are todos. Indent >= 2 spaces => subtask
      of the most recent top-level todo in the current project. Anything
      deeper is flattened to that same single subtask level (spec only models
      one level of nesting).
    - Todo lines before the first heading are placed in an implicit "Inbox"
      project (only if any exist).
    """
    projects: List[Project] = []
    current: Optional[Project] = None
    last_top: Optional[Todo] = None

    for raw_line in text.splitlines():
        heading_m = _HEADING_RE.match(raw_line)
        if heading_m:
            current = Project(name=heading_m.group("name").strip())
            projects.append(current)
            last_top = None
            continue

        todo_m = _TODO_LINE_RE.match(raw_line)
        if not todo_m:
            continue

        if current is None:
            current = Project(name="Inbox")
            projects.append(current)
            last_top = None

        todo = _parse_todo_from_match(todo_m)
        indent_len = len(todo_m.group("indent").expandtabs(4))
        if indent_len >= 2 and last_top is not None:
            last_top.subtasks.append(todo)
        else:
            current.todos.append(todo)
            last_top = todo

    return projects


def load(path: Path) -> List[Project]:
    """Load projects from `path`. If missing/empty, returns the seed and
    writes it to disk so the user has a starter file to inspect."""
    if not path.exists():
        projects = seed_projects()
        save(path, projects)
        return projects
    text = path.read_text(encoding="utf-8")
    projects = parse(text)
    if not projects:
        projects = seed_projects()
        save(path, projects)
    return projects


def save(path: Path, projects: List[Project]) -> None:
    """Atomic write: render to a sibling tmp file, then os.replace."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(serialize(projects), encoding="utf-8")
    os.replace(tmp, path)


# ----------------------------------------------------------------- self-test
if __name__ == "__main__":
    sample = (
        "# Todo\n"
        "\n"
        "- [ ] Buy groceries @prio:high @due:2026-05-20 +errands #shopping\n"
        "  - [ ] Milk\n"
        "  - [x] Bread\n"
        "- [x] Submit expense report @prio:med +work\n"
        "- [ ] Read book @due:2026-06-01 +personal #reading\n"
    )
    projects = parse(sample)
    assert len(projects) == 1, projects
    assert projects[0].name == "Todo"
    todos = projects[0].todos
    assert len(todos) == 3, todos
    assert todos[0].label == "Buy groceries"
    assert todos[0].priority == "high"
    assert todos[0].due == "2026-05-20"
    assert todos[0].project_tag == "errands"
    assert todos[0].tags == ["shopping"]
    assert len(todos[0].subtasks) == 2
    assert todos[0].subtasks[0].label == "Milk" and not todos[0].subtasks[0].done
    assert todos[0].subtasks[1].label == "Bread" and todos[0].subtasks[1].done
    assert todos[1].done and todos[1].priority == "med" and todos[1].project_tag == "work"
    assert todos[2].due == "2026-06-01" and todos[2].tags == ["reading"]

    rendered = serialize(projects)
    reparsed = parse(rendered)
    re_rendered = serialize(reparsed)
    assert rendered == re_rendered, "round-trip is not idempotent"
    print("mdstore self-test OK")
    print("---")
    print(rendered, end="")
