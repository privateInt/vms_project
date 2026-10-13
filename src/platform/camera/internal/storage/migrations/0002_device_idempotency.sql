-- Successful create responses are retained without automatic expiry.
-- Store only a digest of the client key; never the bearer token.
CREATE TABLE camera.device_create_requests (
    principal text NOT NULL,
    method text NOT NULL CHECK (method = 'POST'),
    path text NOT NULL CHECK (path = '/api/v1/devices'),
    key_hash text NOT NULL CHECK (key_hash ~ '^[0-9a-f]{64}$'),
    request_hash text NOT NULL CHECK (request_hash ~ '^[0-9a-f]{64}$'),
    response_body jsonb NOT NULL CHECK (jsonb_typeof(response_body) = 'object'),
    created_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (principal, method, path, key_hash)
);
