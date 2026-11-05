"""Existing canonical CI fixture, only in the owned empty P7 CI database."""


def main():
    import json
    import os
    import runpy
    from pathlib import Path
    from urllib.parse import urlsplit

    import psycopg

    p = Path("planning/12-workspace-controller-revamp/evidence/after/p7-polish/ci")
    m = json.loads((p / "setup.json").read_text())
    u = urlsplit(os.environ["POSTGRES_URL"])
    assert m["databaseCreated"] and m["database"] == "workspace_controller_p7_ci"
    assert (
        u.hostname == "127.0.0.1"
        and u.port == 15458
        and u.path == "/" + m["database"]
        and u.username == "workspace"
    )
    assert (
        os.environ["POSTGRES_URL"] == os.environ["WORKSPACE_RATE_DATABASE_URL"]
        and os.environ["E2E_PRINCIPAL"] == m["principal"]
    )
    assert (
        os.environ["WORKSPACE_E2E_SEED"] == "1"
        and os.environ["ANTHROPIC_API_KEY"] == "local-preview-disabled"
        and os.environ["USE_MOCK_DATA"] == "true"
    )
    with psycopg.connect(os.environ["POSTGRES_URL"]) as conn:
        assert conn.execute("SELECT current_database()").fetchone()[0] == m["database"]
        assert (
            conn.execute(
                "SELECT shobj_description(oid,'pg_database') FROM pg_database WHERE datname=current_database()"
            ).fetchone()[0]
            == m["runId"]
        )
        assert (
            conn.execute(
                "SELECT count(*) FROM information_schema.tables WHERE table_schema='public' AND table_type='BASE TABLE'"
            ).fetchone()[0]
            == 0
        )
    import src

    assert Path(src.__file__).resolve().is_relative_to(Path.cwd().resolve())
    runpy.run_path("web/e2e/fixtures/workspace_seed.py", run_name="__main__")


main()
