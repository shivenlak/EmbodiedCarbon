"""Factor store and provider interface.

Adheres strictly to the requirements in RESEARCH.md §9 and docs/PLAN.md Step 11:
  - Zero numeric factors in application code (all live in seed JSON / SQLite DB).
  - Every row carries non-null source, declared_unit, geography, and modules.
  - Pluggable FactorProvider ABC:
      * LocalSnapshotProvider: SQLite database backed by seed_factors.json
      * EC3Provider: stubbed for live API integration
  - Prevents commercial use of ICE Database (prohibited by ICE licence).
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from abc import ABC, abstractmethod
from datetime import date
from pathlib import Path

from ecarbon.models import FactorRef

SEED_FILE = Path(__file__).resolve().parent / "seed_factors.json"
DEFAULT_DB_PATH = Path(__file__).resolve().parent / "factors.sqlite3"


class FactorProvider(ABC):
    """Abstract interface for carbon factor resolution."""

    @abstractmethod
    def get_factor(self, factor_id: str) -> FactorRef | None:
        """Fetch factor by its unique identifier."""
        pass

    @abstractmethod
    def find_by_material(self, material_name: str) -> FactorRef | None:
        """Find default factor matching a CMHC material string or key."""
        pass

    @abstractmethod
    def list_factors(self) -> list[FactorRef]:
        """List all available factors in this provider."""
        pass

    @abstractmethod
    def list_substitutions(self) -> list[dict]:
        """List available material substitutions."""
        pass


class LocalSnapshotProvider(FactorProvider):
    """Local SQLite-backed factor store seeded from BEAM and EC3 snapshots."""

    def __init__(self, db_path: Path | str | None = None, seed_path: Path | str | None = None) -> None:
        self.db_path = Path(db_path or DEFAULT_DB_PATH)
        self.seed_path = Path(seed_path or SEED_FILE)
        self._init_db()

    def _get_conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        conn = self._get_conn()
        try:
            cur = conn.cursor()
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS factors (
                    factor_id TEXT PRIMARY KEY,
                    material_key TEXT,
                    name TEXT NOT NULL,
                    source TEXT NOT NULL,
                    source_id TEXT,
                    declared_unit TEXT NOT NULL,
                    density_kg_m3 REAL,
                    gwp_value REAL NOT NULL,
                    gwp_unit TEXT NOT NULL,
                    modules TEXT NOT NULL,
                    geography TEXT NOT NULL,
                    valid_from TEXT,
                    valid_to TEXT,
                    data_type TEXT NOT NULL,
                    uncertainty_pct REAL,
                    attribution TEXT
                )
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS material_mappings (
                    cmhc_name TEXT PRIMARY KEY,
                    default_factor_id TEXT NOT NULL,
                    category TEXT NOT NULL,
                    assembly_class TEXT,
                    density_kg_m3 REAL,
                    waste_factor REAL
                )
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS substitutions (
                    swap_id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    target_material TEXT NOT NULL,
                    from_factor_id TEXT NOT NULL,
                    to_factor_id TEXT NOT NULL,
                    description TEXT NOT NULL,
                    category TEXT NOT NULL
                )
                """
            )
            cur.execute(
                "CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT)"
            )

            # Re-seed whenever the seed file's contents differ from what was
            # loaded, not merely when the table is empty.
            #
            # Seeding only into an empty table silently pinned this database to
            # whatever the seed said the first time it was built. Two factor
            # corrections -- GUL + 40% fly ash from 142 to 175 kgCO2e/m3, and
            # the removal of a fabricated "GU 20 MPa" record -- sat in the JSON
            # for days without ever reaching the runtime, so the low-carbon
            # concrete substitution reported a 48.5% saving where the corrected
            # factor gives 36.6%, and an invented factor stayed live in a tool
            # whose entire claim is that every factor is a sourced record. The
            # database is a cache; the JSON is the source of truth.
            if self.seed_path.exists():
                digest = hashlib.sha256(self.seed_path.read_bytes()).hexdigest()
                cur.execute("SELECT value FROM meta WHERE key = 'seed_sha256'")
                row = cur.fetchone()
                if row is None or row[0] != digest:
                    self._load_seed(conn)
                    cur.execute(
                        "INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)",
                        ("seed_sha256", digest),
                    )
            conn.commit()
        finally:
            conn.close()

    def _load_seed(self, conn: sqlite3.Connection) -> None:
        """Bring the database in line with the seed, both ways.

        Rows are upserted *and* rows the seed no longer contains are deleted.
        Without the delete, a record withdrawn for being wrong -- a fabricated
        concrete factor, in the case that prompted this -- would outlive its
        own correction.
        """
        with open(self.seed_path, encoding="utf-8") as f:
            data = json.load(f)

        cur = conn.cursor()
        for table, key, rows in (
            ("factors", "factor_id", data.get("factors", [])),
            ("substitutions", "swap_id", data.get("substitutions", [])),
        ):
            keep = [r[key] for r in rows]
            if keep:
                marks = ",".join("?" * len(keep))
                cur.execute(
                    f"DELETE FROM {table} WHERE {key} NOT IN ({marks})", keep
                )
        for f in data.get("factors", []):
            cur.execute(
                """
                INSERT OR REPLACE INTO factors (
                    factor_id, material_key, name, source, source_id,
                    declared_unit, density_kg_m3, gwp_value, gwp_unit,
                    modules, geography, valid_from, valid_to,
                    data_type, uncertainty_pct, attribution
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    f["factor_id"],
                    f.get("material_key"),
                    f["name"],
                    f["source"],
                    f.get("source_id"),
                    f["declared_unit"],
                    f.get("density_kg_m3"),
                    f["gwp_value"],
                    f.get("gwp_unit", "kgCO2e"),
                    json.dumps(f["modules"]),
                    f["geography"],
                    f.get("valid_from"),
                    f.get("valid_to"),
                    f["data_type"],
                    f.get("uncertainty_pct"),
                    f.get("attribution"),
                ),
            )

        for cmhc_name, m in data.get("cmhc_mappings", []).items() if isinstance(data.get("cmhc_mappings"), dict) else []:
            cur.execute(
                """
                INSERT OR REPLACE INTO material_mappings (
                    cmhc_name, default_factor_id, category, assembly_class,
                    density_kg_m3, waste_factor
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    cmhc_name,
                    m["default_factor_id"],
                    m.get("category", "Other"),
                    m.get("assembly_class"),
                    m.get("density_kg_m3"),
                    m.get("waste_factor", 0.0),
                ),
            )

        for s in data.get("substitutions", []):
            cur.execute(
                """
                INSERT OR REPLACE INTO substitutions (
                    swap_id, title, target_material, from_factor_id,
                    to_factor_id, description, category
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    s["swap_id"],
                    s["title"],
                    s["target_material"],
                    s["from_factor_id"],
                    s["to_factor_id"],
                    s["description"],
                    s.get("category", "General"),
                ),
            )

    def _row_to_factor(self, row: sqlite3.Row) -> FactorRef:
        mods = json.loads(row["modules"])
        vfrom = date.fromisoformat(row["valid_from"]) if row["valid_from"] else None
        vto = date.fromisoformat(row["valid_to"]) if row["valid_to"] else None
        return FactorRef(
            factor_id=row["factor_id"],
            name=row["name"],
            source=row["source"],
            source_id=row["source_id"],
            declared_unit=row["declared_unit"],
            gwp_value=float(row["gwp_value"]),
            gwp_unit=row["gwp_unit"],
            modules=mods,
            geography=row["geography"],
            data_type=row["data_type"],
            valid_from=vfrom,
            valid_to=vto,
            uncertainty_pct=float(row["uncertainty_pct"]) if row["uncertainty_pct"] is not None else None,
            attribution=row["attribution"],
            density_kg_m3=float(row["density_kg_m3"]) if row["density_kg_m3"] is not None else None,
        )

    def get_factor(self, factor_id: str) -> FactorRef | None:
        conn = self._get_conn()
        try:
            cur = conn.cursor()
            cur.execute("SELECT * FROM factors WHERE factor_id = ?", (factor_id,))
            row = cur.fetchone()
            return self._row_to_factor(row) if row else None
        finally:
            conn.close()

    def find_by_material(self, material_name: str) -> FactorRef | None:
        conn = self._get_conn()
        try:
            cur = conn.cursor()
            # 1. Direct mapping
            cur.execute(
                """
                SELECT f.* FROM factors f
                JOIN material_mappings m ON f.factor_id = m.default_factor_id
                WHERE m.cmhc_name = ?
                """,
                (material_name,),
            )
            row = cur.fetchone()
            if row:
                return self._row_to_factor(row)

            # 2. Material key or substring
            cur.execute("SELECT * FROM factors WHERE material_key = ?", (material_name,))
            row = cur.fetchone()
            if row:
                return self._row_to_factor(row)

            # 3. Case-insensitive substring match
            low = f"%{material_name.lower().replace('cmhc_', '')}%"
            cur.execute("SELECT * FROM factors WHERE lower(name) LIKE ? OR lower(material_key) LIKE ? LIMIT 1", (low, low))
            row = cur.fetchone()
            return self._row_to_factor(row) if row else None
        finally:
            conn.close()

    def list_factors(self) -> list[FactorRef]:
        conn = self._get_conn()
        try:
            cur = conn.cursor()
            cur.execute("SELECT * FROM factors ORDER BY name ASC")
            return [self._row_to_factor(r) for r in cur.fetchall()]
        finally:
            conn.close()

    def list_substitutions(self) -> list[dict]:
        conn = self._get_conn()
        try:
            cur = conn.cursor()
            cur.execute("SELECT * FROM substitutions")
            return [dict(r) for r in cur.fetchall()]
        finally:
            conn.close()


class EC3Provider(FactorProvider):
    """Stubbed provider for live Building Transparency EC3 API integration."""

    def __init__(self, api_key: str | None = None) -> None:
        self.api_key = api_key

    def get_factor(self, factor_id: str) -> FactorRef | None:
        raise NotImplementedError("Live EC3 API requires professional account token; use LocalSnapshotProvider.")

    def find_by_material(self, material_name: str) -> FactorRef | None:
        raise NotImplementedError("Live EC3 API requires professional account token; use LocalSnapshotProvider.")

    def list_factors(self) -> list[FactorRef]:
        return []

    def list_substitutions(self) -> list[dict]:
        return []
