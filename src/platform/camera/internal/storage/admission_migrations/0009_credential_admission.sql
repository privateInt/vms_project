-- Explicit admission target only; legacy Migrate remains at schema 8.
-- No automatic identity/bootstrap: maintenance must persist PREPARED first.
CREATE TABLE camera.credential_admission_database (
    singleton smallint PRIMARY KEY CHECK (singleton = 1),
    deployment_id text COLLATE "C" NOT NULL CHECK (deployment_id ~ '^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$'),
    generation bigint NOT NULL CHECK (generation > 0),
    operation_id text COLLATE "C" NOT NULL CHECK (operation_id ~ '^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$'),
    database_id text COLLATE "C" NOT NULL CHECK (database_id ~ '^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$'),
    database_name text COLLATE "C" NOT NULL CHECK (database_name ~ '^[A-Za-z_][A-Za-z0-9_]{0,62}$'),
    schema_version integer NOT NULL CHECK (schema_version = 9),
    migration_set_sha256 text COLLATE "C" NOT NULL CHECK (migration_set_sha256 ~ '^[0-9a-f]{64}$'),
    written_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP
);
REVOKE ALL ON camera.credential_admission_database FROM PUBLIC;
