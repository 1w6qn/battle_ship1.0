import type { Pinia } from 'pinia'
import { createTypedSocket, type TypedSocket } from '../socket/client'
import { useGameStore } from '../stores/game'
import { useResultStore } from '../stores/result'

/**
 * The settlement wire channel (ticket #22).
 *
 * One typed Socket.IO connection feeds the Pinia stores. It is acquired by the
 * game-over screen (and reused by the future game screen) instead of every
 * component opening its own connection. The listener bodies live in
 * applySettlementEvent so the test build can feed the same handler with a
 * frozen payload without bypassing production logic.
 */
export type SettlementEventName =
  | 'game_over'
  | 'game_state'
  | 'room_sync'
  | 'xp_gained'
  | 'rank_changed'
  | 'achievements_unlocked'
  | 'ships_updated'

const SETTLEMENT_EVENTS: readonly SettlementEventName[] = [
  'game_over',
  'game_state',
  'room_sync',
  'xp_gained',
  'rank_changed',
  'achievements_unlocked',
  'ships_updated',
]

function asString(value: unknown): string {
  return typeof value === 'string' ? value : ''
}

/** Apply one server frame to the stores. The single implementation the wire and the gate share. */
export function applySettlementEvent(
  event: SettlementEventName,
  payload: Record<string, unknown> | null | undefined,
  pinia?: Pinia,
): void {
  if (!payload || typeof payload !== 'object') return
  const game = useGameStore(pinia)
  const result = useResultStore(pinia)

  switch (event) {
    case 'game_over': {
      const winner = payload.winner
      game.applyServerState({
        state: 'game_over',
        winner: winner == null ? '' : String(winner),
        game_over_reason: asString(payload.reason) || null,
      })
      result.recordGameOver(payload)
      break
    }
    case 'game_state': {
      game.applyServerState(payload)
      if (payload.state === 'game_over') result.recordGameOver(payload)
      else if (payload.state === 'placing_ships') result.beginMatch()
      break
    }
    case 'room_sync': {
      game.applyServerState(payload)
      if (payload.state === 'game_over') {
        result.recordGameOver({
          winner: payload.winner,
          game_over_reason: payload.game_over_reason,
        })
      }
      break
    }
    case 'xp_gained':
      result.recordXp(payload)
      break
    case 'rank_changed':
      result.recordRank(payload)
      break
    case 'achievements_unlocked':
      result.recordAchievements(payload)
      break
    case 'ships_updated':
      game.applyServerState({
        remaining_ships: payload.player_remaining_ships,
        opponent_remaining_ships: payload.opponent_remaining_ships,
      })
      break
  }
}

export function installSettlementListeners(socket: TypedSocket, pinia?: Pinia): () => void {
  const offs = SETTLEMENT_EVENTS.map((event) =>
    socket.on(event, (payload) => applySettlementEvent(event, payload, pinia)),
  )
  return () => {
    for (const off of offs) off()
  }
}

interface ActiveChannel {
  socket: TypedSocket
  stop: () => void
  refs: number
}

let active: ActiveChannel | null = null

/**
 * Acquire the shared channel. The returned release function disconnects when
 * the last screen using it goes away; Pinia state survives, only the socket
 * does not.
 */
export function acquireSettlementChannel(pinia?: Pinia): () => void {
  if (!active) {
    const socket = createTypedSocket()
    const stopListeners = installSettlementListeners(socket, pinia)
    socket.connect()
    active = {
      socket,
      stop: () => {
        stopListeners()
        socket.disconnect()
      },
      refs: 0,
    }
  }
  const channel = active
  channel.refs += 1
  let released = false
  return () => {
    if (released) return
    released = true
    channel.refs -= 1
    if (channel.refs <= 0 && active === channel) {
      channel.stop()
      active = null
    }
  }
}

export function getSettlementSocket(): TypedSocket | null {
  return active?.socket ?? null
}

export function settlementSocketConnected(): boolean {
  return active?.socket.socket.connected ?? false
}

/** Test-build helper: drop the singleton between browser checks. */
export function resetSettlementChannelForTest(): void {
  if (!active) return
  active.stop()
  active = null
}
