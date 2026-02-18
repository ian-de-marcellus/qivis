"""Database schema DDL. All tables use CREATE IF NOT EXISTS for idempotency."""

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS events (
    sequence_num INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id TEXT UNIQUE NOT NULL,
    tree_id TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    device_id TEXT NOT NULL DEFAULT 'local',
    user_id TEXT,
    event_type TEXT NOT NULL,
    payload TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_events_tree_id ON events(tree_id);
CREATE INDEX IF NOT EXISTS idx_events_event_type ON events(event_type);
CREATE INDEX IF NOT EXISTS idx_events_timestamp ON events(timestamp);

CREATE TABLE IF NOT EXISTS trees (
    tree_id TEXT PRIMARY KEY,
    title TEXT,
    metadata TEXT NOT NULL DEFAULT '{}',
    default_model TEXT,
    default_provider TEXT,
    default_system_prompt TEXT,
    default_sampling_params TEXT,
    conversation_mode TEXT NOT NULL DEFAULT 'single',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    archived INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS nodes (
    node_id TEXT PRIMARY KEY,
    tree_id TEXT NOT NULL,
    parent_id TEXT,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    model TEXT,
    provider TEXT,
    system_prompt TEXT,
    sampling_params TEXT,
    mode TEXT DEFAULT 'chat',
    usage TEXT,
    latency_ms INTEGER,
    finish_reason TEXT,
    logprobs TEXT,
    context_usage TEXT,
    participant_id TEXT,
    participant_name TEXT,
    thinking_content TEXT,
    edited_content TEXT,
    include_thinking_in_context INTEGER NOT NULL DEFAULT 0,
    include_timestamps INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    archived INTEGER NOT NULL DEFAULT 0,
    FOREIGN KEY (tree_id) REFERENCES trees(tree_id)
);

CREATE INDEX IF NOT EXISTS idx_nodes_tree_id ON nodes(tree_id);
CREATE INDEX IF NOT EXISTS idx_nodes_parent_id ON nodes(parent_id);

CREATE TABLE IF NOT EXISTS annotations (
    annotation_id TEXT PRIMARY KEY,
    tree_id TEXT NOT NULL,
    node_id TEXT NOT NULL,
    tag TEXT NOT NULL,
    value TEXT,
    notes TEXT,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_annotations_node_id ON annotations(node_id);
CREATE INDEX IF NOT EXISTS idx_annotations_tree_id ON annotations(tree_id);
CREATE INDEX IF NOT EXISTS idx_annotations_tag ON annotations(tag);

CREATE TABLE IF NOT EXISTS bookmarks (
    bookmark_id TEXT PRIMARY KEY,
    tree_id TEXT NOT NULL,
    node_id TEXT NOT NULL,
    label TEXT NOT NULL,
    notes TEXT,
    summary TEXT,
    summary_model TEXT,
    summarized_node_ids TEXT,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_bookmarks_tree_id ON bookmarks(tree_id);
CREATE INDEX IF NOT EXISTS idx_bookmarks_node_id ON bookmarks(node_id);

CREATE TABLE IF NOT EXISTS node_exclusions (
    tree_id TEXT NOT NULL,
    node_id TEXT NOT NULL,
    scope_node_id TEXT NOT NULL,
    reason TEXT,
    created_at TEXT NOT NULL,
    PRIMARY KEY (tree_id, node_id, scope_node_id)
);

CREATE TABLE IF NOT EXISTS digression_groups (
    group_id TEXT PRIMARY KEY,
    tree_id TEXT NOT NULL,
    label TEXT NOT NULL,
    included INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_digression_groups_tree_id ON digression_groups(tree_id);

CREATE TABLE IF NOT EXISTS digression_group_nodes (
    group_id TEXT NOT NULL,
    node_id TEXT NOT NULL,
    sort_order INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (group_id, node_id)
);

CREATE TABLE IF NOT EXISTS node_anchors (
    tree_id TEXT NOT NULL,
    node_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (tree_id, node_id)
);

CREATE INDEX IF NOT EXISTS idx_node_anchors_tree_id ON node_anchors(tree_id);
"""

# Migrations for existing databases that already have the nodes table.
_MIGRATIONS = [
    "ALTER TABLE nodes ADD COLUMN thinking_content TEXT",
    "ALTER TABLE nodes ADD COLUMN edited_content TEXT",
    "ALTER TABLE nodes ADD COLUMN include_thinking_in_context INTEGER NOT NULL DEFAULT 0",
    "ALTER TABLE nodes ADD COLUMN include_timestamps INTEGER NOT NULL DEFAULT 0",
]


async def run_migrations(db: object) -> None:
    """Run schema migrations safely. Ignores errors for already-applied migrations."""
    for sql in _MIGRATIONS:
        try:
            await db.execute(sql)
        except Exception:
            pass  # Column already exists or other expected error
