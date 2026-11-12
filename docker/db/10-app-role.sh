#!/bin/sh
# Least-privilege database role for the application.
#
# The official postgres image makes POSTGRES_USER a SUPERUSER. The app should not run as
# that: a superuser can read server files, run programs (COPY ... PROGRAM) and change any
# setting, so one SQL-injection bug would become a full server compromise. This script
# creates APP_DB_USER (no SUPERUSER / CREATEROLE / CREATEDB / REPLICATION / BYPASSRLS) and
# makes it the owner of the application database and of its tables, sequences and types.
# POSTGRES_USER stays the administrator account, used only for maintenance.
#
# Runs automatically when the database volume is first created (docker-entrypoint-initdb.d).
# For an existing installation run it once by hand:  make db-least-privilege
# It is idempotent and changes only role settings and object ownership, never data.
set -eu

APP_USER="${APP_DB_USER:-}"
if [ -z "$APP_USER" ] || [ -z "${APP_DB_PASSWORD:-}" ]; then
  echo "10-app-role: APP_DB_USER/APP_DB_PASSWORD not set; skipping (the app will use the admin role)." >&2
  exit 0
fi
case "$APP_USER" in
  *[!a-z0-9_]* | [!a-z_]* ) echo "10-app-role: APP_DB_USER must be lower-case letters, digits or _" >&2; exit 1 ;;
esac
if [ "$APP_USER" = "${POSTGRES_USER:-postgres}" ]; then
  echo "10-app-role: APP_DB_USER must differ from POSTGRES_USER" >&2; exit 1
fi
DB="${POSTGRES_DB:-${POSTGRES_USER:-postgres}}"

# The password goes in as a psql variable (:'pw'), so it is quoted safely and never appears
# in the process list or in logs.
psql -v ON_ERROR_STOP=1 -v pw="$APP_DB_PASSWORD" --username "${POSTGRES_USER:-postgres}" --dbname "$DB" <<SQL
SELECT 'CREATE ROLE $APP_USER LOGIN'
 WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '$APP_USER') \gexec
ALTER ROLE $APP_USER WITH LOGIN NOSUPERUSER NOCREATEROLE NOCREATEDB NOREPLICATION NOBYPASSRLS
  CONNECTION LIMIT 60 PASSWORD :'pw';
ALTER DATABASE "$DB" OWNER TO $APP_USER;

-- Hand over the application's objects (tables, views, sequences not tied to a column,
-- enum/composite types, functions) in schema public. Objects that belong to an extension
-- are left alone.
DO \$\$
DECLARE r record;
BEGIN
  FOR r IN
    SELECT c.oid::regclass AS obj,
           CASE c.relkind WHEN 'S' THEN 'SEQUENCE' WHEN 'v' THEN 'VIEW'
                          WHEN 'm' THEN 'MATERIALIZED VIEW' ELSE 'TABLE' END AS kind
      FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
     WHERE n.nspname = 'public' AND c.relkind IN ('r', 'p', 'v', 'm', 'S')
       AND pg_get_userbyid(c.relowner) <> '$APP_USER'
       AND NOT EXISTS (SELECT 1 FROM pg_depend d WHERE d.classid = 'pg_class'::regclass
                         AND d.objid = c.oid AND d.deptype IN ('e', 'a', 'i'))
  LOOP
    EXECUTE format('ALTER %s %s OWNER TO %I', r.kind, r.obj, '$APP_USER');
  END LOOP;
  FOR r IN
    SELECT t.oid::regtype AS obj FROM pg_type t JOIN pg_namespace n ON n.oid = t.typnamespace
     WHERE n.nspname = 'public' AND t.typtype IN ('e', 'd')
       AND pg_get_userbyid(t.typowner) <> '$APP_USER'
       AND NOT EXISTS (SELECT 1 FROM pg_depend d WHERE d.classid = 'pg_type'::regclass
                         AND d.objid = t.oid AND d.deptype = 'e')
  LOOP
    EXECUTE format('ALTER TYPE %s OWNER TO %I', r.obj, '$APP_USER');
  END LOOP;
  FOR r IN
    SELECT p.oid::regprocedure AS obj FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace
     WHERE n.nspname = 'public' AND pg_get_userbyid(p.proowner) <> '$APP_USER'
       AND NOT EXISTS (SELECT 1 FROM pg_depend d WHERE d.classid = 'pg_proc'::regclass
                         AND d.objid = p.oid AND d.deptype = 'e')
  LOOP
    EXECUTE format('ALTER ROUTINE %s OWNER TO %I', r.obj, '$APP_USER');
  END LOOP;
END
\$\$;
SQL
echo "10-app-role: '$APP_USER' owns database '$DB' (no superuser rights)."
