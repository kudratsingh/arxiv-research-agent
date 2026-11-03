CREATE TABLE IF NOT EXISTS workspace_material_provenance (
 material_id TEXT PRIMARY KEY REFERENCES workspace_material(material_id),
 data JSONB NOT NULL
);
