-- Camera-owned registration metadata only. No media, credentials or sessions.
CREATE TABLE camera.devices (
    device_id text COLLATE "C" PRIMARY KEY CHECK (device_id ~ '^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$'),
    display_name text NOT NULL CHECK (char_length(display_name) BETWEEN 1 AND 128 AND display_name ~ '[^[:space:]]'),
    device_kind text NOT NULL CHECK (device_kind IN ('CCTV','SMART_GLASSES','TEST')),
    version bigint NOT NULL DEFAULT 1 CHECK (version > 0),
    created_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
    deleted_at timestamptz,
    CHECK (updated_at >= created_at),
    CHECK (deleted_at IS NULL OR deleted_at >= created_at)
);

CREATE TABLE camera.video_sources (
    source_id text COLLATE "C" PRIMARY KEY CHECK (source_id ~ '^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$'),
    device_id text COLLATE "C" NOT NULL REFERENCES camera.devices(device_id) ON UPDATE RESTRICT ON DELETE RESTRICT,
    channel_key text COLLATE "C" NOT NULL CHECK (channel_key ~ '^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$'),
    display_name text NOT NULL CHECK (char_length(display_name) BETWEEN 1 AND 128 AND display_name ~ '[^[:space:]]'),
    transport text NOT NULL,
    input_mode text NOT NULL,
    primary_profile_id text COLLATE "C" NOT NULL CHECK (primary_profile_id ~ '^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$'),
    motion_mode text NOT NULL CHECK (motion_mode IN ('FIXED','MOVING','UNKNOWN')),
    version bigint NOT NULL DEFAULT 1 CHECK (version > 0),
    created_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
    deleted_at timestamptz,
    CONSTRAINT source_channel_unique UNIQUE (device_id, channel_key),
    CONSTRAINT source_transport_pair CHECK ((transport='RTSP' AND input_mode='PULL') OR (transport='WEBRTC' AND input_mode='PUSH')),
    CHECK (updated_at >= created_at),
    CHECK (deleted_at IS NULL OR deleted_at >= created_at)
);

CREATE TABLE camera.stream_profiles (
    source_id text COLLATE "C" NOT NULL REFERENCES camera.video_sources(source_id) ON UPDATE RESTRICT ON DELETE RESTRICT,
    profile_id text COLLATE "C" NOT NULL CHECK (profile_id ~ '^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$'),
    position smallint NOT NULL CHECK (position BETWEEN 1 AND 8),
    codec text NOT NULL CHECK (codec IN ('AUTO','H264','H265','VP8','VP9','AV1')),
    width integer NOT NULL CHECK (width BETWEEN 1 AND 16384),
    height integer NOT NULL CHECK (height BETWEEN 1 AND 16384),
    fps double precision NOT NULL CHECK (fps > 0 AND fps <= 240),
    PRIMARY KEY (source_id, profile_id),
    UNIQUE (source_id, position)
);

-- The primary profile is initially the first declared profile. A deferred FK
-- guarantees at least one profile at commit, without cross-row CHECK triggers.
ALTER TABLE camera.video_sources ADD CONSTRAINT source_primary_profile
FOREIGN KEY (source_id, primary_profile_id)
REFERENCES camera.stream_profiles(source_id, profile_id)
ON UPDATE NO ACTION ON DELETE NO ACTION DEFERRABLE INITIALLY DEFERRED;

-- Services retain tombstones rather than physically deleting device/source rows.
-- Soft-deleted parents, immutable fields and version increments are service rules
-- to implement in the following CRUD units; the SQL owner can bypass those rules.
