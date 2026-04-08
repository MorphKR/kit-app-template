from .constant import *
from .section_manager import CutDirection, SectionManager, WidgetAlignment
from .utils import *

# Keep optional imports resilient so SectionManager import works even if
# viewport-related modules are unavailable in current runtime context.
try:
    from .selection_state import SelectionState
except Exception:  # pragma: no cover
    SelectionState = None

__all__ = [
    "CutDirection",
    "SectionManager",
    "WidgetAlignment",
    "SelectionState",
]
