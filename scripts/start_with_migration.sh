#!/bin/bash

run_migration() {
    local retries=5
    local count=0
    local delay=300 # 5 minutes in seconds

    while [ $count -lt $retries ]; do
        echo "$(date): Running alembic migration. Attempt $((count+1)) of $retries."
        alembic upgrade head
        if [ $? -eq 0 ]; then
            echo "$(date): Migrations applied successfully."
            return 0
        else
            echo "$(date): Migration failed. Attempt $((count+1)) of $retries. Retrying in $delay seconds."
            count=$((count+1))
            sleep $delay
        fi
    done

    echo "$(date): Migration failed after $retries attempts. Exiting."
    return 1
}

./scripts/start.sh &

run_migration

wait
