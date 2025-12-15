from pathlib import Path


def generate_tree(
    directory,
    prefix="",
    output_file=None,
    ignore_dirs={".git", "__pycache__", ".idea", "venv", "node_modules", ".venv"},
):
    contents = list(Path(directory).iterdir())
    contents = [c for c in contents if c.name not in ignore_dirs]
    contents = sorted(contents, key=lambda x: (x.is_file(), x.name))

    for i, path in enumerate(contents):
        is_last = i == len(contents) - 1
        current = "└── " if is_last else "├── "
        print(f"{prefix}{current}{path.name}", file=output_file)

        if path.is_dir():
            extension = "    " if is_last else "│   "
            generate_tree(path, prefix + extension, output_file, ignore_dirs)


# Run it
project_dir = Path("src/arche_api/")
with open("project_structure2.txt", "w", encoding="utf-8") as f:
    print(project_dir.name, file=f)
    generate_tree(project_dir, output_file=f)

print("Project structure exported to project_structure2.txt")
