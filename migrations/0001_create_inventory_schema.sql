-- Esquema fundacional del catálogo SQLite (Fase 5 -- ver docs/ARCHITECTURE.md y DECISIONS.md #12).
-- DDL tal cual quedó fijado en el plan de diseño: identidad estable (`id`), lookup real por
-- (library_id, current_path), jerarquía show->season->episode reutilizando parent_id/
-- relation_to_parent ya modelados en domain/models.py, season/episode como columnas DERIVADAS
-- (nunca se añaden a domain/models.py).

CREATE TABLE IF NOT EXISTS schema_migrations (
    version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL, description TEXT NOT NULL
);

CREATE TABLE inventory_items (
    id TEXT PRIMARY KEY,               -- mismo UUID que InventoryItem.id, estable entre syncs
    library_id TEXT NOT NULL,
    authorized_root TEXT NOT NULL,
    current_path TEXT NOT NULL,
    extension TEXT NOT NULL,
    content_type TEXT NOT NULL CHECK (content_type IN (
        'movie','tv_show','tv_season','tv_episode',
        'music_artist','music_album','music_track','photo','other_video','extra')),
    item_state TEXT NOT NULL CHECK (item_state IN (
        'discovered','parsed','matched','needs_review','planned',
        'applied','verified','failed','rolled_back')),
    size_bytes INTEGER NOT NULL, mtime TEXT NOT NULL,
    fingerprint_quick TEXT NOT NULL, full_sha256 TEXT, full_sha256_computed_at TEXT,
    device_id INTEGER, inode INTEGER, device_inode_reliable INTEGER,
    parent_id TEXT REFERENCES inventory_items(id),
    relation_to_parent TEXT CHECK (relation_to_parent IS NULL OR relation_to_parent IN (
        'season_of_show','episode_of_season','track_of_album','album_of_artist',
        'extra_of','version_of','edition_of')),
    season_number INTEGER, episode_number INTEGER, episode_number_end INTEGER,  -- derivados
    discovered_at TEXT NOT NULL, updated_at TEXT NOT NULL, last_seen_at TEXT NOT NULL,
    CHECK ((parent_id IS NULL) = (relation_to_parent IS NULL)),   -- mismo XOR que el validador Pydantic
    UNIQUE (library_id, current_path)
);
CREATE INDEX idx_inventory_items_library ON inventory_items(library_id);
CREATE INDEX idx_inventory_items_state ON inventory_items(item_state);
CREATE INDEX idx_inventory_items_parent ON inventory_items(parent_id);
CREATE INDEX idx_inventory_items_library_content_type ON inventory_items(library_id, content_type);

CREATE TABLE libraries (library_id TEXT PRIMARY KEY, authorized_root TEXT NOT NULL, created_at TEXT NOT NULL);
