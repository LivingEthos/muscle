"""
Idempotency tests for every registered project-memory migration (MG-01/MG-02/TEST-04).

For each ``(version, migrate_fn)`` in :func:`tools.muscle.migrations._load_migrations`
we:

1. Create a fresh ``:memory:`` sqlite3 DB.
2. Apply every prior migration in order up to and including the target.
3. Capture the resulting schema via ``sqlite_master``.
4. Re-apply only the target migration a second time (via its own ``migrate()``
   function — i.e. the same entry-point the runner uses).
5. Assert the second call is a no-op: no exception, and the schema string is
   byte-for-byte unchanged.

This guards against the common failure mode where a migration forgets
``IF NOT EXISTS`` or re-inserts its version row and crashes on UNIQUE violation
if it is re-run against an already-upgraded database.
"""

from __future__ import annotations

import logging
import sqlite3

import pytest

from tools.muscle.migrations import _load_migrations

logger = logging.getLogger(__name__)


def _schema_snapshot(conn: sqlite3.Connection) -> list[tuple[str, str, str | None]]:
    """Return a stable, ordered snapshot of the schema.

    Each tuple is ``(type, name, sql)``. We sort by ``(type, name)`` so the
    comparison is deterministic regardless of insertion order.
    """
    rows = conn.execute(
        "SELECT type, name, sql FROM sqlite_master "
        "WHERE name NOT LIKE 'sqlite_%' "
        "ORDER BY type, name"
    ).fetchall()
    return [(row[0], row[1], row[2]) for row in rows]


def _apply_up_to(
    conn: sqlite3.Connection,
    migrations: list[tuple[str, object, object | None]],
    target_version: str,
) -> None:
    """Apply every migration in order up to and including ``target_version``.

    Uses the migration modules' own ``migrate(conn)`` entry points — i.e. the
    exact callable the :class:`MigrationRunner` invokes.
    """
    # Ensure schema_version exists the way the runner would ensure it.
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_version (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            version TEXT NOT NULL UNIQUE,
            applied_at TEXT NOT NULL
        )
        """
    )
    conn.commit()

    for version, migrate_fn, _rollback in migrations:
        migrate_fn(conn)  # type: ignore[operator]
        if version == target_version:
            return


# Build a parametrized registry of (version, migrate_fn) pairs — one test per
# migration. We resolve the list at import time so pytest can show one case
# per version in -v output.
_REGISTRY = _load_migrations()
_IDS = [version for version, _m, _r in _REGISTRY]


@pytest.mark.parametrize(
    ("version", "migrate_fn"),
    [(version, migrate_fn) for version, migrate_fn, _rollback in _REGISTRY],
    ids=_IDS,
)
def test_migration_is_idempotent(version: str, migrate_fn: object) -> None:
    """Re-applying a migration against its own output must be a no-op.

    We apply every migration up to (and including) ``version`` against a
    fresh in-memory DB, snapshot the schema, then re-invoke just the target
    migration's ``migrate()`` function. The second call must:

    * not raise, and
    * leave the schema snapshot byte-for-byte unchanged.
    """
    conn = sqlite3.connect(":memory:")
    try:
        _apply_up_to(conn, _REGISTRY, version)
        first_schema = _schema_snapshot(conn)

        # Second application: same entry-point as the runner uses.
        result = migrate_fn(conn)  # type: ignore[operator]
        # On re-apply every migration in this repo returns False ("already
        # applied"). We accept any non-raising return value, but we do assert
        # it did not raise above.
        assert result in (False, None), (
            f"Migration {version} re-apply returned {result!r}; expected False/None"
        )

        second_schema = _schema_snapshot(conn)
        assert first_schema == second_schema, (
            f"Migration {version} is NOT idempotent: schema changed on "
            f"second apply. First: {first_schema!r} Second: {second_schema!r}"
        )

        # schema_version row for this version must exist exactly once.
        cursor = conn.execute(
            "SELECT COUNT(*) FROM schema_version WHERE version = ?",
            (version,),
        )
        count = cursor.fetchone()[0]
        assert count == 1, (
            f"Migration {version} produced {count} rows in schema_version "
            "after double-apply; expected exactly 1."
        )
    finally:
        conn.close()
