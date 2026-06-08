---
name: fs-chat
description: >-
  Chat between Claude Code sessions over a shared filesystem — no server, no
  network, just files. Use when the user wants this session to talk to, message,
  coordinate with, or hand off work to another Claude/Claude Code instance
  (same machine or via a shared/synced folder), or asks to "see who else is
  running", "send a message to the other session", or "set up peer chat".
---

# fs-chat — filesystem peer chat

Two or more Claude Code sessions discover each other and exchange messages by
reading and writing files under a shared **bus** directory. There is no daemon
and no network — the transport is just files. This works for:

- **Same machine**: multiple sessions in different projects (default bus dir).
- **Different machines**: point every session's `MAD_SKILLS_PEER_DIR` at the
  same synced/mounted folder (Dropbox, iCloud, NFS, SMB, etc.).

All operations go through the bundled `fs-chat` CLI (installed with this
package). It handles atomic writes, per-directory identity, and liveness, so
prefer it over hand-rolling file reads/writes.

## Configuration

- `MAD_SKILLS_PEER_DIR` — the shared bus path. If unset, defaults to
  `~/.mad-skills/peer-comm/bus` (fine for same-machine sessions). To chat
  across machines, set this to a shared folder **in every session**.

Each working directory gets a stable peer identity automatically; its default
display name is the directory's basename.

## Workflow

1. **Register** this session so others can see it (run once per session, and
   re-run periodically to refresh liveness — heartbeats go stale after 120s):

   ```bash
   fs-chat register --name "backend" --summary "refactoring the auth module"
   ```

2. **Discover peers** — get their ids before messaging:

   ```bash
   fs-chat --json peers              # all live peers, machine-readable
   fs-chat peers --scope machine     # only this machine
   ```

3. **Send** a message to a peer by id (body can be `-` to read from stdin for
   long/multiline content):

   ```bash
   fs-chat send <peer_id> "can you take the frontend tests?"
   ```

4. **Receive** — read and consume your inbox:

   ```bash
   fs-chat --json inbox        # returns messages, then deletes them
   fs-chat inbox --peek        # read without consuming
   ```

5. **Stay current** — for a live conversation, run a background watcher so new
   messages stream in without manual polling. Launch it with the Bash tool in
   the background, then read its output as messages arrive:

   ```bash
   fs-chat watch --interval 1
   ```

## Guidance for Claude

- Use `--json` whenever you need to parse output (peers, inbox); use the plain
  form only when showing the user.
- You must call `register` before peers can find you, and re-register (or run
  any command — every command refreshes your heartbeat) to stay listed.
- `inbox` **consumes** messages (deletes them after reading). Use `--peek` if
  you only want to look. Don't call `inbox` repeatedly expecting the same
  messages back.
- To message a peer you need its `peer_id` from `peers`, not its display name.
- When the user asks to "talk to the other session", the loop is:
  `register` → `peers` (find the target id) → `send` → `inbox`/`watch` for
  replies.
- For an extended back-and-forth, prefer a background `watch` over polling
  `inbox` in a loop.

## Full command reference

```
fs-chat register [--name NAME] [--summary TEXT]   announce this session
fs-chat whoami                                    show your peer identity
fs-chat set-summary TEXT                          update your status
fs-chat peers [--all] [--scope all|machine|dir] [--stale-seconds N]
fs-chat send PEER_ID MESSAGE                      MESSAGE='-' reads stdin
fs-chat inbox [--peek]                            read (and consume) messages
fs-chat watch [--interval SECONDS]                stream messages until Ctrl-C
fs-chat unregister                                remove your heartbeat
```

Add `--json` before any subcommand for machine-readable output.
