-- Private camera credential foundation. No runtime/API activation or key material.
CREATE TABLE camera.credential_encryption_budgets (
    key_id text COLLATE "C" PRIMARY KEY CHECK (key_id ~ '^enc-[0-9a-f]{16}$'),
    uses bigint NOT NULL DEFAULT 0 CHECK (uses BETWEEN 0 AND 4294967295),
    enabled boolean NOT NULL DEFAULT true,
    created_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE camera.credentials (
    credential_id text COLLATE "C" PRIMARY KEY CHECK (credential_id ~ '^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$'),
    scope_id text COLLATE "C" NOT NULL CHECK (scope_id ~ '^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$'),
    device_id text COLLATE "C" NOT NULL REFERENCES camera.devices(device_id) ON UPDATE RESTRICT ON DELETE RESTRICT,
    head_version bigint NOT NULL CHECK (head_version > 0),
    created_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP CHECK (updated_at >= created_at)
);

CREATE TABLE camera.credential_versions (
    credential_id text COLLATE "C" NOT NULL REFERENCES camera.credentials(credential_id) ON UPDATE RESTRICT ON DELETE RESTRICT,
    version bigint NOT NULL CHECK (version > 0),
    protocol text NOT NULL CHECK (protocol = 'RTSP'),
    host text NOT NULL CHECK (octet_length(host) BETWEEN 1 AND 253),
    port integer NOT NULL CHECK (port BETWEEN 1 AND 65535),
    target_policy_sha256 text NOT NULL CHECK (target_policy_sha256 ~ '^[0-9a-f]{64}$'),
    encryption_format integer NOT NULL CHECK (encryption_format = 1),
    encryption_algorithm text NOT NULL CHECK (encryption_algorithm = 'AES-256-GCM-RANDOM-NONCE'),
    encryption_key_id text COLLATE "C" NOT NULL REFERENCES camera.credential_encryption_budgets(key_id) ON UPDATE RESTRICT ON DELETE RESTRICT,
    encryption_use bigint NOT NULL CHECK (encryption_use BETWEEN 1 AND 4294967295),
    ciphertext bytea NOT NULL CHECK (octet_length(ciphertext) BETWEEN 28 AND 32796),
    created_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
    revoked_at timestamptz CHECK (revoked_at IS NULL OR revoked_at >= created_at),
    PRIMARY KEY (credential_id, version),
    UNIQUE (encryption_key_id, encryption_use)
);
ALTER TABLE camera.credentials ADD CONSTRAINT credential_head_exists
FOREIGN KEY (credential_id, head_version) REFERENCES camera.credential_versions(credential_id, version)
ON UPDATE NO ACTION ON DELETE NO ACTION DEFERRABLE INITIALLY DEFERRED;

-- Typed receipts cannot archive arbitrary JSON, addresses or plaintext secrets.
CREATE TABLE camera.credential_requests (
    scope_id text COLLATE "C" NOT NULL CHECK (scope_id ~ '^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$'),
    principal text COLLATE "C" NOT NULL CHECK (principal ~ '^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$'),
    method text NOT NULL CHECK (method IN ('POST','DELETE')),
    path text NOT NULL CHECK (path ~ '^/api/v1/credentials/[A-Za-z0-9][A-Za-z0-9._-]{0,63}/versions(/[1-9][0-9]{0,18})?$'),
    key_hash text NOT NULL CHECK (key_hash ~ '^[0-9a-f]{64}$'),
    fingerprint_format integer NOT NULL CHECK (fingerprint_format = 1),
    fingerprint_algorithm text NOT NULL CHECK (fingerprint_algorithm = 'HMAC-SHA256'),
    fingerprint_key_id text NOT NULL CHECK (fingerprint_key_id ~ '^idem-[0-9a-f]{16}$'),
    fingerprint_digest text NOT NULL CHECK (fingerprint_digest ~ '^[0-9a-f]{64}$'),
    credential_id text COLLATE "C" NOT NULL CHECK (credential_id ~ '^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$'),
    device_id text COLLATE "C" NOT NULL CHECK (device_id ~ '^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$'),
    version bigint NOT NULL CHECK (version > 0),
    version_created_at timestamptz NOT NULL,
    revoked_at timestamptz CHECK (revoked_at IS NULL OR revoked_at >= version_created_at),
    PRIMARY KEY (scope_id, principal, method, path, key_hash)
);

-- Only this fixed operation is exposed to a separate budget connection/account.
-- Calling it in an outer data transaction is forbidden by the Go boundary.
CREATE FUNCTION camera.reserve_credential_encryption_use(selected_key text) RETURNS bigint
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, camera, pg_temp AS $$
DECLARE reserved bigint;
BEGIN
    UPDATE camera.credential_encryption_budgets SET uses=uses+1
    WHERE key_id=selected_key AND enabled AND uses<4294967295 RETURNING uses INTO reserved;
    IF FOUND THEN RETURN reserved; END IF;
    IF EXISTS (SELECT 1 FROM camera.credential_encryption_budgets WHERE key_id=selected_key AND enabled)
    THEN RETURN 0; END IF;
    RETURN -1;
END;
$$;
REVOKE ALL ON FUNCTION camera.reserve_credential_encryption_use(text) FROM PUBLIC;

CREATE FUNCTION camera.credential_encryption_key_ready(selected_key text) RETURNS boolean
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = pg_catalog, camera, pg_temp AS $$
    SELECT EXISTS (SELECT 1 FROM camera.credential_encryption_budgets
                   WHERE key_id=selected_key AND enabled AND uses<4294967295);
$$;
REVOKE ALL ON FUNCTION camera.credential_encryption_key_ready(text) FROM PUBLIC;

-- The registry account can ask this predicate without reading ciphertext/policy.
CREATE FUNCTION camera.device_has_active_credentials(selected_device text) RETURNS boolean
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = pg_catalog, camera, pg_temp AS $$
    SELECT EXISTS (SELECT 1 FROM camera.credentials c JOIN camera.credential_versions v USING (credential_id)
                   WHERE c.device_id=selected_device AND v.revoked_at IS NULL);
$$;
REVOKE ALL ON FUNCTION camera.device_has_active_credentials(text) FROM PUBLIC;

-- Preserve parent admission even if an older caller tries logical deletion.
CREATE FUNCTION camera.protect_credential_parent() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, camera, pg_temp AS $$
BEGIN
    IF OLD.deleted_at IS NULL AND NEW.deleted_at IS NOT NULL THEN
        PERFORM pg_catalog.pg_advisory_xact_lock(1447908164,pg_catalog.hashtext(NEW.device_id));
        IF camera.device_has_active_credentials(NEW.device_id) THEN
            RAISE EXCEPTION 'DEVICE_IN_USE' USING ERRCODE='23514';
        END IF;
    END IF;
    RETURN NEW;
END;
$$;
REVOKE ALL ON FUNCTION camera.protect_credential_parent() FROM PUBLIC;
CREATE TRIGGER protect_credential_parent BEFORE UPDATE OF deleted_at ON camera.devices
FOR EACH ROW EXECUTE FUNCTION camera.protect_credential_parent();

CREATE FUNCTION camera.protect_credential_version_insert() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, camera, pg_temp AS $$
DECLARE parent text; current_head bigint; has_versions boolean;
BEGIN
    SELECT device_id INTO parent FROM camera.credentials WHERE credential_id=NEW.credential_id;
    PERFORM pg_catalog.pg_advisory_xact_lock(1447908164,pg_catalog.hashtext(parent));
    IF NOT EXISTS (SELECT 1 FROM camera.devices WHERE device_id=parent AND deleted_at IS NULL) THEN
        RAISE EXCEPTION 'DEVICE_UNAVAILABLE' USING ERRCODE='23514';
    END IF;
    SELECT head_version INTO current_head FROM camera.credentials WHERE credential_id=NEW.credential_id FOR UPDATE;
    SELECT EXISTS (SELECT 1 FROM camera.credential_versions WHERE credential_id=NEW.credential_id) INTO has_versions;
    IF (NOT has_versions AND NEW.version<>1) OR (has_versions AND NEW.version<>current_head+1) THEN
        RAISE EXCEPTION 'CREDENTIAL_VERSION_INVALID' USING ERRCODE='23514';
    END IF;
    IF NOT EXISTS (SELECT 1 FROM camera.credential_encryption_budgets
                   WHERE key_id=NEW.encryption_key_id AND enabled AND uses>=NEW.encryption_use) THEN
        RAISE EXCEPTION 'CREDENTIAL_RESERVATION_INVALID' USING ERRCODE='23514';
    END IF;
    RETURN NEW;
END;
$$;
REVOKE ALL ON FUNCTION camera.protect_credential_version_insert() FROM PUBLIC;
CREATE TRIGGER protect_credential_version_insert BEFORE INSERT ON camera.credential_versions
FOR EACH ROW EXECUTE FUNCTION camera.protect_credential_version_insert();

CREATE FUNCTION camera.protect_credential_version_update() RETURNS trigger
LANGUAGE plpgsql SET search_path = pg_catalog, camera, pg_temp AS $$
BEGIN
    IF ROW(NEW.credential_id,NEW.version,NEW.protocol,NEW.host,NEW.port,NEW.target_policy_sha256,
           NEW.encryption_format,NEW.encryption_algorithm,NEW.encryption_key_id,NEW.encryption_use,NEW.ciphertext,NEW.created_at)
       IS DISTINCT FROM ROW(OLD.credential_id,OLD.version,OLD.protocol,OLD.host,OLD.port,OLD.target_policy_sha256,
           OLD.encryption_format,OLD.encryption_algorithm,OLD.encryption_key_id,OLD.encryption_use,OLD.ciphertext,OLD.created_at)
       OR OLD.revoked_at IS NOT NULL OR NEW.revoked_at IS NULL THEN
        RAISE EXCEPTION 'CREDENTIAL_VERSION_IMMUTABLE' USING ERRCODE='23514';
    END IF;
    RETURN NEW;
END;
$$;
REVOKE ALL ON FUNCTION camera.protect_credential_version_update() FROM PUBLIC;
CREATE TRIGGER protect_credential_version_update BEFORE UPDATE ON camera.credential_versions
FOR EACH ROW EXECUTE FUNCTION camera.protect_credential_version_update();

CREATE FUNCTION camera.protect_credential_head() RETURNS trigger
LANGUAGE plpgsql SET search_path = pg_catalog, camera, pg_temp AS $$
BEGIN
    IF ROW(NEW.credential_id,NEW.scope_id,NEW.device_id,NEW.created_at)
       IS DISTINCT FROM ROW(OLD.credential_id,OLD.scope_id,OLD.device_id,OLD.created_at)
       OR NEW.head_version<>OLD.head_version+1 OR NEW.updated_at<OLD.updated_at THEN
        RAISE EXCEPTION 'CREDENTIAL_HEAD_IMMUTABLE' USING ERRCODE='23514';
    END IF;
    RETURN NEW;
END;
$$;
REVOKE ALL ON FUNCTION camera.protect_credential_head() FROM PUBLIC;
CREATE TRIGGER protect_credential_head BEFORE UPDATE ON camera.credentials
FOR EACH ROW EXECUTE FUNCTION camera.protect_credential_head();

CREATE FUNCTION camera.check_credential_head() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, camera, pg_temp AS $$
BEGIN
    IF EXISTS (SELECT 1 FROM camera.credentials c WHERE c.credential_id=NEW.credential_id
               AND c.head_version IS DISTINCT FROM (SELECT max(v.version) FROM camera.credential_versions v WHERE v.credential_id=c.credential_id)) THEN
        RAISE EXCEPTION 'CREDENTIAL_HEAD_INVALID' USING ERRCODE='23514';
    END IF;
    RETURN NULL;
END;
$$;
REVOKE ALL ON FUNCTION camera.check_credential_head() FROM PUBLIC;
CREATE CONSTRAINT TRIGGER check_credential_root_head AFTER INSERT OR UPDATE ON camera.credentials
DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION camera.check_credential_head();
CREATE CONSTRAINT TRIGGER check_credential_version_head AFTER INSERT ON camera.credential_versions
DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION camera.check_credential_head();

CREATE FUNCTION camera.protect_credential_budget() RETURNS trigger
LANGUAGE plpgsql SET search_path = pg_catalog, camera, pg_temp AS $$
BEGIN
    IF NEW.key_id<>OLD.key_id OR NEW.created_at<>OLD.created_at OR NEW.uses<OLD.uses OR (NOT OLD.enabled AND NEW.enabled) THEN
        RAISE EXCEPTION 'CREDENTIAL_BUDGET_RESET_FORBIDDEN' USING ERRCODE='23514';
    END IF;
    RETURN NEW;
END;
$$;
REVOKE ALL ON FUNCTION camera.protect_credential_budget() FROM PUBLIC;
CREATE TRIGGER protect_credential_budget BEFORE UPDATE ON camera.credential_encryption_budgets
FOR EACH ROW EXECUTE FUNCTION camera.protect_credential_budget();
