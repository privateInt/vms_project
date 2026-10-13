#!/bin/sh
# The official PostgreSQL entrypoint runs this only on an empty data directory.
(
set -eu
test "$POSTGRES_DB" = vms_camera
test "$POSTGRES_USER" = camera_admin
migration_password=$(cat /run/secrets/camera_migration_password)
runtime_password=$(cat /run/secrets/camera_runtime_password)
psql --set=ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" \
  --set=migration_password="$migration_password" --set=runtime_password="$runtime_password" <<'SQL'
CREATE ROLE camera_migrator LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION PASSWORD :'migration_password';
CREATE ROLE camera_runtime LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION PASSWORD :'runtime_password';
REVOKE ALL ON DATABASE vms_camera FROM PUBLIC;
GRANT CONNECT, CREATE ON DATABASE vms_camera TO camera_migrator;
GRANT CONNECT ON DATABASE vms_camera TO camera_runtime;
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
CREATE SCHEMA camera AUTHORIZATION camera_migrator;
SQL
unset migration_password runtime_password
)
