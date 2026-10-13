-- Successful logical DELETE receipts are independent from POST/PATCH history.
-- No device FK: history must survive any future separately controlled retention.
CREATE TABLE camera.device_delete_requests (
    principal text NOT NULL,
    method text NOT NULL CHECK (method = 'DELETE'),
    path text NOT NULL CHECK (path ~ '^/api/v1/devices/[A-Za-z0-9][A-Za-z0-9._-]{0,63}$'),
    key_hash text NOT NULL CHECK (key_hash ~ '^[0-9a-f]{64}$'),
    request_hash text NOT NULL CHECK (request_hash ~ '^[0-9a-f]{64}$'),
    response_body jsonb NOT NULL CHECK (jsonb_typeof(response_body) = 'object'),
    created_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (principal, method, path, key_hash)
);
