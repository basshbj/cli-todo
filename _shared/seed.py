"""Shared seed data + palette for all Sample 03 Minimal Soft TUI ports.

Mirrors the two `<article class="project">` blocks in
`sample-03-minimal-soft.html`. Every sample imports from here so the
content stays identical across frameworks.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional


# --- Palette (lifted from the `:root` block in sample-03-minimal-soft.html) ---
PALETTE = {
    "bg":            "#050B14",
    "surface":       "#0C1A2B",
    "surface_soft":  "#193B57",
    "border":        "#193B57",
    "border_strong": "#C9D6E2",
    "text":          "#C9D6E2",
    "text_muted":    "#97A4B0",   # ~76% of text against bg
    "accent":        "#2EE6A6",
    "accent_fg":     "#050B14",
    "accent_soft":   "#143C36",   # accent at ~16% over surface, flattened
}


@dataclass
class Todo:
    label: str
    done: bool = False
    priority: Optional[str] = None       # e.g. "high" / "med" / "low"
    due: Optional[str] = None            # ISO date string "YYYY-MM-DD"
    project_tag: Optional[str] = None    # inline `+name` tag
    tags: List[str] = field(default_factory=list)        # `#tag` values, no leading '#'
    subtasks: List["Todo"] = field(default_factory=list)
    # Set by `flatten()` for legacy ports that branch on it. Not part of the
    # markdown round-trip.
    is_sub: bool = False


@dataclass
class Project:
    name: str
    todos: List[Todo] = field(default_factory=list)


def seed_projects() -> List[Project]:
    """Return a fresh copy of the seed projects (mirrors the HTML sample)."""
    return [
        Project(
            name="Project 1",
            todos=[
                Todo(label="Todo"),
                Todo(
                    label="#tag Todo",
                    tags=["tag"],
                    subtasks=[
                        Todo(label="Sub task 1"),
                        Todo(label="Sub task 2"),
                    ],
                ),
            ],
        ),
        Project(
            name="Project 2",
            todos=[
                Todo(label="Todo"),
                Todo(
                    label="#tag Todo",
                    tags=["tag"],
                    subtasks=[
                        Todo(label="Sub task 1"),
                        Todo(label="Sub task 2"),
                    ],
                ),
                Todo(label="Prepare test fixtures", priority="high"),
                Todo(label="Clean query syntax docs", due="2026-06-01"),
            ],
        ),
    ]


def flatten(projects: List[Project]):
    """Yield (project_index, todo_index, project, todo) in display order.

    Descends into `Todo.subtasks`. The `todo.is_sub` attribute is set on the
    yielded `Todo` so legacy ports can still branch on it.
    """
    for pi, project in enumerate(projects):
        ti = 0
        for top in project.todos:
            top.is_sub = False
            yield pi, ti, project, top
            ti += 1
            for sub in top.subtasks:
                sub.is_sub = True
                yield pi, ti, project, sub
                ti += 1
