"""Manage guest portal access.

    uv run python -m qivis.guest.cli init --public-url https://host.tailnet.ts.net
    uv run python -m qivis.guest.cli add "Alice"      # prints Alice's personal invite link
    uv run python -m qivis.guest.cli list
    uv run python -m qivis.guest.cli revoke "Alice"
    uv run python -m qivis.guest.cli models
    uv run python -m qivis.guest.cli url https://host.tailnet.ts.net   # set the public URL

The running server picks up changes immediately (it re-reads the file).
"""

import argparse
import sys
import uuid
from datetime import UTC, datetime

from qivis.guest import auth
from qivis.guest.config import Guest, GuestModel, config_path, load, new_config, save

SUN = GuestModel(
    id="sun-1.0.1",
    label="Sun",
    provider="llamacpp",
    model="Sun-v1.0.1-8B.Q4_K_M.gguf",
    generation_mode="completion",
    prompt_template="llama3",
    sampling_params={"max_tokens": 1024, "logprobs": True, "top_logprobs": 5},
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="qivis.guest.cli")
    sub = parser.add_subparsers(dest="cmd", required=True)
    p_init = sub.add_parser("init", help="create the config (with Sun as the first model)")
    p_init.add_argument("--public-url", default="")
    p_add = sub.add_parser("add", help="invite a guest; prints their personal link")
    p_add.add_argument("name")
    p_rev = sub.add_parser("revoke", help="cut off a guest immediately")
    p_rev.add_argument("name")
    sub.add_parser("list")
    sub.add_parser("models")
    p_url = sub.add_parser("url", help="set the public URL used in invite links")
    p_url.add_argument("public_url")
    args = parser.parse_args(argv)
    path = config_path()

    if args.cmd == "init":
        if path.exists():
            print(f"{path} already exists", file=sys.stderr)
            return 1
        cfg = new_config()
        cfg.public_url = args.public_url.rstrip("/")
        cfg.models = [SUN]
        save(cfg, path)
        print(f"wrote {path}")
        return 0

    cfg = load(path)
    if args.cmd == "add":
        if any(g.name == args.name and not g.revoked for g in cfg.guests):
            print(
                f"{args.name} already has access (revoke first to issue a new link)",
                file=sys.stderr,
            )
            return 1
        token = auth.new_token()
        cfg.guests.append(
            Guest(
                id=uuid.uuid4().hex[:12],
                name=args.name,
                token_sha256=auth.hash_token(token),
                created_at=datetime.now(UTC).isoformat(),
            )
        )
        save(cfg, path)
        base = cfg.public_url or "http://127.0.0.1:8100"
        print(f"Invite link for {args.name} (shown once; send it privately):\n{base}/i/{token}")
    elif args.cmd == "revoke":
        hits = [g for g in cfg.guests if g.name == args.name and not g.revoked]
        if not hits:
            print(f"no active guest named {args.name}", file=sys.stderr)
            return 1
        for g in hits:
            g.revoked = True
        save(cfg, path)
        print(f"revoked {args.name}")
    elif args.cmd == "list":
        for g in cfg.guests:
            print(
                f"{g.name:20} {'revoked' if g.revoked else 'active':8} since {g.created_at[:10]}  id={g.id}"
            )
    elif args.cmd == "url":
        cfg.public_url = args.public_url.rstrip("/")
        save(cfg, path)
        print(f"public URL set to {cfg.public_url}")
    elif args.cmd == "models":
        for m in cfg.models:
            print(f"{m.id:16} {m.label:12} {m.provider}/{m.model} ({m.generation_mode})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
