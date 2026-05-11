# Runtime Smoke Review

Verify the generated application by running it through real local services, not only by reading code.

Required checks:

- Confirm backend startup from a clean project-local environment.
- Confirm required runtime dependencies are declared in the project dependency files.
- Confirm health endpoints and core API operations return successful responses.
- Confirm the frontend compiles and serves a page through its dev or production server.
- Confirm at least one browser-level create/read interaction reaches the backend and persists data when the feature requires persistence.
- Create focused coder fix tasks for runtime dependency gaps, build failures, incorrect API base URLs, route mismatches, or UI paths that cannot complete the main workflow.

Prefer deterministic HWE tasks for evidence:

- Use `kind=command` for dependency install, build, server startup scripts, and backend tests.
- Use `kind=http_check` for backend health, API smoke, and frontend page checks.
- Record the exact commands, URLs, and observed responses in the review result.

Do not approve final acceptance from static inspection alone when the requested deliverable is a runnable application.