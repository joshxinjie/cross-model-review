"""Parse a unified diff into the lines GitHub accepts inline comments on."""

import re



def parse_unified_diff(text: str) -> dict[str, dict[str, set[int]]]:
    """Map each new-side path to {'added': lines added, 'commentable': every new-side line inside a hunk}.

    Hunk bodies are walked by their line counts, so content lines that look like headers ("+++ x", "--- x")
    are never mistaken for file headers.
    """
    files: dict[str, dict[str, set[int]]] = {}
    current = None
    new_line = 0
    remaining_new = remaining_old = 0
    lines = text.splitlines()
    i = 0
    while i < len(lines):
        raw = lines[i]
        i += 1
        if remaining_new > 0 or remaining_old > 0:        # inside a hunk body
            tag = raw[:1] or " "                            # an empty line is an empty context line
            if tag == "\\":                                 # "\ No newline at end of file"
                continue
            if tag in "+ " and current is not None:
                current["commentable"].add(new_line)
                if tag == "+":
                    current["added"].add(new_line)
            if tag in "+ ":
                new_line += 1
                remaining_new -= 1
            if tag in "- ":
                remaining_old -= 1
            continue
        if raw.startswith("+++ "):
            path = raw[4:].strip().split("\t")[0]
            if path == "/dev/null":
                current = None
            else:
                path = path[2:] if path.startswith("b/") else path
                current = files.setdefault(path, {"added": set(), "commentable": set()})
            continue
        m = re.match(r"^@@ -\d+(?:,(\d+))? \+(\d+)(?:,(\d+))? @@", raw)
        if m:
            remaining_old = int(m.group(1)) if m.group(1) is not None else 1
            new_line = int(m.group(2))
            remaining_new = int(m.group(3)) if m.group(3) is not None else 1
    return files
