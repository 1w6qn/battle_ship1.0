"""Public chain-node area preview (ticket #12, legacy `spectate.preview_node`).

The chain frame must let both players see the area/line an opponent selected,
without forwarding the raw client `targets` (their shape is uncontrolled). The
public node is a whitelist: `{id, card, seat, board, shape, cells}`.

Only confirmed targets already stored on the `ChainItem` are read here. This
function never evaluates a card, never looks at ships, and never guesses a board
side: an unregistered card or a `choice` board without an explicit side yields
`None` (no preview) rather than a wrong board.
"""

from __future__ import annotations

from typing import Any

from ..room.models import Room, seat_label

BOARD_SIDES = ("self", "opponent")
PREVIEW_SHAPES = ("area", "line", "cells", "single")

#: Card name -> the board its area target belongs to (`choice` needs the client
#: to submit `board` explicitly; it is validated in the service layer).
AREA_TARGET_BOARDS: dict[str, str] = {
    "神威！": "choice",
    "冻结": "opponent",
    "探测雷达": "opponent",
    "轰炸": "opponent",
    "硫磺火焰": "opponent",
}


def _preview_cells(targets: Any) -> tuple[str, list[tuple[int, int]]] | None:
    if not isinstance(targets, dict):
        return None

    shape = targets.get("shape")
    if shape is not None:
        if shape not in PREVIEW_SHAPES:
            return None
        raw_cells = targets.get("cells")
        if not isinstance(raw_cells, (list, tuple)) or not raw_cells:
            return None
        cells: list[tuple[int, int]] = []
        for cell in raw_cells:
            if not isinstance(cell, dict):
                return None
            try:
                cells.append((int(cell["x"]), int(cell["y"])))
            except (KeyError, TypeError, ValueError):
                return None
        return shape, cells

    area = targets.get("target_area")
    if isinstance(area, dict):
        try:
            x1, y1 = int(area["x1"]), int(area["y1"])
            x2, y2 = int(area["x2"]), int(area["y2"])
        except (KeyError, TypeError, ValueError):
            return None
        cells = [
            (x, y)
            for y in range(min(y1, y2), max(y1, y2) + 1)
            for x in range(min(x1, x2), max(x1, x2) + 1)
        ]
        return ("area", cells) if cells else None

    line = targets.get("target_line")
    if isinstance(line, dict):
        try:
            index = int(line["index"])
        except (KeyError, TypeError, ValueError):
            return None
        if line.get("type") == "row":
            return "line", [(x, index) for x in range(6)]
        if line.get("type") == "col":
            return "line", [(index, y) for y in range(6)]
        return None

    for key in ("target_cells", "selected_cells"):
        raw = targets.get(key)
        if not isinstance(raw, (list, tuple)) or not raw:
            continue
        parsed: list[tuple[int, int]] = []
        for cell in raw:
            if not isinstance(cell, dict):
                return None
            try:
                parsed.append((int(cell["x"]), int(cell["y"])))
            except (KeyError, TypeError, ValueError):
                return None
        return "cells", parsed
    return None


def _preview_id(shape: str, cells: list[tuple[int, int]]) -> str:
    try:
        if shape == "area":
            xs = [cell[0] for cell in cells]
            ys = [cell[1] for cell in cells]
            return "area:%d,%d-%d,%d" % (min(xs), min(ys), max(xs), max(ys))
        if shape == "line":
            first = cells[0]
            kind = "row" if len({cell[1] for cell in cells}) == 1 else "col"
            return "line:%s:%d" % (kind, first[1] if kind == "row" else first[0])
        if shape == "cells" and len(cells) == 1:
            return "single:%d,%d" % cells[0]
        return "cells:%d" % len(cells)
    except (IndexError, TypeError, ValueError):
        return "unknown"


def preview_node(targets: Any, card_name: str | None, room: Room | None = None,
                 board: str | None = None) -> dict[str, Any] | None:
    """Public area preview for one chain node, or None when there is no area."""

    parsed = _preview_cells(targets)
    if parsed is None:
        return None
    shape, cells = parsed
    if any(not (0 <= x <= 5 and 0 <= y <= 5) for x, y in cells):
        return None
    declared = AREA_TARGET_BOARDS.get(card_name or "")
    if declared is None:
        return None
    side = board if board in BOARD_SIDES else None
    if side is None and declared in BOARD_SIDES:
        side = declared
    if side not in BOARD_SIDES:
        return None
    return {
        "id": _preview_id(shape, cells),
        "card": card_name,
        "seat": seat_label(room, None),
        "board": side,
        "shape": shape,
        "cells": [{"x": x, "y": y} for x, y in cells],
    }


__all__ = ["AREA_TARGET_BOARDS", "BOARD_SIDES", "PREVIEW_SHAPES", "preview_node"]
