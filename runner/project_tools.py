import posixpath
import shlex

def tool(name, description, properties, required):
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {
                "type": "object",
                "properties": properties,
                "required": required,
            },
        },
    }

PROJECT_TOOLS = [
    tool(
        "list_files",
        "List up to 120 source file paths under a project directory. "
        "Excludes target, .git, and node_modules. Use subdirectories for narrower listings.",
        {"path": {"type": "string", "description": "Project-relative directory; default is ."}},
        [],
    ),
    tool(
        "read_file",
        "Read a numbered section of a project text file, at most 120 lines. "
        "Request subsequent sections to read longer files.",
        {
            "path": {"type": "string"},
            "start_line": {"type": "integer", "minimum": 1},
            "end_line": {"type": "integer", "minimum": 1},
        },
        ["path"],
    ),
]

def project_path(value):
    if not isinstance(value, str) or "\0" in value:
        raise ValueError("Path must be a valid string.")
    path = posixpath.normpath(posixpath.join("/project", value))
    if path != "/project" and not path.startswith("/project/"):
        raise ValueError("Path must remain inside /project.")
    return shlex.quote(path)

def build_command(name, arguments):
    if not isinstance(arguments, dict):
        raise ValueError("Arguments must be an object.")
    if name == "run_command":
        command = arguments.get("command")
        if not isinstance(command, str) or not command.strip():
            raise ValueError("A nonempty command is required.")
        return command
    if name == "list_files":
        path = project_path(arguments.get("path", "."))
        return (
            f"find {path} -type d "
            r"\( -name target -o -name .git -o -name node_modules \) "
            r"-prune -o -type f -print | sort | sed -n '1,120p'"
        )
    if name == "read_file":
        path = project_path(arguments["path"])
        start = arguments.get("start_line", 1)
        end = arguments.get("end_line", start + 119)
        if type(start) is not int or type(end) is not int:
            raise ValueError("Line numbers must be integers.")
        if start < 1 or end < start or end - start >= 120:
            raise ValueError("Request between 1 and 120 lines, starting at line 1 or later.")
        return f"nl -ba -- {path} | sed -n '{start},{end}p'"
    raise ValueError("Unknown tool.")
