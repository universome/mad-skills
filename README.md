# mad-skills

My personal [Claude Code](https://claude.com/claude-code) skills, pip-installable.

## Install

```bash
uv tool install "git+https://github.com/universome/mad-skills.git"
mad-skills install   # copies skills into ~/.claude/skills
```

Restart Claude Code afterwards.

## Skills

- **`fs-chat`** — chat between Claude Code sessions over a shared filesystem (no
  server, no network). Same machine by default; set `MAD_SKILLS_PEER_DIR` to a
  synced/mounted folder to chat across machines.

  ```bash
  fs-chat register --name backend --summary "what I'm doing"
  fs-chat peers                 # find peer ids
  fs-chat send <peer_id> "hi"
  fs-chat inbox                 # read messages
  ```

MIT licensed.
