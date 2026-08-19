#!/bin/sh
set -e

python -m xy_neo4j.import_neo4j_data
exec "$@"
