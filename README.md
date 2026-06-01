# CLI Todo

A terminal-based todo manager built with Python's `curses` library. It features a clean dark UI, markdown-based persistence, and inline tag syntax for priorities, due dates, and categories.

## Features

- **Curses TUI** — full-screen terminal interface with custom dark color palette
- **Markdown storage** — todos persist to `~/.todos.md` in a human-readable format
- **Inline tags** — priorities, due dates, project tags, and free-form tags parsed from natural input
- **Subtasks** — one level of nesting under any top-level todo
- **Atomic saves** — writes go through a temp file + `os.replace` to avoid corruption
- **Seed data** — first launch generates a starter file so the app isn't empty

## Requirements

- Python 3.10+
- **Windows:** `pip install windows-curses`
- **macOS / Linux:** curses is included in the standard library

## Usage

```bash
# (Optional) create and activate a virtual environment
python -m venv .venv
.venv\Scripts\Activate.ps1   # Windows PowerShell
# source .venv/bin/activate  # macOS/Linux

# Windows only
pip install windows-curses

# Run
python app.py
```

## Keybindings

| Key | Action |
|-----|--------|
| `Tab` | Swap between list and input regions |
| `↑` / `↓` | Move selection in the list |
| `Enter` | Toggle done (list) / Submit input (input region) |
| `e` | Edit the selected todo (loads it into the input) |
| `Esc` | Cancel edit |
| `q` / `Ctrl+C` | Quit |

## Input Syntax

Type a free-form line in the input region. Tags are extracted inline:

```
Buy groceries @prio:high @due:2026-06-15 +errands #shopping
```

| Token | Meaning |
|-------|---------|
| `@prio:<word>` | Priority (e.g. `high`, `med`, `low`) |
| `@due:YYYY-MM-DD` | Due date |
| `+<word>` | Project tag |
| `#<word>` | Free-form tag |

### Adding subtasks

Prefix input with `> ` to attach as a subtask of the currently selected row:

```
> Milk
```

## Data Format

Todos are stored in `~/.todos.md`:

```markdown
# Work

- [ ] Finish report @prio:high @due:2026-06-10 +work
  - [x] Gather data
  - [ ] Write conclusion
- [x] Submit timesheet @prio:med +work

# Personal

- [ ] Read book @due:2026-06-01 +personal #reading
```

Each `# Heading` defines a project. Indented items (2 spaces) are subtasks.

## Project Structure

```
app.py            # Main curses application
_shared/
  __init__.py
  mdstore.py      # Markdown parsing, serialization, and file I/O
  seed.py         # Data models (Todo, Project) and starter seed data
```
