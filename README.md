# mad-skills

My personal [Claude Code](https://claude.com/claude-code) skills, pip-installable.

## Install

```bash
uv tool install "git+https://github.com/universome/mad-skills.git"
mad-skills install          # copies skills into ~/.claude/skills
# or:
mad-skills install --link   # symlink instead, so `pip install -U` auto-updates them
```

Restart Claude Code afterwards (skills load at launch).

`--link` points `~/.claude/skills/<name>` at the installed package, so upgrading
the package updates the skills in place — no `mad-skills install` re-run (just
restart Claude Code). Use the default copy if your Python env may move or its
version may change (which would dangle the symlink).

## Skills

- **`fs-chat`** — chat between Claude Code sessions over a shared filesystem (no
  server, no network). Peers in the same **group** (a directory under
  `~/.mad-skills/fs-chat/`, default `all`) see each other. Same machine/cluster
  works out of the box (shared `$HOME`); across machines, register everyone with
  the same `--dir` on a shared/synced mount.

  ```bash
  # register ONCE (pick a group or an explicit shared dir); later commands need no flags
  fs-chat --group kube-chat register --name alice --summary "what I'm doing"
  fs-chat peers                 # find peer ids
  fs-chat send <peer_id> "hi"
  fs-chat inbox                 # read messages
  fs-chat watch                 # stream incoming messages live
  ```

  Override the bus path explicitly with `--dir PATH` or
  `MAD_SKILLS_FS_CHAT_DIR`; pick a group with `--group NAME` or
  `MAD_SKILLS_FS_CHAT_GROUP`.

MIT licensed.
