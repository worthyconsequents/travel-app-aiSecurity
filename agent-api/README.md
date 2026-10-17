# agent-api

Entry point: `services/api.py`. Shared schemas and database transaction code live in `services/` to avoid divergent authorization or approval implementations. Compose runs each service in a separate process/container.
