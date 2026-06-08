"""`mad-skills` — install the bundled skills into Claude Code.

Copies the skill folders shipped inside this package into a Claude Code skills
directory (``~/.claude/skills`` by default, or ``.claude/skills`` with
``--project``). After installing, Claude Code picks the skills up on its next
launch.
"""

from __future__ import annotations

import argparse
import shutil
from importlib import resources
from pathlib import Path


def _skills_root():
    """Traversable pointing at the packaged ``skills/`` directory."""
    return resources.files("mad_skills") / "skills"


def list_skills() -> list[str]:
    root = _skills_root()
    names = []
    for entry in root.iterdir():
        if entry.is_dir() and (entry / "SKILL.md").is_file():
            names.append(entry.name)
    return sorted(names)


def _target_dir(args) -> Path:
    if args.dir:
        return Path(args.dir).expanduser()
    if args.project:
        return Path.cwd() / ".claude" / "skills"
    return Path.home() / ".claude" / "skills"


def cmd_list(args) -> int:
    skills = list_skills()
    if not skills:
        print("(no bundled skills found)")
        return 0
    print("Bundled skills:")
    for name in skills:
        print(f"  - {name}")
    return 0


def cmd_install(args) -> int:
    target = _target_dir(args)
    target.mkdir(parents=True, exist_ok=True)
    selected = args.skills or list_skills()
    available = set(list_skills())

    root = _skills_root()
    installed = []
    for name in selected:
        if name not in available:
            print(f"! unknown skill: {name} (have: {', '.join(sorted(available))})")
            return 1
        dest = target / name
        if dest.exists():
            if not args.force:
                print(f"  skip {name} (exists; use --force to overwrite)")
                continue
            shutil.rmtree(dest)
        # resources.as_file gives a real filesystem path even from a zip/wheel
        with resources.as_file(root / name) as src:
            shutil.copytree(src, dest)
        installed.append(name)
        print(f"  installed {name} -> {dest}")

    if installed:
        print(f"\nDone. Restart Claude Code to load: {', '.join(installed)}")
    else:
        print("\nNothing installed.")
    return 0


def cmd_uninstall(args) -> int:
    target = _target_dir(args)
    for name in args.skills:
        dest = target / name
        if dest.exists():
            shutil.rmtree(dest)
            print(f"  removed {dest}")
        else:
            print(f"  not installed: {name}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="mad-skills",
        description="Install the bundled Claude Code skills.",
    )
    sub = p.add_subparsers(dest="command", required=True)

    def add_target_flags(sp):
        sp.add_argument(
            "--project", action="store_true",
            help="install into ./.claude/skills instead of ~/.claude/skills",
        )
        sp.add_argument(
            "--dir", help="install into an explicit directory",
        )

    sp = sub.add_parser("list", help="list bundled skills")
    sp.set_defaults(func=cmd_list)

    sp = sub.add_parser("install", help="copy skills into a Claude skills dir")
    sp.add_argument("skills", nargs="*", help="skill names (default: all)")
    sp.add_argument(
        "--force", action="store_true", help="overwrite existing skills"
    )
    add_target_flags(sp)
    sp.set_defaults(func=cmd_install)

    sp = sub.add_parser("uninstall", help="remove installed skills")
    sp.add_argument("skills", nargs="+", help="skill names to remove")
    add_target_flags(sp)
    sp.set_defaults(func=cmd_uninstall)

    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
