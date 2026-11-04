from enum import Enum
class ToolCallStatus(str, Enum):
    SUCCESS = "success"
    FAILED = "failed"
    NOT_FOUND = "not_found"