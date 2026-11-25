# FlowForge — Agent Instructions

## 1. Project Overview

FlowForge is a backend-only distributed workflow execution engine.

It allows users to define workflows, trigger asynchronous executions, monitor execution progress, handle failures, retry steps, and inspect execution logs.

The goal is to build a functional, well-structured backend project demonstrating practical backend engineering, asynchronous processing, distributed task execution, persistence, and failure handling.

Build incrementally. Prioritize working functionality, correctness, clarity, and testing over unnecessary complexity.

## 2. Core Technology Stack

- Python 3.12+
- FastAPI
- PostgreSQL
- Redis
- SQLAlchemy 2.x (async)
- Alembic
- Pydantic
- asyncio
- Pytest

## 3. Environment Constraints

- This project runs locally on Windows.
- Python virtual environment: `.venv`.
- PostgreSQL is installed locally.
- Redis is installed locally.
- Docker and Docker Compose must NOT be used.
- Do not assume Linux-specific commands or environment configurations.
- Provide Windows-compatible instructions when command-line instructions are necessary.
- Never modify system installations or global configurations without explicit approval.

## 4. Project Scope

FlowForge is strictly backend-only.

Implement:

- Workflow definitions and validation.
- Workflow persistence.
- Workflow execution triggering.
- Asynchronous workflow execution.
- Redis-backed queueing.
- Worker processing.
- Execution and step status tracking.
- Retry handling.
- Exponential backoff.
- Step timeouts.
- Execution logging.
- Idempotency.
- Failure handling.
- Execution cancellation where practical.
- Automated tests.

Do NOT build:

- Frontend or web dashboard.
- Authentication unless explicitly requested.
- Arbitrary shell execution.
- Arbitrary Python execution.
- Arbitrary code execution through workflow definitions.
- Kubernetes deployment.
- Docker infrastructure.
- Unnecessary infrastructure or external services.
- Features outside the agreed scope without approval.

## 5. Architecture Guidelines

Use a modular architecture with clear separation of responsibilities.

Expected logical components:

- API layer: HTTP endpoints and request/response handling.
- Application/service layer: orchestration and business logic.
- Workflow registry: workflow creation, validation and retrieval.
- Execution engine: workflow and step execution.
- Queue layer: Redis-based task dispatch.
- Worker: asynchronous execution of queued tasks.
- Persistence layer: database access and repositories.
- Models: database models and domain representations.
- Schemas: API and validation schemas.
- Logging: execution-specific event logging.
- Configuration: application settings.

Avoid unnecessary abstractions. Introduce interfaces or abstractions only when they provide a concrete benefit.

Do not couple the execution engine directly to HTTP endpoints.

## 6. Workflow Execution

- Execute steps in defined order for the initial version.
- Keep step execution isolated from API request handling.
- Persist execution status and step status.
- Record meaningful execution events.
- Handle failures explicitly.
- Implement retries only for eligible failures.
- Use configurable retry limits.
- Implement exponential backoff.
- Support step-level timeout configuration.
- Ensure execution state transitions are valid.
- Avoid duplicate execution when idempotency requirements apply.
- Never silently swallow exceptions.

Initial supported step types should be safe, predefined operations such as:

- HTTP request steps.
- Delay steps.
- Internal demonstration steps.

Do not implement arbitrary shell or code execution.

## 7. Execution State

Workflow execution states may include:

- QUEUED
- RUNNING
- RETRYING
- COMPLETED
- FAILED
- CANCELLED

Step states may include:

- PENDING
- RUNNING
- RETRYING
- COMPLETED
- FAILED
- SKIPPED
- CANCELLED

Validate state transitions and avoid inconsistent persisted state.

## 8. Database Guidelines

- Use PostgreSQL.
- Use SQLAlchemy 2.x async APIs.
- Use Alembic for schema migrations.
- Do not create production schema changes through ad-hoc table creation when migrations are expected.
- Keep database operations explicit.
- Avoid inefficient query patterns.
- Use transactions where required.
- Store structured workflow definitions and appropriate metadata using PostgreSQL JSONB when justified.
- Use UUIDs where appropriate.
- Add indexes based on actual query patterns.
- Avoid premature indexing.

Expected core entities:

- Workflows
- Executions
- ExecutionSteps
- ExecutionLogs

Do not add unnecessary tables without explaining the reason.

## 9. Redis Guidelines

Redis is used for queueing and worker coordination.

- Keep queue operations separate from workflow business logic.
- Handle Redis connection failures appropriately.
- Do not treat Redis as the primary persistent source of execution history.
- PostgreSQL remains the source of truth for execution state and historical records.
- Avoid introducing Redis features that are unnecessary for the MVP.
- Make queue operations testable.

## 10. Async Programming

- Prefer async APIs where supported.
- Use async database access.
- Use async Redis operations.
- Avoid blocking the event loop.
- Do not use blocking sleep inside async execution.
- Use asyncio-compatible operations.
- Handle task cancellation correctly.
- Avoid unmanaged background tasks where reliability or lifecycle management is required.

## 11. API Guidelines

Use REST conventions.

Base path:

`/api/v1`

Expected endpoints:

- `POST /workflows`
- `GET /workflows`
- `GET /workflows/{workflow_id}`
- `POST /workflows/{workflow_id}/execute`
- `GET /executions/{execution_id}`
- `GET /executions/{execution_id}/steps`
- `GET /executions/{execution_id}/logs`
- `POST /executions/{execution_id}/cancel`
- `POST /executions/{execution_id}/retry`

These are planned endpoints. Implement incrementally.

- Validate incoming data using Pydantic.
- Use appropriate HTTP status codes.
- Keep response schemas consistent.
- Do not expose internal exception details or secrets.
- Do not place business logic inside route handlers.
- Avoid unnecessary endpoints.

## 12. Error Handling

- Handle expected failures explicitly.
- Use structured and meaningful exceptions where appropriate.
- Avoid broad exception handling that hides errors.
- Preserve useful debugging information in internal logs.
- Never expose credentials, sensitive configuration, or internal stack traces through API responses.
- Retry transient failures only.
- Do not retry permanent failures indiscriminately.

## 13. Logging

- Use Python logging.
- Avoid print statements in application code.
- Include execution IDs and step IDs in relevant log events.
- Keep execution logs distinguishable from application logs.
- Persist execution events when required by the execution history design.
- Avoid logging secrets, credentials, tokens, or sensitive request data.

## 14. Testing Guidelines

Use Pytest.

- Write tests for implemented functionality.
- Prefer unit tests for isolated components.
- Add integration tests for database, Redis, queue and execution flows where appropriate.
- Test successful execution.
- Test step failure.
- Test retry behavior.
- Test timeout behavior.
- Test state transitions.
- Test idempotency where implemented.
- Test cancellation where implemented.
- Use mocks only when appropriate.
- Do not claim tests passed unless they were actually executed.
- Do not remove or weaken existing tests merely to make implementation pass.

## 15. Security

- Never execute arbitrary workflow-provided code.
- Never execute arbitrary shell commands.
- Validate workflow definitions.
- Prevent unsafe HTTP step configurations where practical, including SSRF risks.
- Do not hardcode credentials.
- Use environment variables for configuration and secrets.
- Never commit `.env` files.
- Never log secrets.
- Avoid unsafe deserialization.
- Treat workflow inputs as untrusted data.

## 16. Configuration

- Centralize configuration.
- Use environment variables.
- Keep secrets out of source code.
- Provide `.env.example` containing placeholders only.
- Do not overwrite a user's existing environment configuration.
- Make local development configuration straightforward.

## 17. Coding Standards

- Follow PEP 8.
- Use clear and descriptive naming.
- Add type hints where practical.
- Prefer small, focused functions.
- Keep modules cohesive.
- Avoid unnecessarily large files.
- Avoid duplicated logic.
- Avoid unnecessary design patterns.
- Write readable code over clever code.
- Add comments only when they explain non-obvious decisions.
- Do not introduce dependencies without explaining why they are needed.

## 18. Git and File Modification Rules

- Inspect existing files before modifying them.
- Never overwrite existing work without inspecting it first.
- Do not delete files without justification.
- Do not modify unrelated files.
- Keep changes scoped to the requested task.
- Avoid large rewrites.
- Do not commit unless explicitly asked.
- Do not change project architecture without explaining the reason.

## 19. Agent Workflow

Before starting any task:

1. Read this AGENTS.md.
2. Inspect the existing project structure.
3. Read relevant files.
4. Understand existing implementation and dependencies.
5. Identify the smallest reasonable change.
6. Implement the task.
7. Run relevant tests and checks.
8. Report actual results.

For each task:

- Do not assume a feature exists without inspecting the code.
- Do not reimplement existing functionality.
- Do not make unrelated improvements.
- Do not expand scope without approval.
- Do not create unnecessary files.
- Do not generate lengthy documentation unless requested.
- Do not change previously agreed architecture without approval.

## 20. Credit-Efficient Agent Instructions

When working inside AI agent workspaces:

- Keep tasks tightly scoped.
- Inspect before acting.
- Avoid repeatedly scanning the entire project.
- Do not repeatedly restate or regenerate existing files.
- Do not perform unnecessary planning cycles.
- Do not use multiple agents on the same files simultaneously.
- Avoid expensive model usage for simple tasks.
- Complete the requested task before proposing additional work.
- Do not start the next phase without approval.

## 21. Task Completion Report

At the end of each task, report briefly:

1. What was implemented.
2. Files created or modified.
3. Important architectural decisions.
4. Tests/checks executed and their actual results.
5. Any unresolved issues.
6. The next logical task, without executing it automatically.

Do not claim functionality, test results, or integrations that were not verified.

## 22. Project Priorities

Priority order:

1. Correctness.
2. Functional implementation.
3. Reliability.
4. Testability.
5. Security.
6. Maintainability.
7. Simplicity.
8. Performance optimization when justified.

Build FlowForge incrementally and keep it runnable throughout development.