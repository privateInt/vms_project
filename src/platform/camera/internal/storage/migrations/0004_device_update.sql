-- Successful PATCH snapshots are separate from the immutable POST journal.
-- No foreign key: request history survives future device tombstones.
CREATE TABLE camera.device_update_requests (
    principal text NOT NULL,
    method text NOT NULL CHECK (method = 'PATCH'),
    path text NOT NULL CHECK (path ~ '^/api/v1/devices/[A-Za-z0-9][A-Za-z0-9._-]{0,63}$'),
    key_hash text NOT NULL CHECK (key_hash ~ '^[0-9a-f]{64}$'),
    request_hash text NOT NULL CHECK (request_hash ~ '^[0-9a-f]{64}$'),
    response_body jsonb NOT NULL CHECK (jsonb_typeof(response_body) = 'object'),
    created_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (principal, method, path, key_hash)
);
