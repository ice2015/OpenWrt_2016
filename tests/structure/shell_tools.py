"""Find the external tools a POSIX shell script invokes.

Only invocations that carry an option flag are reported: a tool such as
``stat -c %u`` or ``od -An -N 16`` cannot be mistaken for prose or for a
shell variable. That is exactly the shape of the calls that broke on the
device, where a script used a utility the image does not ship.
"""

import re

# A tool name that is followed by an option flag, at a position where a
# command may start: the start of a line, after a separator, or inside a
# command substitution.
INVOCATION = re.compile(
    r"(?:^|[;&|(]\s*|\$\(\s*|\bthen\s+|\bdo\s+|\belse\s+|\b!\s+)"
    r"([a-z][a-z0-9_.-]{1,24})\s+-[A-Za-z]"
)

# The same shape, but for a tool used without any option.
BARE_INVOCATION = re.compile(
    r"(?:^|[;&|(]\s*|\$\(\s*|\bthen\s+|\bdo\s+|\belse\s+)"
    r"([a-z][a-z0-9_.-]{1,24})(?:\s|$)"
)

SHELL_KEYWORDS = {
    "if", "then", "elif", "else", "fi", "for", "while", "until", "do", "done",
    "case", "esac", "in", "select", "function", "time", "!", "{", "}", "(",
    ")", "return", "break", "continue", "exit", "local", "export", "readonly",
    "declare", "typeset", "shift", "trap", "eval", "exec", "source", ".",
    "true", "false", "esac", "esac)", "fi", "done", "in", "esac",
}

BUILTIN_NAMES = {
    "printf", "read", "set", "unset", "test", "wait", "command", "echo",
    "cd", "pwd", "umask", "alias", "type", "ulimit", "hash", "jobs", "kill",
    "[", "]]", "[[", "((", "let",
}


def strip_comments(text):
    """Drop trailing comments. A '#' only starts one at a word boundary."""
    out = []
    for line in text.splitlines(True):
        cut = len(line)
        for index, char in enumerate(line):
            if char == "#" and (index == 0 or line[index - 1] in " \t;|&()"):
                cut = index
                break
        out.append(line[:cut])
    return "".join(out)


def blank_literals(text):
    """Blank single-quoted regions. Double quotes keep $(...) substitutions,
    which the shell still executes inside them."""
    out = []
    index = 0
    length = len(text)
    while index < length:
        char = text[index]
        if char == "\\":
            out.append(" ")
            index += 2
            continue
        if char == "'":
            end = text.find("'", index + 1)
            if end == -1:
                out.append(char)
                index += 1
                continue
            out.append("  ")
            index = end + 1
            continue
        if char == '"':
            end = index + 1
            while end < length:
                if text[end] == "\\":
                    end += 2
                    continue
                if text[end] == '"':
                    break
                end += 1
            if end >= length:
                out.append(char)
                index += 1
                continue
            body = text[index + 1:end]
            # Keep only command substitutions; the rest is data.
            kept = []
            cursor = 0
            while cursor < len(body):
                if body.startswith("$(", cursor):
                    depth = 1
                    start = cursor
                    cursor += 2
                    while cursor < len(body) and depth:
                        if body.startswith("$(", cursor):
                            depth += 1
                            cursor += 2
                            continue
                        if body[cursor] == ")":
                            depth -= 1
                            if not depth:
                                break
                        cursor += 1
                    kept.append(body[start:cursor + 1])
                    cursor += 1
                else:
                    cursor += 1
            out.append(" " + " ".join(kept) + " ")
            index = end + 1
            continue
        out.append(char)
        index += 1
    return "".join(out)


def invocations(source):
    """Return the set of tools the script calls with an option flag."""
    code = blank_literals(strip_comments(source))
    found = set()
    for name in INVOCATION.findall(code):
        if name in SHELL_KEYWORDS or name in BUILTIN_NAMES:
            continue
        found.add(name)
    return found
