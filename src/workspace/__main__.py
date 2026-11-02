"""Zero-spend workspace administration and one-shot durable worker."""
from __future__ import annotations

import argparse
import json

from src.tools.postgres_pool import close_pool, get_pool
from src.workspace.scheduler import run_once
from src.workspace.store import WorkspaceStore


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("verb", choices=["migrate", "worker-once", "refresh", "export"])
    parser.add_argument("--owner", default="personal-local")
    parser.add_argument("--sources", nargs="*", default=[])
    args = parser.parse_args()
    store = WorkspaceStore(get_pool())
    try:
        store.migrate()
        if args.verb == "migrate":
            print("workspace schema migrated; no source/model calls")
        elif args.verb == "worker-once":
            from src.workspace import routes
            routes._store = store
            result = run_once(store, lambda owner: routes.refresh(owner, [], persist_edition=False))
            print(json.dumps(result or {"state": "idle", "reason": "no enabled due schedule"}))
        elif args.verb == "refresh":
            from src.workspace import routes
            routes._store = store
            print(json.dumps(routes.refresh(args.owner, args.sources), indent=2))
        else:
            print(json.dumps({"profile": store.profile(args.owner), "works": store.works(args.owner)}, indent=2))
    finally:
        close_pool()


if __name__ == "__main__":
    main()
