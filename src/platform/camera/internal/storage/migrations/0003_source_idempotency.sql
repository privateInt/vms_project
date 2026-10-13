-- Source creation and its original successful response commit together.
-- The method/path namespace is independent of device creation.
CREATE TABLE camera.source_create_requests (
    principal text NOT NULL,
    method text NOT NULL CHECK (method = 'POST'),
    path text NOT NULL CHECK (path = '/api/v1/sources'),
    key_hash text NOT NULL CHECK (key_hash ~ '^[0-9a-f]{64}$'),
    request_hash text NOT NULL CHECK (request_hash ~ '^[0-9a-f]{64}$'),
    response_body jsonb NOT NULL CHECK (jsonb_typeof(response_body) = 'object'),
    created_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (principal, method, path, key_hash)
);
