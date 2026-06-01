"""Sample 03 · Minimal Soft — curses (stdlib) port + full CLI.

Run:
    python explorations/04_curses/app.py
    # Windows: pip install windows-curses first

Persists todos to `~/.todos.md`. Markdown format:

    # Project Name

    - [ ] Buy groceries @prio:high @due:2026-05-20 +errands #shopping
      - [ ] Milk
      - [x] Bread

Input syntax: type a free-form line. Tags are extracted inline:
    @prio:<word>   @due:YYYY-MM-DD   +project   #tag

Subtasks: prefix the input with `> ` to attach as a subtask of the selected
row (or as a sibling subtask if the selected row is already a subtask).

Keys:
    Tab          swap region
    ↑ / ↓        move selection (list region)
    Enter        toggle done (list) / submit (input)
    e            edit selected row (loads it into the input)
    Esc          cancel edit
    q / Ctrl+C   quit
"""

from __future__ import annotations

import curses
import sys
from datetime import date
from pathlib import Path
from typing import List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from _shared.seed import Project, Todo  # noqa: E402
from _shared.mdstore import (  # noqa: E402
    apply_parsed,
    format_input_line,
    load as md_load,
    new_todo_from_text,
    parse_input_line,
    save as md_save,
)


TODOS_PATH = Path.home() / ".todos.md"


# Color pair IDs
CP_BG = 1
CP_MUTED = 2
CP_TITLE = 3
CP_BORDER = 4
CP_BORDER_ACTIVE = 5
CP_PROJECT_BG = 6
CP_ROW = 7
CP_ROW_ACTIVE = 8
CP_ROW_DONE = 9
CP_ACCENT = 10
CP_INPUT = 11


def rgb_to_curses(r: int, g: int, b: int) -> tuple[int, int, int]:
    return (int(r * 1000 / 255), int(g * 1000 / 255), int(b * 1000 / 255))


def init_palette() -> None:
    if not curses.has_colors():
        return
    curses.start_color()
    try:
        curses.use_default_colors()
    except curses.error:
        pass

    can_change = curses.can_change_color() and curses.COLORS >= 16
    C_BG, C_SURFACE, C_SURFACE_SOFT = 16, 17, 18
    C_BORDER, C_TEXT, C_MUTED = 19, 20, 21
    C_ACCENT, C_ACCENT_SOFT, C_ACCENT_FG = 22, 23, 24

    if can_change:
        try:
            curses.init_color(C_BG,           *rgb_to_curses(0x05, 0x0B, 0x14))
            curses.init_color(C_SURFACE,      *rgb_to_curses(0x0C, 0x1A, 0x2B))
            curses.init_color(C_SURFACE_SOFT, *rgb_to_curses(0x19, 0x3B, 0x57))
            curses.init_color(C_BORDER,       *rgb_to_curses(0x19, 0x3B, 0x57))
            curses.init_color(C_TEXT,         *rgb_to_curses(0xC9, 0xD6, 0xE2))
            curses.init_color(C_MUTED,        *rgb_to_curses(0x97, 0xA4, 0xB0))
            curses.init_color(C_ACCENT,       *rgb_to_curses(0x2E, 0xE6, 0xA6))
            curses.init_color(C_ACCENT_SOFT,  *rgb_to_curses(0x14, 0x3C, 0x36))
            curses.init_color(C_ACCENT_FG,    *rgb_to_curses(0x05, 0x0B, 0x14))
            bg, surface, surface_soft = C_BG, C_SURFACE, C_SURFACE_SOFT
            text, muted, accent = C_TEXT, C_MUTED, C_ACCENT
            accent_soft = C_ACCENT_SOFT
        except curses.error:
            can_change = False

    if not can_change:
        bg = curses.COLOR_BLACK
        surface = curses.COLOR_BLACK
        surface_soft = curses.COLOR_BLUE
        text = curses.COLOR_WHITE
        muted = curses.COLOR_WHITE
        accent = curses.COLOR_GREEN
        accent_soft = curses.COLOR_GREEN

    curses.init_pair(CP_BG,            text,   bg)
    curses.init_pair(CP_MUTED,         muted,  bg)
    curses.init_pair(CP_TITLE,         text,   bg)
    curses.init_pair(CP_BORDER,        surface_soft, bg)
    curses.init_pair(CP_BORDER_ACTIVE, accent, bg)
    curses.init_pair(CP_PROJECT_BG,    muted,  surface_soft)
    curses.init_pair(CP_ROW,           text,   surface)
    curses.init_pair(CP_ROW_ACTIVE,    text,   accent_soft)
    curses.init_pair(CP_ROW_DONE,      muted,  surface)
    curses.init_pair(CP_ACCENT,        accent, bg)
    curses.init_pair(CP_INPUT,         text,   surface_soft)


def draw_box(win, y: int, x: int, h: int, w: int, attr) -> None:
    if h < 2 or w < 2:
        return
    try:
        win.addstr(y, x, "╭" + "─" * (w - 2) + "╮", attr)
        for i in range(1, h - 1):
            win.addstr(y + i, x, "│", attr)
            win.addstr(y + i, x + w - 1, "│", attr)
        win.addstr(y + h - 1, x, "╰" + "─" * (w - 2) + "╯", attr)
    except curses.error:
        pass


def safe_addstr(win, y: int, x: int, text: str, attr=0) -> None:
    try:
        max_y, max_x = win.getmaxyx()
        if y < 0 or y >= max_y or x >= max_x:
            return
        available = max_x - x
        if available <= 0:
            return
        win.addstr(y, x, text[:available], attr)
    except curses.error:
        pass


# A flat row: (project_index, parent_todo_or_None, todo). parent is None for
# top-level rows; set to the parent Todo for subtask rows.
FlatRow = Tuple[int, Optional[Todo], Todo]


class App:
    def __init__(self) -> None:
        self.projects: List[Project] = md_load(TODOS_PATH)
        self.active_region: str = "list"
        self.selected: int = 0
        self.scroll: int = 0
        self.input_text: str = ""
        self.editing_index: Optional[int] = None  # selected index being edited

    # --------------------------------------------------------------- model
    def flat_rows(self) -> List[FlatRow]:
        out: List[FlatRow] = []
        for pi, project in enumerate(self.projects):
            for top in project.todos:
                out.append((pi, None, top))
                for sub in top.subtasks:
                    out.append((pi, top, sub))
        return out

    def selected_row(self) -> Optional[FlatRow]:
        flat = self.flat_rows()
        if not flat:
            return None
        self.selected = max(0, min(self.selected, len(flat) - 1))
        return flat[self.selected]

    def selected_project_index(self) -> int:
        row = self.selected_row()
        if row is None:
            return max(0, len(self.projects) - 1)
        return row[0]

    def toggle_selected(self) -> None:
        row = self.selected_row()
        if row is None:
            return
        row[2].done = not row[2].done
        self._persist()

    def add_top_level(self, text: str) -> None:
        parsed = parse_input_line(text)
        if not parsed.label:
            return
        pi = self.selected_project_index()
        new = new_todo_from_text(text)
        self.projects[pi].todos.append(new)
        # Move selection to the new row.
        self._select_todo(new)
        self._persist()

    def add_subtask(self, text: str) -> None:
        parsed = parse_input_line(text)
        if not parsed.label:
            return
        row = self.selected_row()
        if row is None:
            # No anchor available — fall back to top-level append.
            self.add_top_level(text)
            return
        _, parent, todo = row
        anchor = parent if parent is not None else todo
        new = new_todo_from_text(text)
        anchor.subtasks.append(new)
        self._select_todo(new)
        self._persist()

    def edit_selected_into_input(self) -> None:
        row = self.selected_row()
        if row is None:
            return
        _, _, todo = row
        self.input_text = format_input_line(todo)
        self.editing_index = self.selected
        self.active_region = "input"

    def commit_edit(self, text: str) -> None:
        if self.editing_index is None:
            return
        flat = self.flat_rows()
        if not (0 <= self.editing_index < len(flat)):
            self.editing_index = None
            return
        # Strip a leading `>` if present — reparenting via edit is out of scope.
        clean = text.lstrip()
        if clean.startswith(">"):
            clean = clean[1:].lstrip()
        parsed = parse_input_line(clean)
        if not parsed.label:
            self.editing_index = None
            return
        _, _, todo = flat[self.editing_index]
        apply_parsed(todo, parsed)
        self.editing_index = None
        self._persist()

    def cancel_edit(self) -> None:
        self.editing_index = None
        self.input_text = ""

    def _select_todo(self, target: Todo) -> None:
        for i, (_, _, t) in enumerate(self.flat_rows()):
            if t is target:
                self.selected = i
                return

    def _persist(self) -> None:
        try:
            md_save(TODOS_PATH, self.projects)
        except OSError:
            # Persistence failure is non-fatal for the running session.
            pass

    # ---------------------------------------------------------- rendering
    def _tag_suffix(self, todo: Todo) -> str:
        parts: List[str] = []
        if todo.priority:
            parts.append(f"@prio:{todo.priority}")
        if todo.due:
            parts.append(f"@due:{todo.due}")
        if todo.project_tag:
            parts.append(f"+{todo.project_tag}")
        for tag in todo.tags:
            parts.append(f"#{tag}")
        return " ".join(parts)

    def _is_overdue(self, todo: Todo) -> bool:
        if not todo.due or todo.done:
            return False
        try:
            return todo.due < date.today().isoformat()
        except Exception:
            return False

    def render(self, stdscr) -> None:
        stdscr.erase()
        stdscr.bkgd(" ", curses.color_pair(CP_BG))
        max_y, max_x = stdscr.getmaxyx()

        # Caption
        safe_addstr(stdscr, 0, 1, "Sample 03 · Minimal Soft",
                    curses.color_pair(CP_TITLE) | curses.A_BOLD)
        path_hint = f"~/{TODOS_PATH.name}"
        safe_addstr(stdscr, 0, max(1, max_x - len(path_hint) - 1), path_hint,
                    curses.color_pair(CP_MUTED))

        # Footer
        footer = (" Tab swap · Enter toggle/add · e edit · Esc cancel · "
                  "> prefix = subtask · q quit")
        safe_addstr(stdscr, max_y - 1, 1, footer, curses.color_pair(CP_MUTED))

        # Region geometry
        shell_y, shell_x = 2, 1
        shell_h, shell_w = max_y - 3, max_x - 2

        input_h = 5
        list_h = shell_h - input_h - 1
        list_attr = (curses.color_pair(CP_BORDER_ACTIVE)
                     if self.active_region == "list"
                     else curses.color_pair(CP_BORDER))
        input_attr = (curses.color_pair(CP_BORDER_ACTIVE)
                      if self.active_region == "input"
                      else curses.color_pair(CP_BORDER))

        draw_box(stdscr, shell_y, shell_x, list_h, shell_w, list_attr)
        draw_box(stdscr, shell_y + list_h, shell_x, input_h, shell_w, input_attr)

        # List head
        list_status = "Active: List" if self.active_region == "list" else "Inactive"
        head = " ToDo list area - Scrollable"
        safe_addstr(stdscr, shell_y + 1, shell_x + 2, head, curses.color_pair(CP_MUTED))
        status_attr = (curses.color_pair(CP_ACCENT) | curses.A_BOLD
                       if self.active_region == "list"
                       else curses.color_pair(CP_MUTED))
        safe_addstr(stdscr, shell_y + 1,
                    shell_x + shell_w - len(list_status) - 3,
                    list_status, status_attr)
        try:
            stdscr.addstr(shell_y + 2, shell_x + 1, "─" * (shell_w - 2),
                          curses.color_pair(CP_BORDER))
        except curses.error:
            pass

        content_y0 = shell_y + 3
        content_h = list_h - 4
        content_w = shell_w - 4

        # Build display lines
        # kind: "project" | "row" | "blank"
        # For "row" the payload is (todo, is_sub, is_selected)
        lines: List[Tuple[str, object]] = []
        flat = self.flat_rows()
        cursor = 0
        for pi, project in enumerate(self.projects):
            if pi > 0:
                lines.append(("blank", ""))
            lines.append(("project", f"  {project.name.upper()}"))
            for top in project.todos:
                is_sel = (cursor == self.selected and self.active_region == "list")
                lines.append(("row", (top, False, is_sel)))
                cursor += 1
                for sub in top.subtasks:
                    is_sel = (cursor == self.selected and self.active_region == "list")
                    lines.append(("row", (sub, True, is_sel)))
                    cursor += 1

        # Keep selection visible
        row_line_indices = [i for i, ln in enumerate(lines) if ln[0] == "row"]
        if row_line_indices and self.selected < len(row_line_indices):
            sel_line = row_line_indices[self.selected]
            if sel_line < self.scroll:
                self.scroll = sel_line
            elif sel_line >= self.scroll + content_h:
                self.scroll = sel_line - content_h + 1
        self.scroll = max(0, self.scroll)

        for vi in range(content_h):
            li = self.scroll + vi
            if li >= len(lines):
                break
            kind, payload = lines[li]
            y = content_y0 + vi
            x = shell_x + 2
            safe_addstr(stdscr, y, x, " " * content_w, curses.color_pair(CP_ROW))
            if kind == "project":
                safe_addstr(stdscr, y, x, str(payload).ljust(content_w),
                            curses.color_pair(CP_PROJECT_BG) | curses.A_BOLD)
            elif kind == "row":
                todo, is_sub, is_sel = payload  # type: ignore[misc]
                indent = "    " if is_sub else "  "
                box = "[✓]" if todo.done else "[ ]"
                label_part = f"{indent}{box}  {todo.label}"
                tag_part = self._tag_suffix(todo)
                overdue = self._is_overdue(todo)
                if overdue:
                    tag_part = (tag_part + "  !") if tag_part else "!"

                # Base row background
                if is_sel:
                    base_attr = curses.color_pair(CP_ROW_ACTIVE) | curses.A_BOLD
                elif todo.done:
                    base_attr = curses.color_pair(CP_ROW_DONE) | curses.A_DIM
                else:
                    base_attr = curses.color_pair(CP_ROW)

                # Paint the whole row width with the row background first
                safe_addstr(stdscr, y, x, " " * content_w, base_attr)
                # Then the label
                safe_addstr(stdscr, y, x, label_part, base_attr)

                # High-priority accent on the box for undone rows
                if todo.priority == "high" and not todo.done and not is_sel:
                    safe_addstr(stdscr, y, x + len(indent), box,
                                curses.color_pair(CP_ACCENT) | curses.A_BOLD)

                # Tag suffix in muted/dim
                if tag_part:
                    tag_x = x + len(label_part) + 2
                    if tag_x < x + content_w:
                        tag_attr = (curses.color_pair(CP_ROW_ACTIVE) | curses.A_DIM
                                    if is_sel
                                    else curses.color_pair(CP_ROW_DONE) | curses.A_DIM)
                        safe_addstr(stdscr, y, tag_x,
                                    tag_part[: x + content_w - tag_x],
                                    tag_attr)

        # Input region head
        ih_y = shell_y + list_h + 1
        if self.editing_index is not None:
            input_status = "Editing"
        elif self.active_region == "input":
            input_status = "Active: Input"
        else:
            input_status = "Inactive"
        safe_addstr(stdscr, ih_y, shell_x + 2,
                    " TextBox area - Fixed - Input new todo",
                    curses.color_pair(CP_MUTED))
        in_status_attr = (curses.color_pair(CP_ACCENT) | curses.A_BOLD
                          if self.active_region == "input"
                          else curses.color_pair(CP_MUTED))
        safe_addstr(stdscr, ih_y,
                    shell_x + shell_w - len(input_status) - 3,
                    input_status, in_status_attr)
        try:
            stdscr.addstr(ih_y + 1, shell_x + 1, "─" * (shell_w - 2),
                          curses.color_pair(CP_BORDER))
        except curses.error:
            pass

        # Input field
        placeholder = "Input new todo  (prefix with `> ` for a subtask)"
        field_attr = curses.color_pair(CP_INPUT)
        if self.input_text:
            field = "  > " + self.input_text
        else:
            field = "  > " + placeholder
            field_attr |= curses.A_DIM
        safe_addstr(stdscr, ih_y + 2, shell_x + 2,
                    field.ljust(shell_w - 4), field_attr)

        # Micro hint
        micro = ("Editing — Enter to save, Esc to cancel"
                 if self.editing_index is not None
                 else "Tags: @prio:high  @due:2026-05-20  +project  #tag")
        safe_addstr(stdscr, ih_y + 3, shell_x + 2,
                    micro, curses.color_pair(CP_MUTED))

        # Place cursor in input field when active
        if self.active_region == "input":
            curses.curs_set(1)
            cur_x = shell_x + 2 + len("  > ") + len(self.input_text)
            try:
                stdscr.move(ih_y + 2, min(cur_x, max_x - 2))
            except curses.error:
                pass
        else:
            curses.curs_set(0)

        stdscr.refresh()

    # ---------------------------------------------------------------- loop
    def _submit_input(self) -> None:
        text = self.input_text
        self.input_text = ""
        if self.editing_index is not None:
            self.commit_edit(text)
            return
        stripped = text.lstrip()
        if stripped.startswith(">"):
            self.add_subtask(stripped[1:].lstrip())
        else:
            self.add_top_level(text)

    def run(self, stdscr) -> None:
        init_palette()
        curses.curs_set(0)
        stdscr.keypad(True)

        while True:
            self.render(stdscr)
            try:
                ch = stdscr.get_wch()
            except KeyboardInterrupt:
                return

            if isinstance(ch, str):
                # Tab swap (works in both regions)
                if ch == "\t":
                    self.active_region = "input" if self.active_region == "list" else "list"
                    continue
                if ch == "\x03":  # Ctrl+C
                    return
                if ch == "\x1b":  # Escape
                    if self.active_region == "input":
                        if self.editing_index is not None:
                            self.cancel_edit()
                        else:
                            self.input_text = ""
                        self.active_region = "list"
                    continue

                if self.active_region == "list":
                    if ch in ("q", "Q"):
                        return
                    if ch in ("\n", "\r"):
                        self.toggle_selected()
                    elif ch in ("e", "E"):
                        self.edit_selected_into_input()
                else:
                    if ch in ("\n", "\r"):
                        self._submit_input()
                    elif ch in ("\x7f", "\b"):
                        self.input_text = self.input_text[:-1]
                    elif ch.isprintable():
                        self.input_text += ch
            else:
                # Special key codes
                if ch == curses.KEY_DOWN and self.active_region == "list":
                    n = len(self.flat_rows())
                    if n:
                        self.selected = (self.selected + 1) % n
                elif ch == curses.KEY_UP and self.active_region == "list":
                    n = len(self.flat_rows())
                    if n:
                        self.selected = (self.selected - 1 + n) % n
                elif ch == curses.KEY_BACKSPACE and self.active_region == "input":
                    self.input_text = self.input_text[:-1]
                elif ch == curses.KEY_BTAB:
                    self.active_region = "input" if self.active_region == "list" else "list"


def main(stdscr) -> None:
    App().run(stdscr)


if __name__ == "__main__":
    curses.wrapper(main)
