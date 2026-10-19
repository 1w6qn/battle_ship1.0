"""Cancellable background timers (re-export; ticket #12).

The registry itself lives in :mod:`battleship.infra.timers` so services can use
it without importing the socket layer (domain/services must not depend on
realtime). This module is the realtime-facing export point.
"""

from ..infra.timers import TaskRegistry

__all__ = ["TaskRegistry"]
