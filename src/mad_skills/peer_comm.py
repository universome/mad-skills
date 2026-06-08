"""Filesystem-based peer messaging for Claude Code sessions.

Two or more Claude instances communicate by reading/writing files under a
shared "bus" directory. No daemon, no network: point ``MAD_SKILLS_PEER_DIR``
at any shared path (a synced folder, an NFS/SMB mount, or just a local dir for
same-machine sessions) and the peers find each other.

Bus layout (shared, may live on a mounted/synced filesystem)::

    <bus>/peers/<peer_id>.json        one heartbeat file per live peer
    <bus>/inbox/<peer_id>/<msg>.json  messages addressed to that peer

Identity is stored locally (NOT on the shared bus), keyed by working
directory, so repeated invocations from the same project reuse one peer id.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import socket
import sys
import tempfile
import time
import uuid
from pathlib import Path

DEFAULT_HOME = Path.home() / ".mad-skills" / "peer-comm"
# A peer is considered "live" if its heartbeat was touched within this window.
DEFAULT_STALE_SECONDS = 120


# --------------------------------------------------------------------------- #
# Paths
# --------------------------------------------------------------------------- #
def bus_dir() -> Path:
    """Shared message bus. Override with MAD_SKILLS_PEER_DIR."""
    env = os.environ.get("MAD_SKILLS_PEER_DIR")
    base = Path(env).expanduser() if env else DEFAULT_HOME / "bus"
    return base


def state_dir() -> Path:
    """Machine-local identity store (never shared across machines)."""
    return DEFAULT_HOME / "state"


def _cwd_key() -> str:
    cwd = os.path.realpath(os.getcwd())
    return hashlib.sha1(cwd.encode()).hexdigest()[:16]


def peers_dir() -> Path:
    return bus_dir() / "peers"


def inbox_dir(peer_id: str) -> Path:
    return bus_dir() / "inbox" / peer_id


# --------------------------------------------------------------------------- #
# Atomic IO helpers
# --------------------------------------------------------------------------- #
def _atomic_write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(data, f, indent=2)
            f.write("\n")
        os.replace(tmp, path)  # atomic on POSIX
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def _read_json(path: Path) -> dict | None:
    try:
        with open(path) as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


# --------------------------------------------------------------------------- #
# Identity
# --------------------------------------------------------------------------- #
def _identity_path() -> Path:
    return state_dir() / f"{_cwd_key()}.json"


def load_or_create_identity(name: str | None = None) -> dict:
    path = _identity_path()
    ident = _read_json(path)
    if ident is None:
        ident = {
            "id": uuid.uuid4().hex[:12],
            "name": name or Path(os.getcwd()).name,
            "cwd": os.path.realpath(os.getcwd()),
            "host": socket.gethostname(),
            "summary": "",
        }
        _atomic_write_json(path, ident)
    elif name and name != ident.get("name"):
        ident["name"] = name
        _atomic_write_json(path, ident)
    return ident


def _publish_heartbeat(ident: dict) -> None:
    record = dict(ident)
    record["last_seen"] = time.time()
    record["last_seen_iso"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    _atomic_write_json(peers_dir() / f"{ident['id']}.json", record)


# --------------------------------------------------------------------------- #
# Commands
# --------------------------------------------------------------------------- #
def cmd_register(args) -> int:
    ident = load_or_create_identity(args.name)
    if args.summary is not None:
        ident["summary"] = args.summary
        _atomic_write_json(_identity_path(), ident)
    _publish_heartbeat(ident)
    inbox_dir(ident["id"]).mkdir(parents=True, exist_ok=True)
    _emit(args, {"registered": ident})
    return 0


def cmd_whoami(args) -> int:
    _emit(args, {"identity": load_or_create_identity()})
    return 0


def cmd_set_summary(args) -> int:
    ident = load_or_create_identity()
    ident["summary"] = args.text
    _atomic_write_json(_identity_path(), ident)
    _publish_heartbeat(ident)
    _emit(args, {"ok": True, "summary": args.text})
    return 0


def cmd_peers(args) -> int:
    ident = load_or_create_identity()
    _publish_heartbeat(ident)  # announce ourselves while we look
    now = time.time()
    out = []
    pdir = peers_dir()
    if pdir.exists():
        for f in sorted(pdir.glob("*.json")):
            rec = _read_json(f)
            if not rec:
                continue
            age = now - rec.get("last_seen", 0)
            rec["age_seconds"] = round(age, 1)
            rec["self"] = rec.get("id") == ident["id"]
            if not args.all and age > args.stale_seconds:
                continue
            if args.scope == "machine" and rec.get("host") != ident["host"]:
                continue
            if args.scope == "dir" and rec.get("cwd") != ident["cwd"]:
                continue
            out.append(rec)
    _emit(args, {"peers": out, "count": len(out)})
    return 0


def cmd_send(args) -> int:
    ident = load_or_create_identity()
    _publish_heartbeat(ident)
    body = args.message
    if body == "-":  # read from stdin
        body = sys.stdin.read()
    msg = {
        "id": uuid.uuid4().hex[:12],
        "from": ident["id"],
        "from_name": ident["name"],
        "to": args.peer_id,
        "ts": time.time(),
        "ts_iso": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "body": body,
    }
    # nanosecond prefix keeps inbox files lexically ordered by arrival
    fname = f"{time.time_ns()}-{msg['id']}.json"
    _atomic_write_json(inbox_dir(args.peer_id) / fname, msg)
    _emit(args, {"sent": {"to": args.peer_id, "id": msg["id"]}})
    return 0


def cmd_inbox(args) -> int:
    ident = load_or_create_identity()
    _publish_heartbeat(ident)
    box = inbox_dir(ident["id"])
    msgs = []
    if box.exists():
        for f in sorted(box.glob("*.json")):
            rec = _read_json(f)
            if rec is None:
                continue
            msgs.append(rec)
            if not args.peek:
                try:
                    f.unlink()  # consume
                except OSError:
                    pass
    _emit(args, {"messages": msgs, "count": len(msgs)})
    return 0


def cmd_watch(args) -> int:
    ident = load_or_create_identity()
    box = inbox_dir(ident["id"])
    box.mkdir(parents=True, exist_ok=True)
    sys.stderr.write(
        f"watching inbox for {ident['name']} ({ident['id']}); Ctrl-C to stop\n"
    )
    sys.stderr.flush()
    try:
        while True:
            _publish_heartbeat(ident)
            for f in sorted(box.glob("*.json")):
                rec = _read_json(f)
                if rec is None:
                    continue
                line = json.dumps(rec) if args.json else (
                    f"[{rec.get('ts_iso','')}] {rec.get('from_name','?')}"
                    f" ({rec.get('from','?')}): {rec.get('body','')}"
                )
                print(line, flush=True)
                try:
                    f.unlink()
                except OSError:
                    pass
            time.sleep(args.interval)
    except KeyboardInterrupt:
        return 0


def cmd_unregister(args) -> int:
    ident = load_or_create_identity()
    try:
        (peers_dir() / f"{ident['id']}.json").unlink()
    except OSError:
        pass
    _emit(args, {"unregistered": ident["id"]})
    return 0


# --------------------------------------------------------------------------- #
# Output
# --------------------------------------------------------------------------- #
def _emit(args, payload: dict) -> None:
    if getattr(args, "json", False):
        print(json.dumps(payload, indent=2))
        return
    # Human-readable rendering
    if "peers" in payload:
        if not payload["peers"]:
            print("(no live peers)")
        for p in payload["peers"]:
            tag = " (you)" if p.get("self") else ""
            summary = f" — {p['summary']}" if p.get("summary") else ""
            print(
                f"{p['id']}  {p['name']}{tag}  [{p.get('host','?')}:"
                f"{p.get('cwd','?')}]  {p['age_seconds']}s ago{summary}"
            )
    elif "messages" in payload:
        if not payload["messages"]:
            print("(no new messages)")
        for m in payload["messages"]:
            print(
                f"[{m.get('ts_iso','')}] {m.get('from_name','?')} "
                f"({m.get('from','?')}): {m.get('body','')}"
            )
    else:
        print(json.dumps(payload, indent=2))


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="fs-chat",
        description="Communicate between Claude Code sessions over a shared "
        "filesystem. Set MAD_SKILLS_PEER_DIR to the shared bus path.",
    )
    p.add_argument(
        "--json", action="store_true", help="emit machine-readable JSON"
    )
    sub = p.add_subparsers(dest="command", required=True)

    sp = sub.add_parser("register", help="announce this session as a peer")
    sp.add_argument("--name", help="display name (default: directory name)")
    sp.add_argument("--summary", help="what this session is working on")
    sp.set_defaults(func=cmd_register)

    sp = sub.add_parser("whoami", help="show this session's peer identity")
    sp.set_defaults(func=cmd_whoami)

    sp = sub.add_parser("set-summary", help="update this session's summary")
    sp.add_argument("text")
    sp.set_defaults(func=cmd_set_summary)

    sp = sub.add_parser("peers", help="list live peers")
    sp.add_argument("--all", action="store_true", help="include stale peers")
    sp.add_argument(
        "--stale-seconds", type=float, default=DEFAULT_STALE_SECONDS,
        help=f"liveness window (default {DEFAULT_STALE_SECONDS}s)",
    )
    sp.add_argument(
        "--scope", choices=["all", "machine", "dir"], default="all",
        help="restrict to same machine or same directory",
    )
    sp.set_defaults(func=cmd_peers)

    sp = sub.add_parser("send", help="send a message to a peer")
    sp.add_argument("peer_id", help="recipient peer id (see `peers`)")
    sp.add_argument("message", help="message body, or '-' to read stdin")
    sp.set_defaults(func=cmd_send)

    sp = sub.add_parser("inbox", help="read (and consume) your messages")
    sp.add_argument(
        "--peek", action="store_true", help="do not delete after reading"
    )
    sp.set_defaults(func=cmd_inbox)

    sp = sub.add_parser("watch", help="block and stream incoming messages")
    sp.add_argument("--interval", type=float, default=1.0)
    sp.set_defaults(func=cmd_watch)

    sp = sub.add_parser("unregister", help="remove this session's heartbeat")
    sp.set_defaults(func=cmd_unregister)

    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
