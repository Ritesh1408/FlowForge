"""Application errors that map to client-facing HTTP responses.

Messages must be safe to show to API clients: no internal details or secrets.
"""


class FlowForgeError(Exception):
    status_code = 500
    code = "internal_error"

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class NotFoundError(FlowForgeError):
    status_code = 404
    code = "not_found"


class ConflictError(FlowForgeError):
    status_code = 409
    code = "conflict"


class WorkflowNotFoundError(NotFoundError):
    code = "workflow_not_found"


class WorkflowNameConflictError(ConflictError):
    code = "workflow_name_conflict"


class ServiceUnavailableError(FlowForgeError):
    status_code = 503
    code = "service_unavailable"


class ExecutionPersistenceError(ServiceUnavailableError):
    code = "execution_persistence_failed"


class ExecutionQueueUnavailableError(ServiceUnavailableError):
    code = "execution_queue_unavailable"
