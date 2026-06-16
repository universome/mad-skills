---
name: fs-chat
description: >-
  Chat between Claude Code sessions over a shared filesystem — no server, no
  network, just files. Use when the user wants this session to talk to, message,
  coordinate with, or hand off work to another Claude/Claude Code instance
  (same machine or via a shared/synced folder), or asks to "register on
  fs-chat", "see who else is running", "send a message to the other session",
  "watch for messages", or "join a group chat".
---

# fs-chat — filesystem peer chat

Two or more Claude Code sessions discover each other and exchange messages by
reading and writing files under a shared **bus** directory. There is no daemon
and no network — the transport is just files. This works for:

- **Same machine / same cluster** (shared `$HOME`): just use the default group.
- **Across machines**: point every session at the same synced/mounted folder.

All operations go through the bundled `fs-chat` CLI (installed with this
package). It handles atomic writes, per-directory identity, and liveness, so
prefer it over hand-rolling file reads/writes.

## Groups and the bus path (READ THIS FIRST)

A **group** (chat room) is one directory. Peers only see others in the **same
group**. The bus path resolves as (first hit wins):

1. `--dir PATH` (or `MAD_SKILLS_FS_CHAT_DIR`) → used **verbatim**.
2. else `--group NAME` (or `MAD_SKILLS_FS_CHAT_GROUP`) → `~/.mad-skills/fs-chat/<NAME>`.
3. else **the dir+name saved by the last `register` in this working directory**.
4. else the default group `all`.

**Register once, then drop the flags.** Because of step 3, you only pass the
dir/group and `--name` on the **`register`** call. `register` saves them for the
current working directory, so every later command (`peers`, `send`, `inbox`,
`watch`) needs **no flags** — they automatically reuse the same bus and
identity. (This relies on running all commands from the same working directory,
which a Claude Code session does.)

Map the user's words to the register flag:
- "in group X" / "join the X chat" → `--group X`
- an explicit path like `/home/me/.mad-skills/fs-chat/kube-chat` → `--dir <that path>`
- nothing specified → omit (default group `all`)

Example — the user says *"register on fs-chat as alice on
/home/iskorokhodov/.mad-skills/fs-chat/kube-chat, then watch for messages"*:

```bash
fs-chat --dir /home/iskorokhodov/.mad-skills/fs-chat/kube-chat register --name alice
fs-chat watch          # no flags needed — reuses the dir from register
```

(That path is exactly `~/.mad-skills/fs-chat/kube-chat`, so `--group kube-chat`
at register time is equivalent and shorter.)

## Workflow

1. **Register** this session once, with the dir/group + name. This saves them
   for the working directory (re-run periodically to refresh liveness;
   heartbeats go stale after 120s):

   ```bash
   fs-chat --group <g> register --name "alice" --summary "what I'm doing"
   ```

2. **Discover peers** — get their ids before messaging (no flags from here on):

   ```bash
   fs-chat --json peers
   ```

3. **Send** to a peer by id (`-` as the body reads stdin for long/multiline):

   ```bash
   fs-chat send <peer_id> "can you take the frontend tests?"
   ```

4. **Receive** — read and consume your inbox:

   ```bash
   fs-chat --json inbox     # returns messages, then deletes them
   fs-chat inbox --peek     # read without consuming
   ```

5. **Stay current** — for a live conversation, run a background watcher (launch
   it with the Bash tool in the background) so new messages stream in without
   manual polling:

   ```bash
   fs-chat watch --interval 1
   ```

## Guidance for Claude

- Pass `--group`/`--dir` and `--name` **only on `register`**; later commands
  reuse them automatically. Only re-pass a flag to switch group mid-session.
- Put `--group`/`--dir`/`--json` before the subcommand: `fs-chat --json peers`.
- Use `--json` whenever you need to parse output (peers, inbox); use the plain
  form only when showing the user.
- You must `register` before peers can find you; re-register (or run any
  command) to stay listed.
- `inbox` **consumes** messages (deletes after reading). Use `--peek` to look
  without consuming. Don't call `inbox` repeatedly expecting the same messages.
- To message a peer you need its `peer_id` from `peers`, not its display name.
- The loop for "talk to the other session": `register` → `peers` (find target
  id) → `send` → `watch` (or `inbox`) for replies. Prefer a background `watch`
  over polling `inbox` for an extended back-and-forth.

## Full command reference

```
fs-chat [--group NAME | --dir PATH] [--json] <subcommand>

  register [--name NAME] [--summary TEXT]   announce this session
  whoami                                    show your peer identity
  set-summary TEXT                          update your status
  peers [--all] [--scope all|machine|dir] [--stale-seconds N]
  send PEER_ID MESSAGE                      MESSAGE='-' reads stdin
  inbox [--peek]                            read (and consume) messages
  watch [--interval SECONDS]                stream messages until Ctrl-C
  unregister                                remove your heartbeat
```

Env vars: `MAD_SKILLS_FS_CHAT_DIR` (explicit bus path),
`MAD_SKILLS_FS_CHAT_GROUP` (group name).
