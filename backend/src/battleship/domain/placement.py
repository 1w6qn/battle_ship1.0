"""Opening ship placement: the single implementation of board legality.

The legacy `handle_place_ships` validates a flat list of single-cell ships and
then stores it; every error string below is the recorded wire text (port map
13-domain-rules §1.1), because the old frontend surfaces the ack message
verbatim. Later placement flows (reinforcement / revive / redeploy) belong to
ticket #10 and must not grow a second copy of these rules.

Deliberately preserved legacy quirk (DECISIONS D1): there is **no room-state
gate** here. Re-sending `place_ships` while attacking resets the board and
drags the room back to rock-paper-scissors. :func:`apply_placement` therefore
only owns the board; the service decides the state transition.
"""

from __future__ import annotations

from typing import Any, Sequence

from .room import (
    BOARD_SIZE,
    DEFAULT_MAX_SHIPS,
    Player,
    PlayerShip,
    Position,
    Room,
)


class PlacementError(ValueError):
    """A rejected placement; `str(error)` is the legacy player-facing text."""


def expected_ship_count(player: Player) -> int:
    value = getattr(player, "max_ships", None)
    return int(value) if value else DEFAULT_MAX_SHIPS


def _parse_position(raw: Any) -> Position:
    if not isinstance(raw, dict):
        raise PlacementError("战舰坐标格式错误")
    try:
        px, py = int(raw["x"]), int(raw["y"])
    except (KeyError, TypeError, ValueError, OverflowError):
        raise PlacementError("战舰坐标非法") from None
    if not (0 <= px < BOARD_SIZE and 0 <= py < BOARD_SIZE):
        raise PlacementError("战舰坐标超出棋盘范围")
    return Position(x=px, y=py)


def _parse_ship(raw: Any) -> PlayerShip:
    if not isinstance(raw, dict):
        raise PlacementError("战舰数据格式错误")
    positions = raw.get("positions") or []
    if not isinstance(positions, list) or not positions:
        raise PlacementError("战舰缺少位置信息")
    return PlayerShip(positions=[_parse_position(pos) for pos in positions])


def validate_placement(raw_ships: Any, expected: int) -> list[PlayerShip]:
    """Validate and convert the wire payload; raises PlacementError.

    Legacy rules (server.py:3869-3893): the list must be non-empty, contain
    exactly `expected` ships, every ship needs non-empty positions, every
    coordinate is an integer in 0..5, and no two cells may coincide (the
    occupied set spans the whole submission, so a duplicate inside one ship is
    rejected too).
    """

    if not isinstance(raw_ships, list) or not raw_ships:
        raise PlacementError("布船数据无效")
    if len(raw_ships) != expected:
        raise PlacementError(f"需要放置 {expected} 艘战舰")

    occupied: set[tuple[int, int]] = set()
    ships: list[PlayerShip] = []
    for raw in raw_ships:
        ship = _parse_ship(raw)
        for position in ship.positions:
            cell = (position.x, position.y)
            if cell in occupied:
                raise PlacementError("战舰不能重叠")
            occupied.add(cell)
        ships.append(ship)
    return ships


def apply_placement(player: Player, ships: Sequence[PlayerShip]) -> None:
    """Store a validated board. `remaining_ships` is the attack-count source."""

    player.ships = list(ships)
    player.remaining_ships = len(ships)


def all_players_placed(room: Room) -> bool:
    return bool(room.players) and all(len(seat.ships or []) > 0 for seat in room.players.values())


def auto_place_ai(room: Room, player_id: str, rng) -> list[PlayerShip]:
    """Random single-cell board for an AI seat, exactly like `_ai_place_ships`.

    Shuffle all 36 cells and take the seat's ship count; the board is rebuilt
    from scratch (legacy behaviour).
    """

    player = room.players[player_id]
    cells = [(x, y) for x in range(BOARD_SIZE) for y in range(BOARD_SIZE)]
    rng.shuffle(cells)
    ships = [
        PlayerShip(positions=[Position(x=x, y=y)])
        for x, y in cells[: expected_ship_count(player)]
    ]
    player.ships = ships
    player.remaining_ships = len(ships)
    return ships