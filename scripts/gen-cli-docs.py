#!/usr/bin/env python

from click.core import Context, Group
from click.formatting import HelpFormatter

from watson import cli as watson_cli

# from watson import watson


class MarkdownFormatter(HelpFormatter):
    def write_heading(self, heading):
        """Writes a heading into the buffer."""
        self.write(f"### {heading}\n")

    def write_usage(self, prog, args="", prefix="Usage: "):
        """Writes a usage line into the buffer.
        :param prog: the program name.
        :param args: whitespace separated list of arguments.
        :param prefix: the prefix for the first line.
        """
        self.write(f"```bash\n{prefix} {prog} {args}\n```\n")

    def write_text(self, text):
        """Writes re-indented text into the buffer."""

        should_indent = False
        rows = []

        for row in text.split("\n"):
            if should_indent:
                row = f"    {row}"

            if "\b" in row:
                row = row.replace("\b", "", 1)
                should_indent = True
            elif not len(row.strip()):
                should_indent = False

            rows.append(row)

        self.write("{}\n".format("\n".join(rows)))

    def write_dl(self, rows, **kwargs):
        """Writes a definition list into the buffer.  This is how options
        and commands are usually formatted.
        :param rows: a list of two item tuples for the terms and values.
        """
        rows = list(rows)
        self.write("\n")

        self.write("Flag | Help\n")
        self.write("-----|-----\n")

        for row in rows:
            self.write("`{}` | {}\n".format(*row))
        self.write("\n")


class MkdocsContext(Context):
    def __init__(self, command, path=None, **kwargs):
        super().__init__(command, **kwargs)
        self._path = path or command.name

    @property
    def command_path(self):
        # Not so proud of it
        return f"watson {self._path}"

    def make_formatter(self):
        return MarkdownFormatter()


def main(rowsput):
    """Iterate over watson.cli commands,
    generate commands markdown documentation and
    write it to the rowsput file.
    """

    content = "\n".join(
        (
            "<!-- ",
            "    This document has been automatically generated.",
            "    It should NOT BE EDITED.",
            "    To update this part of the documentation,",
            "    please type the following from the repository root:",
            "    $ make docs-->",
            "",
            "# Commands",
            "",
        )
    )

    # Iterate over the registered commands (groups expand into their
    # subcommands) to build docs
    def walk(group, prefix=""):
        for name in sorted(group.commands):
            cmd = group.commands[name]
            if isinstance(cmd, Group):
                yield from walk(cmd, f"{prefix}{name} ")
            else:
                yield f"{prefix}{name}", cmd

    for cmd_name, cmd in walk(watson_cli.cli):
        ctx = MkdocsContext(cmd, path=cmd_name)
        formatter = MarkdownFormatter()
        cmd.format_help(ctx, formatter)

        # Each command is a section
        content += f"## `{cmd_name}`\n\n"
        content += "".join(formatter.buffer)

    # Write the commands documentation file
    with open(rowsput, "w") as f:
        f.write(content)


if __name__ == "__main__":
    commands_md = "docs/user-guide/commands.md"
    main(commands_md)
