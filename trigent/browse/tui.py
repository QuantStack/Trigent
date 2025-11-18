#!/usr/bin/env python3
"""Terminal User Interface for browsing Rich Issue database."""

import curses
import textwrap
from typing import Any

from trigent.database import load_issues


class IssueTUI:
    def __init__(self, repo: str = "jupyterlab/jupyterlab"):
        self.repo = repo
        self.issues: list[dict[str, Any]] = []
        self.filtered_issues: list[dict[str, Any]] = []  # Issues after filtering
        self.current_index = 0
        self.view_mode = "list"  # "list", "detail", or "links"
        self.detail_scroll = 0
        self.detail_lines: list[tuple] = []
        self.status_message = ""
        # Filters
        self.status_filter = "all"  # "all", "open", "closed", "merged"
        self.type_filter = "all"  # "all", "issues", "prs"
        # For linked issues selection
        self.links_mode = "similar"  # "similar" or "linked"
        self.links_index = 0
        self.links_scroll = 0
        self.similar_issues: list[dict[str, Any]] = []
        self.linked_issues: list[dict[str, Any]] = []

    def load_data(self):
        """Load issues from database."""
        try:
            self.issues = load_issues(self.repo)
            if not self.issues:
                self.status_message = f"No issues found for {self.repo}"
            else:
                self.apply_filters()
        except Exception as e:
            self.status_message = f"Error loading issues: {e}"

    def get_issue_type(self, issue: dict[str, Any]) -> str:
        """Determine if issue is a PR or regular issue."""
        # Check if it has pull_request field (GitHub API includes this)
        if issue.get("pull_request"):
            return "pr"
        # Fallback: check URL pattern
        url = issue.get("url", "")
        if "/pull/" in url:
            return "pr"
        return "issue"

    def cycle_status_filter(self):
        """Cycle through status filters: all -> open -> closed -> merged -> all"""
        status_order = ["all", "open", "closed", "merged"]
        current_index = status_order.index(self.status_filter)
        self.status_filter = status_order[(current_index + 1) % len(status_order)]
        self.apply_filters()

    def cycle_type_filter(self):
        """Cycle through type filters: all -> issues -> prs -> all"""
        type_order = ["all", "issues", "prs"]
        current_index = type_order.index(self.type_filter)
        self.type_filter = type_order[(current_index + 1) % len(type_order)]
        self.apply_filters()

    def apply_filters(self):
        """Apply current filters to issues list."""
        self.filtered_issues = []

        for issue in self.issues:
            # Apply status filter
            status = issue.get("state", "").lower()
            if self.status_filter != "all":
                if self.status_filter == "merged":
                    # For merged, check if it's a closed PR
                    if status != "closed" or self.get_issue_type(issue) != "pr":
                        continue
                    # Additional check for merged state if available
                    if issue.get("merged", False) is False:
                        continue
                elif status != self.status_filter:
                    continue

            # Apply type filter
            issue_type = self.get_issue_type(issue)
            if self.type_filter != "all":
                if self.type_filter == "issues" and issue_type != "issue":
                    continue
                elif self.type_filter == "prs" and issue_type != "pr":
                    continue

            self.filtered_issues.append(issue)

        # Reset current index if it's out of bounds
        if self.current_index >= len(self.filtered_issues):
            self.current_index = max(0, len(self.filtered_issues) - 1)

    def format_issue_summary(self, issue: dict[str, Any]) -> str:
        """Format issue for list view."""
        number = issue.get("number", "?")
        title = issue.get("title", "No title")
        state = issue.get("state", "?")
        issue_type = self.get_issue_type(issue)

        # Truncate title if too long
        if len(title) > 50:
            title = title[:47] + "..."

        # Get recommendation status with action info
        recommendations = issue.get("recommendations", [])
        if recommendations:
            # Show latest recommendation action if using new schema
            latest_rec = recommendations[-1]
            if "action" in latest_rec:
                action = latest_rec["action"]
                confidence = latest_rec.get("confidence", "?")
                rec_status = f"({len(recommendations)} recs: {action}/{confidence})"
            else:
                # Legacy format
                old_action = latest_rec.get("recommendation", "?")
                rec_status = f"({len(recommendations)} recs: {old_action})"
        else:
            rec_status = "(no recs)"

        return f"#{number:>5} {state:>6} {issue_type:>5} | {title:<50} {rec_status}"

    def format_markdown_simple(self, text: str, width: int) -> list[tuple]:
        """Simple markdown formatting for terminal with improved wrapping.
        Returns list of (text, attribute) tuples for proper terminal formatting."""
        if not text:
            return [("", 0)]

        lines = []
        for line in text.split("\n"):
            line = line.strip()
            if not line:
                lines.append(("", 0))
                continue

            # Handle headers
            if line.startswith("# "):
                header_text = line[2:]
                wrapped_header = textwrap.fill(header_text, width=width - 8)
                for h_line in wrapped_header.split("\n"):
                    lines.append((f"=== {h_line} ===", curses.A_BOLD))
            elif line.startswith("## "):
                header_text = line[3:]
                wrapped_header = textwrap.fill(header_text, width=width - 8)
                for h_line in wrapped_header.split("\n"):
                    lines.append((f"--- {h_line} ---", curses.A_BOLD))
            elif line.startswith("### "):
                header_text = line[4:]
                wrapped_header = textwrap.fill(header_text, width=width - 6)
                for h_line in wrapped_header.split("\n"):
                    lines.append((f"* {h_line} *", curses.A_BOLD))
            # Handle bold
            elif "**" in line:
                # Process bold text inline
                parts = line.split("**")
                processed_line = ""
                for i, part in enumerate(parts):
                    if i % 2 == 1:  # This is bold text
                        processed_line += part
                    else:
                        processed_line += part

                wrapped = textwrap.fill(processed_line, width=width - 2)
                for w_line in wrapped.split("\n"):
                    lines.append((w_line, curses.A_BOLD))
            # Handle italic
            elif "*" in line and "**" not in line:
                # Process italic text inline
                parts = line.split("*")
                processed_line = ""
                for _i, part in enumerate(parts):
                    processed_line += part

                wrapped = textwrap.fill(processed_line, width=width - 2)
                for w_line in wrapped.split("\n"):
                    lines.append((w_line, curses.A_DIM))  # Use dim for italic
            # Handle lists
            elif line.startswith("- "):
                list_text = line[2:]
                wrapped = textwrap.fill(
                    list_text, width=width - 5, subsequent_indent="    "
                )
                for w_line in wrapped.split("\n"):
                    if w_line.startswith("    "):
                        lines.append((f"  {w_line}", 0))
                    else:
                        lines.append((f"  • {w_line}", 0))
            elif line.startswith("* "):
                list_text = line[2:]
                wrapped = textwrap.fill(
                    list_text, width=width - 5, subsequent_indent="    "
                )
                for w_line in wrapped.split("\n"):
                    if w_line.startswith("    "):
                        lines.append((f"  {w_line}", 0))
                    else:
                        lines.append((f"  • {w_line}", 0))
            else:
                # Wrap long lines with better word breaking
                wrapped = textwrap.fill(
                    line, width=width - 2, break_long_words=False, break_on_hyphens=True
                )
                for w_line in wrapped.split("\n"):
                    lines.append((w_line, 0))

        return lines

    def format_issue_detail(self, issue: dict[str, Any], width: int) -> list[tuple]:
        """Format issue for detail view. Returns list of (text, attribute) tuples."""
        lines = []

        # Header
        number = issue.get("number", "?")
        title = issue.get("title", "No title")
        state = issue.get("state", "?")
        url = issue.get("url", "")

        lines.append((f"{'=' * width}", curses.A_BOLD))
        lines.append((f"Issue #{number} - {state}", curses.A_BOLD))
        lines.append((f"{'=' * width}", curses.A_BOLD))
        # Better title wrapping
        wrapped_title = textwrap.fill(
            title, width=width - 2, break_long_words=False, break_on_hyphens=True
        )
        for title_line in wrapped_title.split("\n"):
            lines.append((title_line, curses.A_BOLD))
        lines.append(("", 0))
        if url:
            # Handle long URLs by wrapping them
            if len(url) > width - 6:
                lines.append(("URL:", 0))
                wrapped_url = textwrap.fill(url, width=width - 2, break_long_words=True)
                for url_line in wrapped_url.split("\n"):
                    lines.append((url_line, 0))
            else:
                lines.append((f"URL: {url}", 0))
            lines.append(("", 0))

        # Summary
        summary = issue.get("summary", "")
        if summary:
            lines.append(("SUMMARY:", curses.A_BOLD))
            lines.append(("-" * 20, 0))
            lines.extend(self.format_markdown_simple(summary, width))
            lines.append(("", 0))

        # Metrics (moved up before recommendations for better visibility)
        lines.append(("METRICS:", curses.A_BOLD))
        lines.append(("-" * 20, 0))
        lines.append((f"Comments: {issue.get('comment_count', 0)}", 0))
        lines.append((f"Reactions: {issue.get('total_reactions', 0)}", 0))
        lines.append((f"Age (days): {issue.get('age_days', 0)}", 0))
        lines.append((f"Priority Score: {issue.get('priority_score', 0)}", 0))

        # Add engagement metrics
        participants = issue.get("participants", [])
        if participants:
            lines.append((f"Participants: {len(participants)}", 0))

        labels = issue.get("labels", [])
        if labels:
            label_names = [
                label.get("name", "") for label in labels if label.get("name")
            ]
            if label_names:
                lines.append(
                    (f"Labels: {', '.join(label_names[:5])}", 0)
                )  # Show first 5 labels
                if len(label_names) > 5:
                    lines.append((f"  ... and {len(label_names) - 5} more", 0))

        assignees = issue.get("assignees", [])
        if assignees:
            assignee_names = [
                assignee.get("login", "")
                for assignee in assignees
                if assignee.get("login")
            ]
            if assignee_names:
                lines.append((f"Assignees: {', '.join(assignee_names)}", 0))

        lines.append(("", 0))

        # Recommendations
        recommendations = issue.get("recommendations", [])
        if recommendations:
            lines.append(("RECOMMENDATIONS:", curses.A_BOLD))
            lines.append(("-" * 20, 0))
            for i, rec in enumerate(recommendations, 1):
                lines.append((f"Recommendation {i}:", curses.A_BOLD))

                # Check for new schema format vs old format
                if "action" in rec:
                    # New schema format
                    lines.append((f"  Action: {rec.get('action', '?')}", curses.A_BOLD))
                    lines.append((f"  Confidence: {rec.get('confidence', '?')}", 0))

                    # Summary and rationale
                    summary = rec.get("summary", "")
                    if summary:
                        lines.append((f"  Summary: {summary}", 0))

                    rationale = rec.get("rationale", "")
                    if rationale:
                        lines.append((f"  Rationale: {rationale}", 0))

                    # Analysis section
                    analysis = rec.get("analysis", {})
                    if analysis:
                        lines.append(("  Analysis:", curses.A_BOLD))
                        lines.append(
                            (f"    Severity: {analysis.get('severity', '?')}", 0)
                        )
                        lines.append(
                            (f"    Frequency: {analysis.get('frequency', '?')}", 0)
                        )
                        lines.append(
                            (f"    Prevalence: {analysis.get('prevalence', '?')}", 0)
                        )
                        lines.append(
                            (f"    Effort: {analysis.get('effort_estimate', '?')}", 0)
                        )
                        lines.append(
                            (f"    Risk: {analysis.get('solution_risk', '?')}", 0)
                        )

                    # Context section
                    context = rec.get("context", {})
                    if context:
                        if context.get("affected_packages"):
                            lines.append(
                                (
                                    f"  Packages: {', '.join(context['affected_packages'])}",
                                    0,
                                )
                            )
                        if context.get("affected_paths"):
                            lines.append(
                                (f"  Paths: {', '.join(context['affected_paths'])}", 0)
                            )
                        if context.get("affected_components"):
                            lines.append(
                                (
                                    f"  Components: {', '.join(context['affected_components'])}",
                                    0,
                                )
                            )
                        if context.get("related_issues"):
                            related_str = ", ".join(
                                f"#{num}" for num in context["related_issues"]
                            )
                            lines.append((f"  Related: {related_str}", 0))
                        if context.get("merge_with"):
                            merge_str = ", ".join(
                                f"#{num}" for num in context["merge_with"]
                            )
                            lines.append((f"  Merge with: {merge_str}", 0))

                    # Meta section
                    meta = rec.get("meta", {})
                    if meta:
                        reviewer = meta.get("reviewer", "?")
                        timestamp = meta.get("timestamp", "?")
                        lines.append((f"  By: {reviewer} at {timestamp}", 0))
                        if meta.get("model_version"):
                            lines.append((f"  Model: {meta['model_version']}", 0))

                else:
                    # Legacy schema format (backward compatibility)
                    lines.append((f"  Severity: {rec.get('severity', '?')}", 0))
                    lines.append((f"  Frequency: {rec.get('frequency', '?')}", 0))
                    lines.append((f"  Prevalence: {rec.get('prevalence', '?')}", 0))
                    lines.append(
                        (f"  Recommendation: {rec.get('recommendation', '?')}", 0)
                    )
                    lines.append(
                        (f"  Complexity: {rec.get('solution_complexity', '?')}", 0)
                    )
                    lines.append((f"  Risk: {rec.get('solution_risk', '?')}", 0))

                    # Legacy affected components
                    if rec.get("affected_packages"):
                        lines.append(
                            (f"  Packages: {', '.join(rec['affected_packages'])}", 0)
                        )
                    if rec.get("affected_paths"):
                        lines.append(
                            (f"  Paths: {', '.join(rec['affected_paths'])}", 0)
                        )
                    if rec.get("affected_objects"):
                        lines.append(
                            (f"  Objects: {', '.join(rec['affected_objects'])}", 0)
                        )

                    lines.append((f"  Timestamp: {rec.get('timestamp', '?')}", 0))

                # Report (common to both formats)
                report = rec.get("report", "")
                if report:
                    lines.append(("  Report:", curses.A_BOLD))
                    report_lines = self.format_markdown_simple(report, width - 4)
                    for rline_text, rline_attr in report_lines:
                        lines.append((f"    {rline_text}", rline_attr))

                lines.append(("", 0))

        # Cross references
        cross_refs = issue.get("cross_references", [])
        if cross_refs:
            lines.append(("LINKED ISSUES:", curses.A_BOLD))
            lines.append(("-" * 20, 0))
            for ref in cross_refs[:10]:  # Limit to first 10
                ref_num = ref.get("number", "?")
                ref_title = ref.get("title", "No title")
                if len(ref_title) > 50:
                    ref_title = ref_title[:47] + "..."
                lines.append((f"  #{ref_num} - {ref_title}", 0))
            if len(cross_refs) > 10:
                lines.append((f"  ... and {len(cross_refs) - 10} more", 0))
            lines.append(("", 0))

        return lines

    def find_issue_by_number(self, issue_number: int) -> int | None:
        """Find issue index by number."""
        for i, issue in enumerate(self.issues):
            if issue.get("number") == issue_number:
                return i
        return None

    def get_linked_issues(self, issue: dict[str, Any]) -> list[int]:
        """Get list of linked issue numbers."""
        cross_refs = issue.get("cross_references", [])
        return [ref.get("number") for ref in cross_refs if ref.get("number")]

    def load_similar_and_linked_issues(self, issue: dict[str, Any]):
        """Load similar and linked issues for the current issue."""
        # Get similar issues (placeholder - would need actual similarity data)
        self.similar_issues = []

        # Get linked issues from cross references
        cross_refs = issue.get("cross_references", [])
        self.linked_issues = []
        for ref in cross_refs:
            ref_number = ref.get("number")
            if ref_number:
                # Find the full issue data
                for full_issue in self.issues:
                    if full_issue.get("number") == ref_number:
                        self.linked_issues.append(full_issue)
                        break

    def draw_list_view(self, stdscr):
        """Draw the list view."""
        height, width = stdscr.getmaxyx()
        stdscr.clear()

        # Title with filter info
        filter_info = (
            f"Status: {self.status_filter.title()} | Type: {self.type_filter.title()}"
        )
        title = f"Rich Issue Browser - {self.repo} ({len(self.filtered_issues)}/{len(self.issues)}) - {filter_info}"
        stdscr.addstr(0, 0, title[: width - 1], curses.A_BOLD)

        # Headers
        header = f"{'Number':>6} {'State':>6} {'Type':>5} | {'Title':<50} {'Recs'}"
        stdscr.addstr(1, 0, header[: width - 1], curses.A_UNDERLINE)

        # Issue list
        start_line = 2
        visible_lines = height - 4  # Leave space for status

        # Calculate scroll window
        if self.current_index >= visible_lines:
            start_index = self.current_index - visible_lines + 1
        else:
            start_index = 0

        for i in range(visible_lines):
            line_num = start_line + i
            issue_index = start_index + i

            if issue_index >= len(self.filtered_issues):
                break

            issue = self.filtered_issues[issue_index]
            line_text = self.format_issue_summary(issue)

            # Highlight current selection
            if issue_index == self.current_index:
                stdscr.addstr(line_num, 0, line_text[: width - 1], curses.A_REVERSE)
            else:
                stdscr.addstr(line_num, 0, line_text[: width - 1])

        # Status line
        status_line = height - 1
        help_text = "↑↓: Navigate | Enter: Details | s: Status | t: Type | q: Quit"
        if self.status_message:
            status = f"{self.status_message} | {help_text}"
        else:
            status = help_text
        stdscr.addstr(status_line, 0, status[: width - 1], curses.A_BOLD)

    def draw_detail_view(self, stdscr):
        """Draw the detail view."""
        height, width = stdscr.getmaxyx()
        stdscr.clear()

        if not self.filtered_issues or self.current_index >= len(self.filtered_issues):
            stdscr.addstr(0, 0, "No issue selected", curses.A_BOLD)
            return

        issue = self.filtered_issues[self.current_index]

        # Get formatted detail lines
        if not self.detail_lines:
            self.detail_lines = self.format_issue_detail(issue, width - 2)

        # Display lines with scrolling
        visible_lines = height - 2  # Leave space for status

        for i in range(visible_lines):
            line_index = self.detail_scroll + i
            if line_index >= len(self.detail_lines):
                break

            line_data = self.detail_lines[line_index]
            if isinstance(line_data, tuple):
                line_text, line_attr = line_data
            else:
                # Fallback for backward compatibility
                line_text, line_attr = str(line_data), 0

            stdscr.addstr(i, 0, line_text[: width - 1], line_attr)

        # Status line
        status_line = height - 1
        total_lines = len(self.detail_lines)
        scroll_info = f"Line {self.detail_scroll + 1}-{min(self.detail_scroll + visible_lines, total_lines)}/{total_lines}"

        help_text = f"↑↓: Scroll | Enter: View similar/linked | Esc: Back to list | q: Quit | {scroll_info}"
        stdscr.addstr(status_line, 0, help_text[: width - 1], curses.A_BOLD)

    def draw_links_view(self, stdscr):
        """Draw the similar/linked issues view."""
        height, width = stdscr.getmaxyx()
        stdscr.clear()

        # Title
        current_issue = (
            self.filtered_issues[self.current_index]
            if self.current_index < len(self.filtered_issues)
            else None
        )
        if current_issue:
            issue_title = current_issue.get("title", "No title")
            if len(issue_title) > 50:
                issue_title = issue_title[:47] + "..."
            title = f"Issue #{current_issue.get('number', '?')}: {issue_title}"
        else:
            title = "Links View"
        stdscr.addstr(0, 0, title[: width - 1], curses.A_BOLD)

        # Tab indicator
        tab_line = 1
        similar_tab = f"[Similar ({len(self.similar_issues)})]"
        linked_tab = f"[Linked ({len(self.linked_issues)})]"

        if self.links_mode == "similar":
            stdscr.addstr(tab_line, 0, similar_tab, curses.A_REVERSE)
            stdscr.addstr(tab_line, len(similar_tab) + 2, linked_tab)
        else:
            stdscr.addstr(tab_line, 0, similar_tab)
            stdscr.addstr(tab_line, len(similar_tab) + 2, linked_tab, curses.A_REVERSE)

        # Headers
        header_line = 2
        header = f"{'Number':>6} {'State':>6} | {'Title':<50} {'Comments':>8} {'Reactions':>9}"
        stdscr.addstr(header_line, 0, header[: width - 1], curses.A_UNDERLINE)

        # Issue list
        start_line = 3
        visible_lines = height - 5  # Leave space for status

        # Get current issue list
        current_issues = (
            self.similar_issues if self.links_mode == "similar" else self.linked_issues
        )

        if not current_issues:
            no_items_msg = f"No {self.links_mode} issues found"
            stdscr.addstr(start_line, 0, no_items_msg)
        else:
            # Calculate scroll window
            if self.links_index >= visible_lines:
                start_index = self.links_index - visible_lines + 1
            else:
                start_index = 0

            for i in range(visible_lines):
                line_num = start_line + i
                issue_index = start_index + i

                if issue_index >= len(current_issues):
                    break

                issue = current_issues[issue_index]
                number = issue.get("number", "?")
                title = issue.get("title", "No title")
                state = issue.get("state", "?")
                comments = issue.get("comment_count", 0)
                reactions = issue.get("total_reactions", 0)

                # Truncate title if too long
                if len(title) > 50:
                    title = title[:47] + "..."

                line_text = f"#{number:>5} {state:>6} | {title:<50} {comments:>8} {reactions:>9}"

                # Highlight current selection
                if issue_index == self.links_index:
                    stdscr.addstr(line_num, 0, line_text[: width - 1], curses.A_REVERSE)
                else:
                    stdscr.addstr(line_num, 0, line_text[: width - 1])

        # Status line
        status_line = height - 1
        help_text = "↑↓: Navigate | Enter: View issue | L: Toggle tabs | Esc: Back to detail | q: Quit"
        if self.status_message:
            status = f"{self.status_message} | {help_text}"
        else:
            status = help_text
        stdscr.addstr(status_line, 0, status[: width - 1], curses.A_BOLD)

    def handle_detail_navigation(self, issue: dict[str, Any]) -> int | None:
        """Handle navigation to linked issues. Returns new issue index or None."""
        linked_issues = self.get_linked_issues(issue)

        if not linked_issues:
            self.status_message = "No linked issues found"
            return None

        # For simplicity, navigate to the first linked issue
        # In a more sophisticated UI, you could show a selection menu
        target_number = linked_issues[0]
        target_index = self.find_issue_by_number(target_number)

        if target_index is not None:
            self.status_message = f"Navigated to linked issue #{target_number}"
            return target_index
        else:
            self.status_message = f"Linked issue #{target_number} not found in database"
            return None

    def run(self, stdscr):
        """Main TUI loop."""
        # Setup curses
        curses.curs_set(0)  # Hide cursor
        stdscr.nodelay(True)  # Non-blocking input
        stdscr.timeout(100)  # 100ms timeout

        # Load data
        self.load_data()

        if not self.issues:
            stdscr.addstr(0, 0, "No issues found. Press any key to exit.")
            stdscr.getch()
            return

        while True:
            try:
                if self.view_mode == "list":
                    self.draw_list_view(stdscr)
                elif self.view_mode == "detail":
                    self.draw_detail_view(stdscr)
                elif self.view_mode == "links":
                    self.draw_links_view(stdscr)

                stdscr.refresh()

                # Handle input
                key = stdscr.getch()

                if key == ord("q"):
                    break
                elif key == curses.KEY_UP:
                    if self.view_mode == "list":
                        self.current_index = max(0, self.current_index - 1)
                        self.status_message = ""
                    elif self.view_mode == "detail":
                        self.detail_scroll = max(0, self.detail_scroll - 1)
                    elif self.view_mode == "links":
                        self.links_index = max(0, self.links_index - 1)
                elif key == curses.KEY_DOWN:
                    if self.view_mode == "list":
                        self.current_index = min(
                            len(self.filtered_issues) - 1, self.current_index + 1
                        )
                        self.status_message = ""
                    elif self.view_mode == "detail":
                        max_scroll = max(
                            0, len(self.detail_lines) - (stdscr.getmaxyx()[0] - 2)
                        )
                        self.detail_scroll = min(max_scroll, self.detail_scroll + 1)
                    elif self.view_mode == "links":
                        max_links = (
                            len(self.similar_issues)
                            if self.links_mode == "similar"
                            else len(self.linked_issues)
                        )
                        self.links_index = min(max_links - 1, self.links_index + 1)
                elif key == ord("\n") or key == curses.KEY_ENTER or key == 10:
                    if self.view_mode == "list":
                        # Switch to detail view
                        self.view_mode = "detail"
                        self.detail_scroll = 0
                        self.detail_lines = []  # Reset detail lines
                        self.status_message = ""
                    elif self.view_mode == "detail":
                        # Switch to links view
                        if self.current_index < len(self.filtered_issues):
                            current_issue = self.filtered_issues[self.current_index]
                            self.load_similar_and_linked_issues(current_issue)
                            if self.similar_issues or self.linked_issues:
                                self.view_mode = "links"
                                self.links_index = 0
                                self.links_scroll = 0
                                self.links_mode = (
                                    "linked" if self.linked_issues else "similar"
                                )
                            else:
                                self.status_message = (
                                    "No similar or linked issues found"
                                )
                    elif self.view_mode == "links":
                        # Navigate to selected issue
                        selected_issue = None
                        if self.links_mode == "similar" and self.links_index < len(
                            self.similar_issues
                        ):
                            selected_issue = self.similar_issues[self.links_index]
                        elif self.links_mode == "linked" and self.links_index < len(
                            self.linked_issues
                        ):
                            selected_issue = self.linked_issues[self.links_index]

                        if selected_issue:
                            # Find the issue in the main list
                            selected_number = selected_issue.get("number")
                            new_index = self.find_issue_by_number(selected_number)
                            if new_index is not None:
                                self.current_index = new_index
                                self.view_mode = "detail"
                                self.detail_scroll = 0
                                self.detail_lines = []
                                self.status_message = (
                                    f"Navigated to issue #{selected_number}"
                                )
                            else:
                                self.status_message = (
                                    f"Issue #{selected_number} not found"
                                )
                elif key == ord("s"):
                    # Cycle status filter (all/open/closed/merged)
                    if self.view_mode == "list":
                        self.cycle_status_filter()
                        self.status_message = f"Status filter: {self.status_filter}"
                elif key == ord("t"):
                    # Cycle type filter (all/issues/prs)
                    if self.view_mode == "list":
                        self.cycle_type_filter()
                        self.status_message = f"Type filter: {self.type_filter}"
                elif key == ord("l"):
                    # Toggle between similar and linked issues in links view
                    if self.view_mode == "links":
                        if self.links_mode == "similar" and self.linked_issues:
                            self.links_mode = "linked"
                            self.links_index = 0
                            self.links_scroll = 0
                        elif self.links_mode == "linked" and self.similar_issues:
                            self.links_mode = "similar"
                            self.links_index = 0
                            self.links_scroll = 0
                elif key == 27:  # Escape key
                    if self.view_mode == "detail":
                        self.view_mode = "list"
                        self.detail_lines = []
                        self.status_message = ""
                    elif self.view_mode == "links":
                        self.view_mode = "detail"
                elif key == curses.KEY_HOME:
                    if self.view_mode == "list":
                        self.current_index = 0
                    elif self.view_mode == "detail":
                        self.detail_scroll = 0
                    elif self.view_mode == "links":
                        self.links_index = 0
                        self.links_scroll = 0
                elif key == curses.KEY_END:
                    if self.view_mode == "list":
                        self.current_index = len(self.filtered_issues) - 1
                    elif self.view_mode == "detail":
                        max_scroll = max(
                            0, len(self.detail_lines) - (stdscr.getmaxyx()[0] - 2)
                        )
                        self.detail_scroll = max_scroll
                    elif self.view_mode == "links":
                        max_links = (
                            len(self.similar_issues)
                            if self.links_mode == "similar"
                            else len(self.linked_issues)
                        )
                        self.links_index = max(0, max_links - 1)
                        self.links_scroll = max(0, max_links - 1)

            except KeyboardInterrupt:
                break
            except Exception as e:
                # Simple error handling - show error and continue
                self.status_message = f"Error: {e}"


def run_tui(repo: str = "jupyterlab/jupyterlab"):
    """Run the TUI application."""
    tui = IssueTUI(repo)
    curses.wrapper(tui.run)


def main(repo: str, config: dict):
    """Main entry point for TUI with config support."""
    # TODO: Update IssueTUI to use config for database access
    run_tui(repo)


if __name__ == "__main__":
    import sys

    repo = sys.argv[1] if len(sys.argv) > 1 else "jupyterlab/jupyterlab"
    run_tui(repo)
