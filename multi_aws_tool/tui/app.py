"""
Terminal UI (TUI) for MultiAWSTool
Provides an interactive terminal interface using Python curses for:
  - Browsing and filtering AWS accounts
  - Managing teams and their member accounts
  - Viewing and running command templates
  - Creating command templates directly in the TUI
  - Browsing saved run results with visual status bars
  - A guided multi-step command execution workflow
"""

import curses
import os
import sys
from typing import Any, Dict, List, Optional, Set, Tuple

# ─── Color pair indices ───────────────────────────────────────────────────────

_CP_NORMAL   = 1  # Default text
_CP_SELECTED = 2  # Highlighted / selected row
_CP_HEADER   = 3  # Title / header bar
_CP_SUCCESS  = 4  # Green – positive feedback
_CP_ERROR    = 5  # Red   – errors
_CP_WARNING  = 6  # Yellow – warnings / prompts
_CP_DIM      = 7  # Subdued text
_CP_INFO     = 8  # Cyan  – informational

# ─── Key helpers ─────────────────────────────────────────────────────────────

_ENTER_KEYS = {curses.KEY_ENTER, ord('\n'), ord('\r')}
_ESC        = 27
_CTRL_C     = 3


def _is_enter(key: int) -> bool:
    return key in _ENTER_KEYS


def _truncate(text: str, max_len: int) -> str:
    """Truncate text with ellipsis if it exceeds max_len."""
    if max_len <= 0:
        return ''
    if len(text) <= max_len:
        return text
    return text[:max_len - 1] + '…'


def _sanitize_profile_name_component(name: str) -> str:
    """Sanitize a name component for use in AWS profile names."""
    sanitized = name.replace(' ', '-').replace('_', '-').replace('.', '-')
    sanitized = ''.join(c for c in sanitized if c.isalnum() or c == '-')
    sanitized = '-'.join(filter(None, sanitized.split('-')))
    return sanitized


# ─── TUIApp ───────────────────────────────────────────────────────────────────

class TUIApp:
    """Main TUI application driven by curses.

    Usage::

        app = TUIApp(account_manager, config_manager)
        run_params = app.run()   # returns None or a dict for 'run' action
    """

    def __init__(self, account_manager: Any, config_manager: Any) -> None:
        self.account_manager = account_manager
        self.config_manager  = config_manager
        self.stdscr: Optional[curses.window] = None
        # Cached account collection; cleared by _reload_collection()
        self._collection: Any = None

    # ─── Public entry point ───────────────────────────────────────────────

    def run(self) -> Optional[Dict[str, Any]]:
        """Launch the TUI.

        Returns ``None`` if the user quits normally, or a dict describing a
        command to execute afterwards::

            {
                'action':   'run',
                'accounts': ['123...', '456...'],
                'command':  'sts get-caller-identity',
                'parallel': True,
                'region':   'us-east-1',
                'dry_run':  False,
                'role':     'PowerUserAccess',  # may be ''
            }
        """
        self._run_result: Optional[Dict[str, Any]] = None
        curses.wrapper(self._main)
        return self._run_result

    # ─── Curses initialisation ────────────────────────────────────────────

    def _main(self, stdscr: curses.window) -> None:
        self.stdscr = stdscr
        self._init_colors()
        curses.curs_set(0)
        stdscr.keypad(True)
        curses.noecho()

        screen: Optional[str] = 'main'
        while screen is not None:
            if   screen == 'main':      screen = self._screen_main()
            elif screen == 'accounts':  screen = self._screen_accounts()
            elif screen == 'teams':     screen = self._screen_teams()
            elif screen == 'templates': screen = self._screen_templates()
            elif screen == 'results':   screen = self._screen_results()
            elif screen == 'run':       screen = self._screen_run_workflow()
            elif screen == 'config':    screen = self._screen_config()
            elif screen == 'discovery': screen = self._screen_discovery()
            else:                       break

    def _init_colors(self) -> None:
        curses.start_color()
        try:
            curses.use_default_colors()
            bg = -1
        except Exception:
            bg = curses.COLOR_BLACK

        curses.init_pair(_CP_NORMAL,   curses.COLOR_WHITE,  bg)
        curses.init_pair(_CP_SELECTED, curses.COLOR_BLACK,  curses.COLOR_WHITE)
        curses.init_pair(_CP_HEADER,   curses.COLOR_WHITE,  curses.COLOR_BLUE)
        curses.init_pair(_CP_SUCCESS,  curses.COLOR_GREEN,  bg)
        curses.init_pair(_CP_ERROR,    curses.COLOR_RED,    bg)
        curses.init_pair(_CP_WARNING,  curses.COLOR_YELLOW, bg)
        curses.init_pair(_CP_DIM,      curses.COLOR_WHITE,  bg)
        curses.init_pair(_CP_INFO,     curses.COLOR_CYAN,   bg)

    # ─── Account collection cache ─────────────────────────────────────────

    def _get_collection(self) -> Any:
        if self._collection is None:
            try:
                self._collection = self.account_manager.data_manager.load_accounts()
            except Exception:
                self._collection = None
        return self._collection

    def _reload_collection(self) -> Any:
        self._collection = None
        return self._get_collection()

    def _save_collection(self) -> bool:
        collection = self._get_collection()
        if collection is None:
            return False
        try:
            self.account_manager.data_manager.save_accounts(collection)
            return True
        except Exception:
            return False

    # ─── Common drawing primitives ────────────────────────────────────────

    def _draw_header(self, title: str, subtitle: str = '') -> int:
        """Draw a blue title bar; return the first free row."""
        h, w = self.stdscr.getmaxyx()
        attr = curses.color_pair(_CP_HEADER) | curses.A_BOLD
        self.stdscr.attron(attr)
        self.stdscr.addstr(0, 0, (' ' * (w - 1))[:w - 1])
        label = f'  MultiAWSTool  ›  {title}'
        self.stdscr.addstr(0, 0, _truncate(label, w - 1))
        self.stdscr.attroff(attr)

        row = 1
        if subtitle:
            self.stdscr.attron(curses.color_pair(_CP_DIM))
            self.stdscr.addstr(1, 2, _truncate(subtitle, w - 3))
            self.stdscr.attroff(curses.color_pair(_CP_DIM))
            row = 2
        return row + 1  # leave a blank separator

    def _draw_footer(self, help_text: str) -> None:
        """Draw a blue help bar at the bottom."""
        h, w = self.stdscr.getmaxyx()
        attr = curses.color_pair(_CP_HEADER)
        self.stdscr.attron(attr)
        self.stdscr.addstr(h - 1, 0, (' ' * (w - 1))[:w - 1])
        self.stdscr.addstr(h - 1, 1, _truncate(help_text, w - 2))
        self.stdscr.attroff(attr)

    def _draw_list_rows(
        self,
        rows: List[str],
        selected: int,
        start_row: int,
        max_rows: int,
        scroll: int,
    ) -> None:
        """Render a scrollable list starting at *start_row*."""
        h, w = self.stdscr.getmaxyx()
        for i, text in enumerate(rows[scroll: scroll + max_rows]):
            r = start_row + i
            if r >= h - 1:
                break
            abs_i = scroll + i
            if abs_i == selected:
                attr = curses.color_pair(_CP_SELECTED) | curses.A_BOLD
                line = f' ▶  {text}'
            else:
                attr = curses.color_pair(_CP_NORMAL)
                line = f'    {text}'
            self.stdscr.attron(attr)
            self.stdscr.addstr(r, 0, _truncate(line, w - 1).ljust(w - 1))
            self.stdscr.attroff(attr)

    def _draw_multiselect_rows(
        self,
        rows: List[str],
        selected: int,
        checked: Set[int],
        start_row: int,
        max_rows: int,
        scroll: int,
    ) -> None:
        """Render a multi-select list where checked items show ✓."""
        h, w = self.stdscr.getmaxyx()
        for i, text in enumerate(rows[scroll: scroll + max_rows]):
            r = start_row + i
            if r >= h - 1:
                break
            abs_i = scroll + i
            check = '✓' if abs_i in checked else ' '
            if abs_i == selected:
                attr = curses.color_pair(_CP_SELECTED) | curses.A_BOLD
                line = f' ▶ [{check}] {text}'
            else:
                attr = curses.color_pair(_CP_NORMAL)
                line = f'    [{check}] {text}'
            self.stdscr.attron(attr)
            self.stdscr.addstr(r, 0, _truncate(line, w - 1).ljust(w - 1))
            self.stdscr.attroff(attr)

    # ─── Navigation helpers ───────────────────────────────────────────────

    @staticmethod
    def _nav(
        key: int,
        selected: int,
        scroll: int,
        total: int,
        visible: int,
    ) -> Tuple[int, int]:
        """Update (selected, scroll) based on *key*."""
        if key == curses.KEY_UP and selected > 0:
            selected -= 1
            if selected < scroll:
                scroll = selected
        elif key == curses.KEY_DOWN and selected < total - 1:
            selected += 1
            if selected >= scroll + visible:
                scroll = selected - visible + 1
        elif key == curses.KEY_PPAGE:
            selected = max(0, selected - visible)
            scroll   = max(0, scroll   - visible)
            if selected < scroll:
                scroll = selected
        elif key == curses.KEY_NPAGE:
            selected = min(total - 1, selected + visible)
            scroll   = min(max(0, total - visible), scroll + visible)
            if selected >= scroll + visible:
                scroll = selected - visible + 1
        elif key == curses.KEY_HOME:
            selected = 0
            scroll   = 0
        elif key == curses.KEY_END:
            selected = total - 1
            scroll   = max(0, total - visible)
        return selected, scroll

    # ─── Dialog helpers ───────────────────────────────────────────────────

    def _prompt(self, label: str, default: str = '') -> Optional[str]:
        """Show an inline text input at the second-to-last row.

        Returns the entered string, or *None* if the user pressed ESC.
        """
        h, w = self.stdscr.getmaxyx()
        curses.curs_set(1)
        curses.echo()
        prompt_str = f'  {label}: '
        attr = curses.color_pair(_CP_WARNING) | curses.A_BOLD
        self.stdscr.attron(attr)
        self.stdscr.addstr(h - 2, 0, (' ' * (w - 1))[:w - 1])
        self.stdscr.addstr(h - 2, 0, _truncate(prompt_str, w - 1))
        self.stdscr.attroff(attr)
        col = len(prompt_str)
        if default:
            self.stdscr.attron(curses.color_pair(_CP_NORMAL))
            self.stdscr.addstr(h - 2, col, _truncate(default, w - col - 1))
            self.stdscr.attroff(curses.color_pair(_CP_NORMAL))
        self.stdscr.move(h - 2, col)
        self.stdscr.refresh()
        try:
            raw = self.stdscr.getstr(h - 2, col, w - col - 2)
            value = raw.decode('utf-8', errors='replace')
        except (curses.error, UnicodeDecodeError):
            value = None
        finally:
            curses.noecho()
            curses.curs_set(0)
        return value

    def _confirm(self, message: str) -> bool:
        """Show a yes/no prompt; return True if the user pressed y/Y."""
        h, w = self.stdscr.getmaxyx()
        prompt = f'  {message} [y/N]: '
        attr = curses.color_pair(_CP_WARNING) | curses.A_BOLD
        self.stdscr.attron(attr)
        self.stdscr.addstr(h - 2, 0, (' ' * (w - 1))[:w - 1])
        self.stdscr.addstr(h - 2, 0, _truncate(prompt, w - 1))
        self.stdscr.attroff(attr)
        self.stdscr.refresh()
        return self.stdscr.getch() in (ord('y'), ord('Y'))

    def _flash(self, message: str, is_error: bool = False) -> None:
        """Show a transient status message for ~1.5 s."""
        h, w = self.stdscr.getmaxyx()
        attr = curses.color_pair(_CP_ERROR if is_error else _CP_SUCCESS) | curses.A_BOLD
        self.stdscr.attron(attr)
        self.stdscr.addstr(h - 2, 0, (' ' * (w - 1))[:w - 1])
        self.stdscr.addstr(h - 2, 0, _truncate(f'  {message}', w - 1))
        self.stdscr.attroff(attr)
        self.stdscr.refresh()
        curses.napms(1500)

    def _detail_page(self, title: str, lines: List[str]) -> None:
        """Show a read-only scrollable detail page; any key returns."""
        scroll  = 0
        while True:
            self.stdscr.clear()
            h, w = self.stdscr.getmaxyx()
            start = self._draw_header(title)
            visible = h - start - 1
            for i, line in enumerate(lines[scroll: scroll + visible]):
                r = start + i
                self.stdscr.attron(curses.color_pair(_CP_NORMAL))
                self.stdscr.addstr(r, 2, _truncate(line, w - 3))
                self.stdscr.attroff(curses.color_pair(_CP_NORMAL))
            self._draw_footer(' ↑↓/PgUp/PgDn Scroll   Any key Back ')
            self.stdscr.refresh()
            key = self.stdscr.getch()
            if key == curses.KEY_UP:
                scroll = max(0, scroll - 1)
            elif key == curses.KEY_DOWN:
                scroll = min(max(0, len(lines) - visible), scroll + 1)
            elif key == curses.KEY_PPAGE:
                scroll = max(0, scroll - visible)
            elif key == curses.KEY_NPAGE:
                scroll = min(max(0, len(lines) - visible), scroll + visible)
            else:
                return

    def _pick_from_list(
        self, title: str, options: List[str], subtitle: str = 'Select an option'
    ) -> Optional[str]:
        """Show a simple single-select list and return the chosen option."""
        if not options:
            return None

        selected = 0
        scroll = 0

        while True:
            self.stdscr.clear()
            h, w = self.stdscr.getmaxyx()
            start = self._draw_header(title, subtitle)
            visible = h - start - 1
            rows = [_truncate(option, max(10, w - 6)) for option in options]
            self._draw_list_rows(rows, selected, start, visible, scroll)
            self._draw_footer(' ↑↓ Navigate   Enter Select   Q Back ')
            self.stdscr.refresh()

            key = self.stdscr.getch()
            if key in (_ESC, _CTRL_C, ord('q'), ord('Q')):
                return None
            if _is_enter(key):
                return options[selected]
            selected, scroll = self._nav(key, selected, scroll, len(options), visible)

    @staticmethod
    def _ratio_bar(value: int, total: int, width: int = 20, fill: str = '█') -> str:
        """Return a fixed-width bar visualising value/total."""
        if width <= 0:
            return ''
        if total <= 0:
            return '░' * width
        ratio = max(0.0, min(1.0, float(value) / float(total)))
        filled = int(round(ratio * width))
        filled = max(0, min(width, filled))
        return (fill * filled) + ('░' * (width - filled))

    def _results_output_path(self) -> str:
        """Resolve the directory where run summaries are saved."""
        default = '~/.multi-aws/outputs'
        if self.config_manager is None:
            return os.path.expanduser(default)
        try:
            configured = self.config_manager.get('output', 'path', default)
        except Exception:
            configured = default
        return os.path.expanduser(configured)

    def _load_saved_results(self) -> List[Dict[str, Any]]:
        """Load execution summary files from the configured output directory."""
        from ..output import OutputParser

        output_path = self._results_output_path()
        parser = OutputParser(output_path)
        try:
            files = sorted(
                parser.find_execution_summaries(),
                key=lambda p: p.stat().st_mtime,
                reverse=True,
            )
        except Exception:
            return []

        records: List[Dict[str, Any]] = []
        for path in files:
            try:
                summary = parser.parse_execution_summary(path)
            except Exception:
                continue
            command = summary.command if isinstance(summary.command, str) else ' '.join(summary.command or [])
            records.append(
                {
                    'file_name': path.name,
                    'file_path': str(path),
                    'timestamp': str(summary.timestamp),
                    'command': command,
                    'total': int(summary.total_accounts),
                    'success': int(summary.successful_accounts),
                    'failed': int(summary.failed_accounts),
                    'timeout': int(summary.timeout_accounts),
                    'mode': str(summary.execution_mode),
                    'summary': summary,
                }
            )
        return records

    # ─── Screen: Main menu ────────────────────────────────────────────────

    def _screen_main(self) -> Optional[str]:
        """Render the main navigation menu."""
        options: List[Tuple[str, str, Optional[str]]] = [
            ('A', 'Browse Accounts',       'accounts'),
            ('T', 'Manage Teams',          'teams'),
            ('P', 'Templates / Presets',   'templates'),
            ('V', 'Browse Run Results',    'results'),
            ('R', 'Run Command Workflow',  'run'),
            ('D', 'Discovery & Profiles',  'discovery'),
            ('C', 'Edit Configuration',    'config'),
            ('Q', 'Quit',                  None),
        ]
        selected = 0

        while True:
            self.stdscr.clear()
            h, w = self.stdscr.getmaxyx()
            start = self._draw_header('Main Menu')

            for i, (shortcut, label, _) in enumerate(options):
                row = start + i * 2  # leave a blank line between items
                if row >= h - 2:
                    break
                if i == selected:
                    attr = curses.color_pair(_CP_SELECTED) | curses.A_BOLD
                    prefix = ' ▶ '
                else:
                    attr = curses.color_pair(_CP_NORMAL)
                    prefix = '   '
                line = f'{prefix}[{shortcut}] {label}'
                self.stdscr.attron(attr)
                self.stdscr.addstr(row, 0, _truncate(line, w - 1).ljust(w - 1))
                self.stdscr.attroff(attr)

            self._draw_footer(' ↑↓ Navigate   Enter Select   letter shortcut ')
            self.stdscr.refresh()

            key = self.stdscr.getch()

            if key == curses.KEY_UP and selected > 0:
                selected -= 1
            elif key == curses.KEY_DOWN and selected < len(options) - 1:
                selected += 1
            elif _is_enter(key) or key == ord(' '):
                return options[selected][2]
            elif key in (_ESC, _CTRL_C):
                return None
            else:
                for shortcut, _, dest in options:
                    if key in (ord(shortcut.lower()), ord(shortcut.upper())):
                        return dest

    # ─── Screen: Accounts browser ─────────────────────────────────────────

    def _screen_accounts(self) -> Optional[str]:
        """Browse, filter and inspect accounts."""
        collection = self._get_collection()

        selected  = 0
        scroll    = 0
        filt      = ''   # current filter string
        filtering = False

        while True:
            collection = self._get_collection()
            accounts = list(collection.accounts) if collection else []

            # Apply filter
            if filt:
                fl = filt.lower()
                accounts = [
                    a for a in accounts
                    if fl in a.name.lower()
                    or fl in a.id
                    or fl in (a.product_team or '').lower()
                    or fl in (a.status.value if hasattr(a.status, 'value') else str(a.status)).lower()
                ]

            total   = len(accounts)
            h, w    = self.stdscr.getmaxyx()
            start   = self._draw_header(
                'Accounts',
                f'{len(collection.accounts) if collection else 0} total'
                + (f'  ·  filter: "{filt}"' if filt else ''),
            )
            visible = h - start - 1

            self.stdscr.clear()
            start = self._draw_header(
                'Accounts',
                f'{len(collection.accounts) if collection else 0} total'
                + (f'  ·  filter: "{filt}"' if filt else ''),
            )

            if not accounts:
                msg = 'No accounts found.' if not collection else 'No accounts match the filter.'
                self.stdscr.attron(curses.color_pair(_CP_DIM))
                self.stdscr.addstr(start, 2, msg)
                self.stdscr.attroff(curses.color_pair(_CP_DIM))
            else:
                # Build display rows
                id_w    = 14
                name_w  = max(10, w // 3)
                team_w  = max(8, w // 6)
                rows = []
                for a in accounts:
                    status_sym = '●' if (hasattr(a.status, 'value') and a.status.value == 'active') or str(a.status) == 'AccountStatus.ACTIVE' else '○'
                    profile_sym = '✓' if a.profile_name else ' '
                    name  = _truncate(a.name, name_w)
                    team  = _truncate(a.product_team or '—', team_w)
                    rows.append(
                        f'{a.id:<{id_w}}  {name:<{name_w}}  {status_sym}  {team:<{team_w}}  [{profile_sym}]'
                    )
                selected = min(selected, total - 1) if total else 0
                self._draw_list_rows(rows, selected, start, visible, scroll)

            if filtering:
                self._draw_footer(f' Filter: {filt}_  (Enter confirm  Esc cancel) ')
            else:
                self._draw_footer(
                    ' ↑↓ Navigate   Enter Details   T Team   / Filter   R Reload   Q Back '
                )
            self.stdscr.refresh()

            key = self.stdscr.getch()

            if filtering:
                if key in (_ESC, _CTRL_C):
                    filtering = False
                    filt = ''
                elif _is_enter(key):
                    filtering = False
                    selected = 0
                    scroll   = 0
                elif key in (curses.KEY_BACKSPACE, 127, 8):
                    filt = filt[:-1]
                elif 32 <= key <= 126:
                    filt += chr(key)
                continue

            if key in (_ESC, ord('q'), ord('Q')):
                return 'main'
            elif key == ord('/'):
                filtering = True
                filt = ''
                selected = 0
                scroll   = 0
            elif key == ord('r') or key == ord('R'):
                self._reload_collection()
                selected = 0
                scroll   = 0
            elif total and _is_enter(key):
                self._show_account_detail(accounts[selected])
            elif total and key in (ord('t'), ord('T')):
                self._account_assign_team(accounts[selected])
                self._reload_collection()
            else:
                selected, scroll = self._nav(key, selected, scroll, total, visible)

    def _show_account_detail(self, account: Any) -> None:
        """Show a detail page for a single account."""
        scroll = 0

        while True:
            collection = self._get_collection()
            current = collection.get_account(account.id) if collection else account
            status = current.status.value if hasattr(current.status, 'value') else str(current.status)
            lines = [
                f'ID:      {current.id}',
                f'Name:    {current.name}',
                f'Status:  {status}',
                f'Team:    {current.product_team or "(none)"}',
                f'Profile: {current.profile_name or "(none)"}',
                '',
                f'Roles ({len(current.roles)}):',
            ]
            for role in current.roles:
                lines.append(f'  • {role.name}')
                if role.arn:
                    lines.append(f'    {role.arn}')
            if not current.roles:
                lines.append('  (no roles fetched yet)')
            lines.append('')
            lines.append(f'Tags ({len(current.tags)}):')
            for k, v in sorted(current.tags.items()):
                lines.append(f'  {k} = {v}')
            if not current.tags:
                lines.append('  (no tags)')
            lines.append('')
            updated = current.last_updated.isoformat() if hasattr(current.last_updated, 'isoformat') else str(current.last_updated)
            lines.append(f'Last updated: {updated}')

            self.stdscr.clear()
            h, w = self.stdscr.getmaxyx()
            start = self._draw_header(f'Account: {current.name}', current.id)
            visible = h - start - 1
            for i, line in enumerate(lines[scroll: scroll + visible]):
                r = start + i
                self.stdscr.attron(curses.color_pair(_CP_NORMAL))
                self.stdscr.addstr(r, 2, _truncate(line, w - 3))
                self.stdscr.attroff(curses.color_pair(_CP_NORMAL))
            self._draw_footer(
                ' ↑↓/PgUp/PgDn Scroll   P Create profile   E Edit account   Q Back '
            )
            self.stdscr.refresh()

            key = self.stdscr.getch()
            if key in (_ESC, _CTRL_C, ord('q'), ord('Q')):
                return
            if key == curses.KEY_UP:
                scroll = max(0, scroll - 1)
            elif key == curses.KEY_DOWN:
                scroll = min(max(0, len(lines) - visible), scroll + 1)
            elif key == curses.KEY_PPAGE:
                scroll = max(0, scroll - visible)
            elif key == curses.KEY_NPAGE:
                scroll = min(max(0, len(lines) - visible), scroll + visible)
            elif key in (ord('p'), ord('P')):
                self._account_create_profile(current)
            elif key in (ord('e'), ord('E')):
                self._account_edit_details(current)

    def _account_assign_team(self, account: Any) -> None:
        """Prompt to assign (or remove) a team for *account*."""
        h, w = self.stdscr.getmaxyx()
        current = account.product_team or ''
        new_team = self._prompt(
            f'Team for {account.name} (blank to remove)',
            default=current,
        )
        if new_team is None:
            return  # user pressed ESC
        collection = self._get_collection()
        acc = collection.get_account(account.id) if collection else None
        if acc is None:
            self._flash('Account not found in data.', is_error=True)
            return
        acc.product_team = new_team.strip() or None
        from datetime import datetime
        acc.last_updated = datetime.now()
        if self._save_collection():
            msg = f'Team set to "{new_team.strip()}"' if new_team.strip() else 'Team removed'
            self._flash(msg)
        else:
            self._flash('Failed to save changes.', is_error=True)

    def _account_edit_details(self, account: Any) -> None:
        """Show account detail edit actions."""
        action = self._pick_from_list(
            f'Edit Account: {account.name}',
            ['Edit team', 'Set tag', 'Remove tag'],
            'Update account metadata',
        )
        if action == 'Edit team':
            self._account_assign_team(account)
        elif action == 'Set tag':
            self._account_set_tag(account)
        elif action == 'Remove tag':
            self._account_remove_tag(account)

    def _account_set_tag(self, account: Any) -> None:
        """Prompt to create or update a tag on an account."""
        collection = self._get_collection()
        acc = collection.get_account(account.id) if collection else None
        if acc is None:
            self._flash('Account not found in data.', is_error=True)
            return

        key = self._prompt(f'Tag key for {acc.name}')
        if key is None or not key.strip():
            return
        key = key.strip()
        current_value = acc.tags.get(key, '')
        value = self._prompt(f'Value for tag "{key}" (blank to remove)', default=current_value)
        if value is None:
            return

        from datetime import datetime

        new_value = value.strip()
        if new_value:
            acc.tags[key] = new_value
            acc.last_updated = datetime.now()
            if self._save_collection():
                self._flash(f'Tag "{key}" set to "{new_value}"')
            else:
                self._flash('Failed to save changes.', is_error=True)
            return

        if key not in acc.tags:
            self._flash(f'Tag "{key}" is not set.', is_error=True)
            return

        acc.tags.pop(key, None)
        acc.last_updated = datetime.now()
        if self._save_collection():
            self._flash(f'Tag "{key}" removed')
        else:
            self._flash('Failed to save changes.', is_error=True)

    def _account_remove_tag(self, account: Any) -> None:
        """Select and remove a tag from an account."""
        collection = self._get_collection()
        acc = collection.get_account(account.id) if collection else None
        if acc is None:
            self._flash('Account not found in data.', is_error=True)
            return
        if not acc.tags:
            self._flash('No tags to remove.', is_error=True)
            return

        selected = self._pick_from_list(
            f'Remove Tag: {acc.name}',
            [f'{key} = {value}' for key, value in sorted(acc.tags.items())],
            'Select a tag to remove',
        )
        if not selected:
            return

        tag_key = selected.split(' = ', 1)[0]
        from datetime import datetime

        acc.tags.pop(tag_key, None)
        acc.last_updated = datetime.now()
        if self._save_collection():
            self._flash(f'Tag "{tag_key}" removed')
        else:
            self._flash('Failed to save changes.', is_error=True)

    def _account_create_profile(self, account: Any) -> None:
        """Create a profile for a single account using one of its roles."""
        collection = self._get_collection()
        acc = collection.get_account(account.id) if collection else None
        if acc is None:
            self._flash('Account not found in data.', is_error=True)
            return
        if not acc.roles:
            self._flash('No roles available. Fetch roles first.', is_error=True)
            return

        role_name = self._pick_from_list(
            f'Create Profile: {acc.name}',
            [role.name for role in acc.roles],
            'Select a role for the new profile',
        )
        if not role_name:
            return
        self._create_profiles_for_account_ids([acc.id], role_name)

    # ─── Screen: Teams manager ────────────────────────────────────────────

    def _screen_teams(self) -> Optional[str]:
        """List teams and allow managing them."""
        selected = 0
        scroll   = 0

        while True:
            collection = self._get_collection()
            accounts   = list(collection.accounts) if collection else []

            # Build team → [accounts] mapping
            team_map: Dict[str, List[Any]] = {}
            for a in accounts:
                team = a.product_team or ''
                team_map.setdefault(team, []).append(a)

            team_names = sorted(k for k in team_map if k)
            # Put unassigned at the end
            if '' in team_map:
                display_names = team_names + ['(unassigned)']
                all_teams     = team_names + ['']
            else:
                display_names = team_names
                all_teams     = team_names

            total   = len(all_teams)
            h, w    = self.stdscr.getmaxyx()
            start   = self._draw_header('Teams', f'{len(team_names)} team(s)  ·  {len(accounts)} accounts total')
            visible = h - start - 1

            self.stdscr.clear()
            start = self._draw_header('Teams', f'{len(team_names)} team(s)  ·  {len(accounts)} accounts total')

            if not all_teams:
                self.stdscr.attron(curses.color_pair(_CP_DIM))
                self.stdscr.addstr(start, 2, 'No accounts loaded. Run "init" first.')
                self.stdscr.attroff(curses.color_pair(_CP_DIM))
            else:
                rows = []
                for t, dn in zip(all_teams, display_names):
                    count = len(team_map.get(t, []))
                    rows.append(f'{dn:<30}  {count} account(s)')
                selected = min(selected, total - 1) if total else 0
                self._draw_list_rows(rows, selected, start, visible, scroll)

            self._draw_footer(
                ' ↑↓ Navigate   Enter View members   N New team   R Rename   D Delete   Q Back '
            )
            self.stdscr.refresh()

            key = self.stdscr.getch()

            if key in (_ESC, ord('q'), ord('Q')):
                return 'main'
            elif total and _is_enter(key):
                team_key = all_teams[selected]
                members  = team_map.get(team_key, [])
                self._screen_team_members(team_key or '(unassigned)', members, team_key)
                self._reload_collection()
            elif key in (ord('n'), ord('N')):
                self._create_team()
                self._reload_collection()
                selected = 0
                scroll   = 0
            elif total and key in (ord('r'), ord('R')):
                team_key = all_teams[selected]
                if team_key == '':
                    self._flash('Cannot rename (unassigned).', is_error=True)
                else:
                    self._rename_team(team_key)
                    self._reload_collection()
            elif total and key in (ord('d'), ord('D')):
                team_key = all_teams[selected]
                if team_key == '':
                    self._flash('Cannot delete (unassigned).', is_error=True)
                else:
                    self._delete_team(team_key)
                    self._reload_collection()
                    selected = max(0, selected - 1)
            else:
                selected, scroll = self._nav(key, selected, scroll, total, visible)

    def _screen_team_members(
        self, display_name: str, members: List[Any], team_key: str
    ) -> None:
        """Show members of a team; allow adding/removing accounts."""
        selected = 0
        scroll   = 0

        while True:
            h, w    = self.stdscr.getmaxyx()
            total   = len(members)
            start   = self._draw_header(
                f'Team: {display_name}',
                f'{total} member(s)',
            )
            visible = h - start - 1

            self.stdscr.clear()
            start = self._draw_header(f'Team: {display_name}', f'{total} member(s)')

            if not members:
                self.stdscr.attron(curses.color_pair(_CP_DIM))
                self.stdscr.addstr(start, 2, 'No members in this team.')
                self.stdscr.attroff(curses.color_pair(_CP_DIM))
            else:
                rows = [f'{a.id}  {a.name}' for a in members]
                selected = min(selected, total - 1)
                self._draw_list_rows(rows, selected, start, visible, scroll)

            self._draw_footer(' ↑↓ Navigate   A Add account   R Remove selected   Q Back ')
            self.stdscr.refresh()

            key = self.stdscr.getch()
            if key in (_ESC, ord('q'), ord('Q')):
                return
            elif key in (ord('a'), ord('A')):
                self._add_account_to_team(team_key)
                # Refresh members list
                collection = self._reload_collection()
                if collection:
                    members = [a for a in collection.accounts if (a.product_team or '') == team_key]
            elif total and key in (ord('r'), ord('R')):
                acc = members[selected]
                if self._confirm(f'Remove {acc.name} from team?'):
                    collection = self._get_collection()
                    a = collection.get_account(acc.id) if collection else None
                    if a:
                        a.product_team = None
                        from datetime import datetime
                        a.last_updated = datetime.now()
                        if self._save_collection():
                            self._flash(f'{acc.name} removed from team.')
                        else:
                            self._flash('Failed to save.', is_error=True)
                    collection = self._reload_collection()
                    if collection:
                        members = [a for a in collection.accounts if (a.product_team or '') == team_key]
                    selected = min(selected, len(members) - 1) if members else 0
            else:
                selected, scroll = self._nav(key, selected, scroll, total, visible)

    def _create_team(self) -> None:
        """Prompt for a new team name and assign selected accounts to it."""
        name = self._prompt('New team name')
        if not name or not name.strip():
            return
        name = name.strip()
        collection = self._get_collection()
        if collection is None:
            self._flash('No account data loaded.', is_error=True)
            return
        # Assign accounts interactively
        self._add_account_to_team(name)

    def _add_account_to_team(self, team_key: str) -> None:
        """Show a multi-select dialog to add accounts to *team_key*."""
        collection = self._get_collection()
        if collection is None:
            self._flash('No account data loaded.', is_error=True)
            return

        # Accounts not already in this team are candidates
        candidates = [a for a in collection.accounts if (a.product_team or '') != team_key]
        if not candidates:
            self._flash('No other accounts to add.')
            return

        selected  = 0
        scroll    = 0
        checked: Set[int] = set()
        visible_rows = 0

        while True:
            h, w = self.stdscr.getmaxyx()
            start = self._draw_header(
                f'Add to team: {team_key or "(unassigned)"}',
                f'Space toggle  Enter confirm  Q cancel',
            )
            visible_rows = h - start - 1
            total = len(candidates)

            self.stdscr.clear()
            start = self._draw_header(
                f'Add to team: {team_key or "(unassigned)"}',
                'Space toggle selection  Enter confirm  Q cancel',
            )
            rows = [f'{a.id}  {a.name}  [{a.product_team or "—"}]' for a in candidates]
            selected = min(selected, total - 1)
            self._draw_multiselect_rows(rows, selected, checked, start, visible_rows, scroll)
            self._draw_footer(
                f' ↑↓ Navigate   Space Toggle   A Select all   Enter Confirm   Q Cancel '
            )
            self.stdscr.refresh()

            key = self.stdscr.getch()
            if key in (_ESC, ord('q'), ord('Q')):
                return
            elif key == ord(' '):
                if selected in checked:
                    checked.discard(selected)
                else:
                    checked.add(selected)
            elif key in (ord('a'), ord('A')):
                if len(checked) == total:
                    checked.clear()
                else:
                    checked = set(range(total))
            elif _is_enter(key):
                if not checked:
                    return
                from datetime import datetime
                for idx in checked:
                    acc = collection.get_account(candidates[idx].id)
                    if acc:
                        acc.product_team = team_key or None
                        acc.last_updated = datetime.now()
                if self._save_collection():
                    self._flash(f'{len(checked)} account(s) added to "{team_key}".')
                else:
                    self._flash('Failed to save changes.', is_error=True)
                return
            else:
                selected, scroll = self._nav(key, selected, scroll, total, visible_rows)

    def _rename_team(self, old_name: str) -> None:
        """Rename a team (update product_team on all member accounts)."""
        new_name = self._prompt(f'Rename team "{old_name}" to', default=old_name)
        if not new_name or new_name.strip() == old_name:
            return
        new_name = new_name.strip()
        collection = self._get_collection()
        if collection is None:
            self._flash('No account data loaded.', is_error=True)
            return
        from datetime import datetime
        count = 0
        for a in collection.accounts:
            if a.product_team == old_name:
                a.product_team = new_name
                a.last_updated = datetime.now()
                count += 1
        if self._save_collection():
            self._flash(f'Renamed team for {count} account(s).')
        else:
            self._flash('Failed to save.', is_error=True)

    def _delete_team(self, team_name: str) -> None:
        """Remove the team assignment from all member accounts."""
        collection = self._get_collection()
        if collection is None:
            return
        members = [a for a in collection.accounts if a.product_team == team_name]
        if not self._confirm(f'Delete team "{team_name}" ({len(members)} members)?'):
            return
        from datetime import datetime
        for a in members:
            a.product_team = None
            a.last_updated = datetime.now()
        if self._save_collection():
            self._flash(f'Team "{team_name}" deleted ({len(members)} accounts unassigned).')
        else:
            self._flash('Failed to save.', is_error=True)

    # ─── Screen: Templates ────────────────────────────────────────────────

    def _screen_templates(self) -> Optional[str]:
        """List saved command templates."""
        from ..config.template_manager import get_template_manager

        selected = 0
        scroll   = 0

        while True:
            try:
                tmgr      = get_template_manager(self.config_manager)
                templates = tmgr.list_templates()
            except Exception:
                templates = []

            total   = len(templates)
            h, w    = self.stdscr.getmaxyx()
            start   = self._draw_header('Templates', f'{total} template(s)')
            visible = h - start - 1

            self.stdscr.clear()
            start = self._draw_header('Templates', f'{total} template(s)')

            if not templates:
                self.stdscr.attron(curses.color_pair(_CP_DIM))
                self.stdscr.addstr(start, 2, 'No templates yet.  Use "multi-aws template add" to create one.')
                self.stdscr.attroff(curses.color_pair(_CP_DIM))
            else:
                rows = []
                for t in templates:
                    cmd_preview = _truncate(t.command, 40)
                    region_str  = f'[{t.region}]' if t.region else ''
                    rows.append(f'{t.name:<25}  {cmd_preview:<42}  {region_str}')
                selected = min(selected, total - 1) if total else 0
                self._draw_list_rows(rows, selected, start, visible, scroll)

            self._draw_footer(
                ' ↑↓ Navigate   Enter Details   N New   R Run   D Delete   Q Back '
            )
            self.stdscr.refresh()

            key = self.stdscr.getch()
            if key in (_ESC, ord('q'), ord('Q')):
                return 'main'
            elif total and _is_enter(key):
                self._show_template_detail(templates[selected])
            elif total and key in (ord('r'), ord('R')):
                return self._run_from_template(templates[selected])
            elif key in (ord('n'), ord('N')):
                self._create_template()
            elif total and key in (ord('d'), ord('D')):
                tmpl = templates[selected]
                if self._confirm(f'Delete template "{tmpl.name}"?'):
                    try:
                        tmgr = get_template_manager(self.config_manager)
                        tmgr.delete_template(tmpl.name)
                        tmgr.save_templates()
                        self._flash(f'Template "{tmpl.name}" deleted.')
                        selected = max(0, selected - 1)
                    except Exception as exc:
                        self._flash(f'Error: {exc}', is_error=True)
            else:
                selected, scroll = self._nav(key, selected, scroll, total, visible)

    def _create_template(self) -> None:
        """Create a template directly in the TUI."""
        from ..config.schema import is_destructive_command
        from ..config.template_manager import get_template_manager
        from ..models.template import CommandTemplate

        name = self._prompt('Template name')
        if not name or not name.strip():
            return
        name = name.strip()

        command = self._prompt('AWS command (without "aws")')
        if not command or not command.strip():
            self._flash('Template command is required.', is_error=True)
            return
        command = command.strip()

        description = self._prompt('Description (optional)', default='') or ''
        description = description.strip()

        allow_destructive = False
        if self.config_manager is not None:
            try:
                allow_destructive = self.config_manager.get_bool(
                    'security', 'allow-destructive-commands', False
                )
            except Exception:
                allow_destructive = False
        if is_destructive_command(command) and not allow_destructive:
            self._flash('Command is destructive and blocked by config.', is_error=True)
            return

        try:
            tmgr = get_template_manager(self.config_manager)
            if tmgr.template_exists(name) and not self._confirm(f'Overwrite template "{name}"?'):
                self._flash('Template creation cancelled.')
                return
            tmgr.add_template(
                CommandTemplate(
                    name=name,
                    command=command,
                    description=description,
                )
            )
            tmgr.save_templates()
            self._flash(f'Template "{name}" saved.')
        except Exception as exc:
            self._flash(f'Failed to save template: {exc}', is_error=True)

    # ─── Screen: Results browser ───────────────────────────────────────────

    def _screen_results(self) -> Optional[str]:
        """Browse execution summaries with quick visual stats."""
        selected = 0
        scroll = 0

        while True:
            records = self._load_saved_results()
            total = len(records)
            output_path = self._results_output_path()
            h, _ = self.stdscr.getmaxyx()

            self.stdscr.clear()
            start = self._draw_header('Run Results', f'{total} execution summary file(s)  ·  {output_path}')
            visible = h - start - 1

            if not records:
                self.stdscr.attron(curses.color_pair(_CP_DIM))
                self.stdscr.addstr(start, 2, 'No saved run summaries found. Use run with --save first.')
                self.stdscr.attroff(curses.color_pair(_CP_DIM))
            else:
                rows = []
                for r in records:
                    ts = _truncate(str(r['timestamp']).replace('T', ' ')[:19], 19)
                    cmd = _truncate(r['command'], 36)
                    bar = self._ratio_bar(r['success'], r['total'], width=10)
                    rows.append(
                        f'{ts}  S:{r["success"]}/{r["total"]:<3}  F:{r["failed"]:<3}  T:{r["timeout"]:<3}  {bar}  {cmd}'
                    )
                selected = min(selected, total - 1) if total else 0
                self._draw_list_rows(rows, selected, start, visible, scroll)

            self._draw_footer(' ↑↓ Navigate   Enter Summary   O Outputs   R Refresh   Q Back ')
            self.stdscr.refresh()

            key = self.stdscr.getch()
            if key in (_ESC, ord('q'), ord('Q')):
                return 'main'
            elif key in (ord('r'), ord('R')):
                continue
            elif total and _is_enter(key):
                self._show_result_detail(records[selected])
            elif total and key in (ord('o'), ord('O')):
                self._screen_result_outputs(records[selected])
            else:
                selected, scroll = self._nav(key, selected, scroll, total, visible)

    def _show_result_detail(self, record: Dict[str, Any]) -> None:
        """Show details for one execution summary, including visual breakdown."""
        summary = record['summary']
        total = record['total']
        success = record['success']
        failed = record['failed']
        timeout = record['timeout']

        lines = [
            f'File:      {record["file_name"]}',
            f'Timestamp: {record["timestamp"]}',
            f'Command:   aws {record["command"]}',
            f'Mode:      {record["mode"]}',
            f'Accounts:  {total}',
            '',
            'Status overview:',
            f'  Success  {success:>4}/{total:<4}  {self._ratio_bar(success, total, width=28)}',
            f'  Failed   {failed:>4}/{total:<4}  {self._ratio_bar(failed, total, width=28)}',
            f'  Timeout  {timeout:>4}/{total:<4}  {self._ratio_bar(timeout, total, width=28)}',
            '',
            f'Per-account results ({len(summary.results)}):',
        ]

        for res in summary.results:
            status = str(getattr(res, 'status', 'UNKNOWN')).upper()
            marker = '✓' if 'SUCCESS' in status else ('⏰' if 'TIMEOUT' in status else '✗')
            name = getattr(res, 'account_name', None) or getattr(res, 'account_id', 'unknown')
            account_id = getattr(res, 'account_id', 'unknown')
            exec_time = float(getattr(res, 'execution_time', 0.0) or 0.0)
            lines.append(f'  {marker} {name} ({account_id})  [{status}]  {exec_time:.2f}s')
            err = (getattr(res, 'error', '') or '').strip()
            if err and 'SUCCESS' not in status:
                lines.append(f'      {_truncate(err, 140)}')

        self._detail_page('Execution Result Detail', lines)

    def _screen_result_outputs(self, record: Dict[str, Any]) -> None:
        """Browse per-account outputs for one execution summary."""
        summary = record['summary']
        results = list(summary.results)
        total = len(results)
        if not total:
            self._flash('No per-account results in this summary.', is_error=True)
            return

        selected = 0
        scroll = 0

        while True:
            h, w = self.stdscr.getmaxyx()
            self.stdscr.clear()
            start = self._draw_header(
                f'Outputs: {_truncate(record["command"], 40)}',
                f'{total} account result(s)',
            )
            visible = h - start - 1

            rows = []
            for res in results:
                status = str(getattr(res, 'status', 'UNKNOWN')).upper()
                marker = '✓' if 'SUCCESS' in status else ('⏰' if 'TIMEOUT' in status else '✗')
                name = getattr(res, 'account_name', None) or getattr(res, 'account_id', 'unknown')
                account_id = getattr(res, 'account_id', 'unknown')
                has_out = bool((getattr(res, 'output', '') or '').strip())
                has_err = bool((getattr(res, 'error', '') or '').strip())
                flags = ('[out]' if has_out else '     ') + (' [err]' if has_err else '      ')
                rows.append(f'{marker} {name:<28} ({account_id})  {status:<10}  {flags}')

            selected = min(selected, total - 1) if total else 0
            self._draw_list_rows(rows, selected, start, visible, scroll)
            self._draw_footer(' ↑↓ Navigate   Enter View Output   E View Error   Q Back ')
            self.stdscr.refresh()

            key = self.stdscr.getch()
            if key in (_ESC, ord('q'), ord('Q')):
                return
            elif total and _is_enter(key):
                res = results[selected]
                output = (getattr(res, 'output', '') or '').strip()
                name = getattr(res, 'account_name', None) or getattr(res, 'account_id', 'unknown')
                if output:
                    output_lines = self._format_output_lines(output)
                    self._detail_page(f'Output: {name}', output_lines)
                else:
                    self._flash('No output for this account.')
            elif total and key in (ord('e'), ord('E')):
                res = results[selected]
                error = (getattr(res, 'error', '') or '').strip()
                name = getattr(res, 'account_name', None) or getattr(res, 'account_id', 'unknown')
                if error:
                    error_lines = error.splitlines()
                    self._detail_page(f'Error: {name}', error_lines)
                else:
                    self._flash('No error output for this account.')
            else:
                selected, scroll = self._nav(key, selected, scroll, total, visible)

    @staticmethod
    def _format_output_lines(output: str) -> List[str]:
        """Try to pretty-print JSON output; fall back to raw lines."""
        import json as _json
        stripped = output.strip()
        try:
            parsed = _json.loads(stripped)
            pretty = _json.dumps(parsed, indent=2)
            return pretty.splitlines()
        except Exception:
            return stripped.splitlines()

    def _show_template_detail(self, tmpl: Any) -> None:
        lines = [
            f'Name:     {tmpl.name}',
            f'Command:  {tmpl.command}',
        ]
        if tmpl.description:
            lines.append(f'Desc:     {tmpl.description}')
        if tmpl.region:
            lines.append(f'Region:   {tmpl.region}')
        if tmpl.output_format:
            lines.append(f'Format:   {tmpl.output_format}')
        if tmpl.parallel is not None:
            lines.append(f'Parallel: {"yes" if tmpl.parallel else "no"}')
        if tmpl.timeout:
            lines.append(f'Timeout:  {tmpl.timeout}s')
        if tmpl.accounts:
            lines.append(f'Accounts: {tmpl.accounts}')
        if tmpl.team:
            lines.append(f'Team:     {tmpl.team}')
        if tmpl.tags:
            lines.append(f'Tags:     {", ".join(tmpl.tags)}')
        if tmpl.save is not None:
            lines.append(f'Save:     {"yes" if tmpl.save else "no"}')
        lines += [
            '',
            f'Created:  {tmpl.created_at}',
            f'Updated:  {tmpl.updated_at}',
        ]
        self._detail_page(f'Template: {tmpl.name}', lines)

    def _run_from_template(self, tmpl: Any) -> Optional[str]:
        """Pre-fill the run workflow with the template's settings."""
        return self._screen_run_workflow(template=tmpl)

    # ─── Screen: Config editor ────────────────────────────────────────────

    def _screen_config(self) -> Optional[str]:
        """Interactive configuration editor."""
        if self.config_manager is None:
            self._flash('No configuration manager available.', is_error=True)
            return 'main'

        # Sections and their editable keys with descriptions
        _CONFIG_FIELDS: List[Tuple[str, str, str]] = [
            ('general',   'prefix',                     'Profile prefix'),
            ('general',   'sso-session',                'SSO session name'),
            ('general',   'account-file',               'Account file path'),
            ('general',   'region',                     'Default region'),
            ('output',    'pattern',                    'Output filename pattern'),
            ('output',    'format',                     'Output format (json/yaml/txt/csv)'),
            ('output',    'path',                       'Output directory'),
            ('execution', 'mode',                       'Execution mode (parallel/sequential)'),
            ('execution', 'stop-on-errors',             'Stop after N errors (0=never)'),
            ('security',  'allow-destructive-commands', 'Allow destructive commands (true/false)'),
            ('logging',   'level',                      'Log level (DEBUG/INFO/WARNING/ERROR)'),
            ('logging',   'file',                       'Log file path'),
            ('logging',   'console',                    'Console logging (true/false)'),
            ('logging',   'max-size',                   'Max log size MB'),
            ('logging',   'backup-count',               'Log backup count'),
        ]

        selected = 0
        scroll = 0
        dirty = False

        while True:
            total = len(_CONFIG_FIELDS)
            h, w = self.stdscr.getmaxyx()
            self.stdscr.clear()
            start = self._draw_header('Configuration', 'Edit settings  ·  S Save  ·  Q Back')
            visible = h - start - 1

            rows = []
            for section, key, label in _CONFIG_FIELDS:
                try:
                    val = self.config_manager.get(section, key, '')
                except Exception:
                    val = ''
                rows.append(f'{label:<38}  {_truncate(val, max(10, w - 44))}')

            selected = min(selected, total - 1) if total else 0
            self._draw_list_rows(rows, selected, start, visible, scroll)

            footer = ' ↑↓ Navigate   Enter Edit   S Save   Q Back '
            if dirty:
                footer = ' ↑↓ Navigate   Enter Edit   S Save*   Q Back (unsaved changes) '
            self._draw_footer(footer)
            self.stdscr.refresh()

            key = self.stdscr.getch()
            if key in (_ESC, ord('q'), ord('Q')):
                if dirty and not self._confirm('Discard unsaved changes?'):
                    continue
                return 'main'
            elif key in (ord('s'), ord('S')):
                try:
                    self.config_manager.save_config()
                    dirty = False
                    self._flash('Configuration saved.')
                except Exception as exc:
                    self._flash(f'Save failed: {exc}', is_error=True)
            elif _is_enter(key) and total:
                section, cfg_key, label = _CONFIG_FIELDS[selected]
                try:
                    current = self.config_manager.get(section, cfg_key, '')
                except Exception:
                    current = ''
                new_val = self._prompt(label, default=current)
                if new_val is not None and new_val != current:
                    self.config_manager.set(section, cfg_key, new_val.strip())
                    dirty = True
            else:
                selected, scroll = self._nav(key, selected, scroll, total, visible)

    # ─── Screen: Discovery & Profiles ─────────────────────────────────────

    def _screen_discovery(self) -> Optional[str]:
        """Account discovery, role fetching, and profile creation."""
        options: List[Tuple[str, str]] = [
            ('D', 'Discover accounts (SSO)'),
            ('R', 'Fetch roles for accounts'),
            ('P', 'Create AWS CLI profiles'),
            ('', '──────────────────────────'),
            ('Q', 'Back'),
        ]
        selected = 0

        while True:
            self.stdscr.clear()
            h, w = self.stdscr.getmaxyx()
            start = self._draw_header('Discovery & Profiles', 'Manage account discovery and AWS CLI profiles')
            visible = h - start - 1

            for i, (shortcut, label) in enumerate(options):
                row = start + i
                if row >= h - 2:
                    break
                if label.startswith('──'):
                    self.stdscr.attron(curses.color_pair(_CP_DIM))
                    self.stdscr.addstr(row, 2, _truncate(label, w - 3))
                    self.stdscr.attroff(curses.color_pair(_CP_DIM))
                    continue
                if i == selected:
                    attr = curses.color_pair(_CP_SELECTED) | curses.A_BOLD
                    line = f' ▶ [{shortcut}] {label}'
                else:
                    attr = curses.color_pair(_CP_NORMAL)
                    line = f'   [{shortcut}] {label}'
                self.stdscr.attron(attr)
                self.stdscr.addstr(row, 0, _truncate(line, w - 1).ljust(w - 1))
                self.stdscr.attroff(attr)

            self._draw_footer(' ↑↓ Navigate   Enter/letter Select   Q Back ')
            self.stdscr.refresh()

            key = self.stdscr.getch()

            if key in (_ESC, ord('q'), ord('Q')):
                return 'main'
            elif key == curses.KEY_UP:
                selected = max(0, selected - 1)
                if options[selected][0] == '':
                    selected = max(0, selected - 1)
            elif key == curses.KEY_DOWN:
                selected = min(len(options) - 1, selected + 1)
                if options[selected][0] == '':
                    selected = min(len(options) - 1, selected + 1)
            elif _is_enter(key) or key == ord(' '):
                shortcut, _ = options[selected]
                if shortcut == 'D':
                    self._do_discover_accounts()
                elif shortcut == 'R':
                    self._do_fetch_roles()
                elif shortcut == 'P':
                    self._do_create_profiles()
                elif shortcut == 'Q':
                    return 'main'
            else:
                for shortcut, _ in options:
                    if shortcut and key in (ord(shortcut.lower()), ord(shortcut.upper())):
                        if shortcut == 'D':
                            self._do_discover_accounts()
                        elif shortcut == 'R':
                            self._do_fetch_roles()
                        elif shortcut == 'P':
                            self._do_create_profiles()
                        elif shortcut == 'Q':
                            return 'main'
                        break

    def _do_discover_accounts(self) -> None:
        """Run account discovery via SSO and reload collection."""
        self.stdscr.clear()
        h, w = self.stdscr.getmaxyx()
        self._draw_header('Discovering Accounts…')
        self.stdscr.attron(curses.color_pair(_CP_INFO))
        self.stdscr.addstr(3, 2, 'Connecting to AWS SSO to discover accounts…')
        self.stdscr.attroff(curses.color_pair(_CP_INFO))
        self.stdscr.refresh()

        try:
            collection = self.account_manager.discover_accounts(force_refresh=True)
            self._reload_collection()
            count = len(collection.accounts) if collection else 0
            self._flash(f'Discovery complete: {count} account(s) found.')
        except Exception as exc:
            self._flash(f'Discovery failed: {_truncate(str(exc), 80)}', is_error=True)

    def _do_fetch_roles(self) -> None:
        """Prompt for accounts and fetch their roles."""
        collection = self._get_collection()
        accounts = list(collection.accounts) if collection else []
        if not accounts:
            self._flash('No accounts loaded. Run account discovery first.', is_error=True)
            return

        # Multi-select accounts
        selected_ids = self._pick_accounts_multiselect('Fetch Roles', accounts)
        if not selected_ids:
            return

        self.stdscr.clear()
        h, w = self.stdscr.getmaxyx()
        self._draw_header('Fetching Roles…')
        self.stdscr.attron(curses.color_pair(_CP_INFO))
        self.stdscr.addstr(3, 2, f'Fetching roles for {len(selected_ids)} account(s)…')
        self.stdscr.attroff(curses.color_pair(_CP_INFO))
        self.stdscr.refresh()

        try:
            results = self.account_manager.update_roles_for_accounts(
                selected_ids, force_refresh=True
            )
            ok = sum(1 for v in results.values() if v)
            fail = len(results) - ok
            self._reload_collection()
            msg = f'Roles fetched: {ok} ok'
            if fail:
                msg += f', {fail} failed'
            self._flash(msg, is_error=(fail > 0 and ok == 0))
        except Exception as exc:
            self._flash(f'Role fetch failed: {_truncate(str(exc), 80)}', is_error=True)

    def _do_create_profiles(self) -> None:
        """Prompt for accounts + role name, then create AWS CLI profiles."""
        collection = self._get_collection()
        accounts = list(collection.accounts) if collection else []
        if not accounts:
            self._flash('No accounts loaded. Run account discovery first.', is_error=True)
            return

        # Multi-select accounts
        selected_ids = self._pick_accounts_multiselect('Create Profiles', accounts)
        if not selected_ids:
            return

        self._create_profiles_for_account_ids(selected_ids)

    def _create_profiles_for_account_ids(
        self, selected_ids: List[str], role_name: Optional[str] = None
    ) -> None:
        """Create AWS CLI profiles for the selected account IDs."""
        collection = self._get_collection()
        accounts = list(collection.accounts) if collection else []
        if not accounts:
            self._flash('No accounts loaded. Run account discovery first.', is_error=True)
            return

        if role_name is None:
            role_name = self._prompt('Role name for profiles (e.g. PowerUserAccess)')
        if not role_name or not role_name.strip():
            return
        role_name = role_name.strip()

        # Get region override
        default_region = 'us-east-1'
        if self.config_manager:
            try:
                default_region = self.config_manager.get('general', 'region', 'us-east-1')
            except Exception:
                pass
        region_input = self._prompt('AWS region override (blank for default)', default=default_region)
        region = (region_input or '').strip() or default_region

        # Get prefix
        prefix = 'multi-aws'
        if self.config_manager:
            try:
                prefix = self.config_manager.get('general', 'prefix', 'multi-aws')
            except Exception:
                pass

        # Build profiles
        import os as _os
        aws_config_path = _os.path.expanduser('~/.aws/config')
        lines: List[str] = []
        created = 0
        skipped = 0

        selected_id_set = set(selected_ids)
        selected_accounts = [a for a in accounts if a.id in selected_id_set]
        for acc in selected_accounts:
            role_found = any(r.name == role_name for r in acc.roles)
            if not role_found and acc.roles:
                skipped += 1
                continue
            san_name = _sanitize_profile_name_component(acc.name)
            profile_name = f'{prefix}-{san_name}-{role_name}'
            lines += [
                f'[profile {profile_name}]',
                f'sso_session = {self.account_manager.sso_client.sso_session_name}',
                f'sso_account_id = {acc.id}',
                f'sso_role_name = {role_name}',
                f'region = {region}',
                '',
            ]
            # Store profile name on account
            acc.set_profile_name(profile_name)
            created += 1

        if not lines:
            self._flash('No profiles created. Check role name and account roles.', is_error=True)
            return

        if self._confirm(f'Append {created} profile(s) to {aws_config_path}?'):
            try:
                _os.makedirs(_os.path.dirname(aws_config_path), exist_ok=True)
                with open(aws_config_path, 'a') as fh:
                    fh.write('\n' + '\n'.join(lines))
                self._save_collection()
                self._reload_collection()
                msg = f'{created} profile(s) appended to ~/.aws/config'
                if skipped:
                    msg += f'  ({skipped} skipped – role not found)'
                self._flash(msg)
            except Exception as exc:
                self._flash(f'Failed to write profiles: {_truncate(str(exc), 80)}', is_error=True)

    def _pick_accounts_multiselect(
        self, title: str, accounts: List[Any]
    ) -> Optional[List[str]]:
        """Show a multi-select account picker; return list of IDs or None."""
        selected = 0
        scroll = 0
        checked: Set[int] = set()
        total = len(accounts)

        while True:
            h, w = self.stdscr.getmaxyx()
            self.stdscr.clear()
            start = self._draw_header(
                title,
                f'{len(checked)} selected  ·  Space toggle  ·  A all  ·  Enter confirm',
            )
            visible = h - start - 1
            rows = [f'{a.id}  {a.name:<30}  [{a.product_team or "—"}]' for a in accounts]
            selected = min(selected, total - 1) if total else 0
            self._draw_multiselect_rows(rows, selected, checked, start, visible, scroll)
            self._draw_footer(' ↑↓ Navigate   Space Toggle   A All   Enter Confirm   Q Cancel ')
            self.stdscr.refresh()

            key = self.stdscr.getch()
            if key in (_ESC, ord('q'), ord('Q')):
                return None
            elif key == ord(' ') and total:
                if selected in checked:
                    checked.discard(selected)
                else:
                    checked.add(selected)
            elif key in (ord('a'), ord('A')):
                if len(checked) == total:
                    checked.clear()
                else:
                    checked = set(range(total))
            elif _is_enter(key):
                if not checked:
                    self._flash('Select at least one account.', is_error=True)
                    continue
                return [accounts[i].id for i in sorted(checked)]
            else:
                selected, scroll = self._nav(key, selected, scroll, total, visible)



    def _screen_run_workflow(self, template: Any = None) -> Optional[str]:
        """
        Multi-step guided workflow:
          1. Select accounts
          2. Enter command (pre-filled from template if given)
          3. Set options (region, parallel, dry-run, role)
          4. Preview execution plan
          5. Confirm → store result for caller
        """
        # ── Step 1: Select accounts ──────────────────────────────────────
        account_ids = self._step_select_accounts(
            preselected_team=getattr(template, 'team', '') if template else '',
        )
        if account_ids is None:
            return 'main'

        # ── Step 2: Enter command ─────────────────────────────────────────
        default_cmd = template.command if template else ''
        command = self._step_enter_command(default_cmd)
        if command is None:
            return 'main'

        # ── Step 3: Options ───────────────────────────────────────────────
        opts = self._step_options(template)
        if opts is None:
            return 'main'

        # ── Step 4: Preview & confirm ─────────────────────────────────────
        confirmed = self._step_preview(account_ids, command, opts)
        if not confirmed:
            return 'main'

        # Store result for the caller
        self._run_result = {
            'action':   'run',
            'accounts': account_ids,
            'command':  command,
            'parallel': opts['parallel'],
            'region':   opts['region'],
            'dry_run':  opts['dry_run'],
            'role':     opts['role'],
        }
        return None  # signals the TUI to exit

    def _step_select_accounts(
        self, preselected_team: str = ''
    ) -> Optional[List[str]]:
        """Step 1: multi-select accounts; return list of IDs or None to cancel.

        Supports two modes:
          • Account mode  – individual account multi-select with filter support
          • Team mode     – pick whole teams at once (B key to switch)
        """
        collection = self._get_collection()
        accounts   = list(collection.accounts) if collection else []

        selected  = 0
        scroll    = 0
        checked: Set[int] = set()
        filt      = ''
        filtering = False
        team_mode = False  # False = account mode, True = team mode

        # Pre-check accounts from the template's team
        if preselected_team:
            for i, a in enumerate(accounts):
                if (a.product_team or '') == preselected_team:
                    checked.add(i)

        # ── team mode state ───────────────────────────────────────────────
        team_selected  = 0
        team_scroll    = 0
        team_checked: Set[str] = set()

        def _build_teams() -> List[str]:
            tm: Dict[str, int] = {}
            for a in accounts:
                t = a.product_team or ''
                tm[t] = tm.get(t, 0) + 1
            names = sorted(k for k in tm if k)
            if '' in tm:
                names.append('(unassigned)')
            return names

        while True:
            if team_mode:
                # ─── Team selection mode ──────────────────────────────────
                team_names = _build_teams()
                t_total = len(team_names)

                h, w = self.stdscr.getmaxyx()
                self.stdscr.clear()
                start = self._draw_header(
                    'Select Teams  (Step 1 of 4)',
                    f'{len(team_checked)} team(s) selected  ·  B switch to account mode',
                )
                visible_rows = h - start - 1

                # Count accounts per team for display
                team_counts: Dict[str, int] = {}
                for a in accounts:
                    t = a.product_team or ''
                    team_counts[t] = team_counts.get(t, 0) + 1

                t_rows = []
                for tn in team_names:
                    key_name = '' if tn == '(unassigned)' else tn
                    cnt = team_counts.get(key_name, 0)
                    t_rows.append(f'{tn:<35}  {cnt} account(s)')

                t_checked_idx: Set[int] = {
                    i for i, tn in enumerate(team_names)
                    if ('' if tn == '(unassigned)' else tn) in team_checked
                }
                team_selected = min(team_selected, t_total - 1) if t_total else 0
                self._draw_multiselect_rows(t_rows, team_selected, t_checked_idx, start, visible_rows, team_scroll)
                self._draw_footer(
                    ' Space Toggle   A All   B Account mode   Enter Next   Q Cancel '
                )
                self.stdscr.refresh()

                key = self.stdscr.getch()
                if key in (_ESC, ord('q'), ord('Q')):
                    return None
                elif key in (ord('b'), ord('B')):
                    # Switch back to account mode, translating team selection → checked accounts
                    checked.clear()
                    for i, a in enumerate(accounts):
                        t = a.product_team or ''
                        if t in team_checked or (not t and '' in team_checked):
                            checked.add(i)
                    team_mode = False
                    selected = 0
                    scroll = 0
                elif key == ord(' ') and t_total:
                    tn = team_names[team_selected]
                    key_name = '' if tn == '(unassigned)' else tn
                    if key_name in team_checked:
                        team_checked.discard(key_name)
                    else:
                        team_checked.add(key_name)
                elif key in (ord('a'), ord('A')):
                    if len(team_checked) == t_total:
                        team_checked.clear()
                    else:
                        team_checked = {
                            ('' if tn == '(unassigned)' else tn)
                            for tn in team_names
                        }
                elif _is_enter(key):
                    if not team_checked:
                        self._flash('Select at least one team.', is_error=True)
                        continue
                    # Expand teams → account IDs
                    result_ids = [
                        a.id for a in accounts
                        if (a.product_team or '') in team_checked
                    ]
                    if not result_ids:
                        self._flash('No accounts in selected team(s).', is_error=True)
                        continue
                    return result_ids
                else:
                    team_selected, team_scroll = self._nav(
                        key, team_selected, team_scroll, t_total, visible_rows
                    )

            else:
                # ─── Account selection mode ───────────────────────────────
                visible_accounts = accounts
                if filt:
                    fl = filt.lower()
                    visible_accounts = [
                        a for a in accounts
                        if fl in a.name.lower() or fl in a.id
                        or fl in (a.product_team or '').lower()
                    ]
                # Re-map checked indices when filtered
                if filt:
                    filtered_checked: Set[int] = {
                        i for i, a in enumerate(visible_accounts)
                        if a.id in {accounts[j].id for j in checked}
                    }
                    display_checked = filtered_checked
                else:
                    display_checked = checked

                total = len(visible_accounts)
                h, w  = self.stdscr.getmaxyx()

                self.stdscr.clear()
                start = self._draw_header(
                    'Select Accounts  (Step 1 of 4)',
                    f'{len(checked)} selected  ·  {total} shown'
                    + (f'  ·  filter: "{filt}"' if filt else ''),
                )
                visible_rows = h - start - 1

                rows = [f'{a.id}  {a.name:<30}  [{a.product_team or "—"}]' for a in visible_accounts]
                if total:
                    selected = min(selected, total - 1)
                self._draw_multiselect_rows(rows, selected, display_checked, start, visible_rows, scroll)

                if filtering:
                    self._draw_footer(f' Filter: {filt}_  (Enter confirm  Esc cancel) ')
                else:
                    self._draw_footer(
                        ' Space Toggle   A All   T Add team   B Team mode   / Filter   Enter Next   Q Cancel '
                    )
                self.stdscr.refresh()

                key = self.stdscr.getch()

                if filtering:
                    if key in (_ESC, _CTRL_C):
                        filtering = False
                        filt = ''
                    elif _is_enter(key):
                        filtering = False
                    elif key in (curses.KEY_BACKSPACE, 127, 8):
                        filt = filt[:-1]
                    elif 32 <= key <= 126:
                        filt += chr(key)
                    continue

                if key in (_ESC, ord('q'), ord('Q')):
                    return None
                elif key == ord('/'):
                    filtering = True
                    filt = ''
                elif key in (ord('b'), ord('B')):
                    # Switch to team mode; sync current checked → team_checked
                    team_checked.clear()
                    for j in checked:
                        t = accounts[j].product_team or ''
                        team_checked.add(t)
                    team_mode = True
                    team_selected = 0
                    team_scroll = 0
                elif key == ord(' ') and total:
                    real_idx = accounts.index(visible_accounts[selected]) if filt else selected
                    if real_idx in checked:
                        checked.discard(real_idx)
                    else:
                        checked.add(real_idx)
                elif key in (ord('a'), ord('A')):
                    if len(checked) == len(accounts):
                        checked.clear()
                    else:
                        checked = set(range(len(accounts)))
                elif key in (ord('t'), ord('T')):
                    team_name = self._prompt('Add accounts by team name')
                    if team_name and team_name.strip():
                        for i, a in enumerate(accounts):
                            if (a.product_team or '').lower() == team_name.strip().lower():
                                checked.add(i)
                elif _is_enter(key):
                    if not checked:
                        self._flash('Select at least one account.', is_error=True)
                        continue
                    return [accounts[i].id for i in sorted(checked)]
                else:
                    selected, scroll = self._nav(key, selected, scroll, total, visible_rows)


    def _step_enter_command(self, default: str = '') -> Optional[str]:
        """Step 2: enter an AWS CLI command."""
        self.stdscr.clear()
        h, w = self.stdscr.getmaxyx()
        self._draw_header('Enter Command  (Step 2 of 4)', 'AWS CLI command without "aws" prefix')
        self.stdscr.attron(curses.color_pair(_CP_DIM))
        self.stdscr.addstr(3, 2, 'Examples:  sts get-caller-identity')
        self.stdscr.addstr(4, 2, '           ec2 describe-instances --region us-east-1')
        self.stdscr.addstr(5, 2, '           iam list-users')
        self.stdscr.attroff(curses.color_pair(_CP_DIM))
        self._draw_footer(' Type command  Enter Confirm  Esc Cancel ')
        self.stdscr.refresh()
        value = self._prompt('AWS command', default=default)
        if value is None:
            return None
        value = value.strip()
        if not value:
            return None
        return value

    def _step_options(self, template: Any = None) -> Optional[Dict[str, Any]]:
        """Step 3: configure run options; returns option dict or None to cancel."""
        parallel = bool(template.parallel) if (template and template.parallel is not None) else False
        dry_run  = False
        region   = template.region if template else ''
        role     = ''

        menu = [
            ('P', 'Parallel execution',   'parallel'),
            ('D', 'Dry-run (preview only)', 'dry_run'),
            ('G', 'AWS Region',            'region'),
            ('O', 'Role override',         'role'),
            ('',  '──────────────────────', None),
            ('N', 'Next →',               'next'),
            ('Q', 'Cancel',               'cancel'),
        ]
        sel = 0

        while True:
            self.stdscr.clear()
            h, w  = self.stdscr.getmaxyx()
            start = self._draw_header('Options  (Step 3 of 4)')

            values = {
                'parallel': '✓ ON' if parallel else '  off',
                'dry_run':  '✓ ON' if dry_run  else '  off',
                'region':   region or '(default)',
                'role':     role   or '(auto)',
            }

            display_items = []
            for shortcut, label, key in menu:
                if key in values:
                    val = values[key]
                    display_items.append((shortcut, f'{label:<30}  {val}', key))
                else:
                    display_items.append((shortcut, label, key))

            for i, (shortcut, label, _) in enumerate(display_items):
                row = start + i
                if row >= h - 2:
                    break
                is_sel = (i == sel)
                if label.startswith('──'):
                    attr = curses.color_pair(_CP_DIM)
                    self.stdscr.attron(attr)
                    self.stdscr.addstr(row, 2, _truncate(label, w - 3))
                    self.stdscr.attroff(attr)
                    continue
                if is_sel:
                    attr = curses.color_pair(_CP_SELECTED) | curses.A_BOLD
                    line = f' ▶ [{shortcut}] {label}'
                else:
                    attr = curses.color_pair(_CP_NORMAL)
                    line = f'   [{shortcut}] {label}'
                self.stdscr.attron(attr)
                self.stdscr.addstr(row, 0, _truncate(line, w - 1).ljust(w - 1))
                self.stdscr.attroff(attr)

            self._draw_footer(' ↑↓ Navigate   Enter/letter Toggle/edit   Q Cancel ')
            self.stdscr.refresh()

            key = self.stdscr.getch()

            def _toggle_or_action(action_key: Optional[str]) -> bool:
                nonlocal parallel, dry_run, region, role
                if action_key == 'parallel':
                    parallel = not parallel
                elif action_key == 'dry_run':
                    dry_run = not dry_run
                elif action_key == 'region':
                    val = self._prompt('Region (e.g. us-east-1)', default=region)
                    if val is not None:
                        region = val.strip()
                elif action_key == 'role':
                    val = self._prompt('Role name override', default=role)
                    if val is not None:
                        role = val.strip()
                elif action_key == 'next':
                    return True
                return False

            if key in (_ESC, ord('q'), ord('Q')):
                return None
            elif _is_enter(key) or key == ord(' '):
                action_key = display_items[sel][2]
                if action_key == 'cancel':
                    return None
                if _toggle_or_action(action_key):
                    return {'parallel': parallel, 'dry_run': dry_run, 'region': region, 'role': role}
            elif key == curses.KEY_UP:
                sel = (sel - 1) % len(display_items)
                if display_items[sel][2] is None:
                    sel = (sel - 1) % len(display_items)
            elif key == curses.KEY_DOWN:
                sel = (sel + 1) % len(display_items)
                if display_items[sel][2] is None:
                    sel = (sel + 1) % len(display_items)
            else:
                for shortcut, _, action_key in display_items:
                    if shortcut and key in (ord(shortcut.lower()), ord(shortcut.upper())):
                        if action_key == 'cancel':
                            return None
                        if action_key == 'next':
                            return {'parallel': parallel, 'dry_run': dry_run,
                                    'region': region, 'role': role}
                        _toggle_or_action(action_key)
                        break

    def _step_preview(
        self, account_ids: List[str], command: str, opts: Dict[str, Any]
    ) -> bool:
        """Step 4: show execution preview; return True if confirmed."""
        collection = self._get_collection()
        lines = [
            '  Execution Plan',
            '  ' + '─' * 50,
            '',
            f'  Command:   aws {command}',
            f'  Accounts:  {len(account_ids)}',
            f'  Mode:      {"parallel" if opts["parallel"] else "sequential"}',
        ]
        if opts['region']:
            lines.append(f'  Region:    {opts["region"]}')
        if opts['role']:
            lines.append(f'  Role:      {opts["role"]}')
        if opts['dry_run']:
            lines.append(f'  Dry-run:   YES (no actual changes)')
        lines.append('')
        lines.append('  Accounts:')
        for aid in account_ids:
            name = aid
            if collection:
                acc = collection.get_account(aid)
                if acc:
                    name = f'{acc.name} ({aid})'
            lines.append(f'    • {name}')

        scroll = 0
        while True:
            self.stdscr.clear()
            h, w = self.stdscr.getmaxyx()
            start   = self._draw_header('Preview  (Step 4 of 4)', 'Review execution plan')
            visible = h - start - 2

            for i, line in enumerate(lines[scroll: scroll + visible]):
                r = start + i
                if r >= h - 2:
                    break
                self.stdscr.attron(curses.color_pair(_CP_NORMAL))
                self.stdscr.addstr(r, 0, _truncate(line, w - 1))
                self.stdscr.attroff(curses.color_pair(_CP_NORMAL))

            self._draw_footer(' Y Confirm & Run   N/Q Cancel   ↑↓ Scroll ')
            self.stdscr.refresh()

            key = self.stdscr.getch()
            if key in (ord('y'), ord('Y')):
                return True
            elif key in (ord('n'), ord('N'), ord('q'), ord('Q'), _ESC):
                return False
            elif key == curses.KEY_UP:
                scroll = max(0, scroll - 1)
            elif key == curses.KEY_DOWN:
                scroll = min(max(0, len(lines) - visible), scroll + 1)
