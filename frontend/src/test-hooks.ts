import type { Pinia } from 'pinia'
import { defineComponent, h, watch, type Component } from 'vue'
import { useRoute, type Router } from 'vue-router'
import { io, type Socket } from 'socket.io-client'
import { routeLoading } from './router'
import { fetchRemoteContractHash, type TypedSocket } from './socket/client'
import { CONTRACT_SCHEMA_HASH, ROOM_SYNC_FIELDS } from './socket/events.gen'
import { useGameStore } from './stores/game'
import { useReplayStore } from './stores/replay'
import { useResultStore } from './stores/result'
import { useSpectateStore } from './stores/spectate'
import { GAME_STATE_SCHEMA, defaultGameState } from './stores/gameStateSchema'
import {
  SPECTATE_EVENTS,
  applySpectateEvent,
  getSpectateSocket,
  joinSpectate,
  leaveSpectate,
  resetSpectateChannelForTest,
  sendSpectateChat,
  spectateSocketConnected,
  type SpectateEventName,
} from './realtime/spectate'
import {
  applySettlementEvent,
  getSettlementSocket,
  settlementSocketConnected,
  type SettlementEventName,
} from './realtime/settlement'
import { CrashProbe } from './test-crash/CrashProbe'
import { crashTarget, requestCrash } from './test-crash/state'

/**
 * Test-build-only introspection for the external browser gate
 * (D:/develop/battleship-verify/cases/22-sample/browser_check.mjs).
 *
 * Production entry points never import this module: main.ts decides between
 * the plain App and createTestRoot on the compile-time __BS_TEST_HOOKS__.
 */

interface RouteLoadingEntry {
  path: string
  loading: boolean
}

export interface SettlementTestApi {
  socket: () => TypedSocket | null
  connected: () => boolean
  state: () => {
    gameOver: unknown
    xp: unknown
    rank: unknown
    achievements: unknown[]
    recentOpponent: unknown
  }
  /** Feed the exact production handler with a frozen payload (test build only). */
  feed: (event: string, payload: Record<string, unknown>) => void
  /** A second real Socket.IO client, used to seat the opponent. */
  createSocket: () => Socket
}

export interface ReplayTestApi {
  state: () => {
    status: string
    error: string
    matchId: string
    youAre: string | null
    k: number
    playing: boolean
    speed: number
    stepCount: number
    truncated: string
  }
  payload: () => unknown
  frame: () => unknown
  load: (matchId: string) => Promise<void>
}

export interface SpectateTestApi {
  state: () => Record<string, unknown>
  feed: (event: string, payload: Record<string, unknown>) => void
  socket: () => TypedSocket | null
  connected: () => boolean
  join: (roomId: string) => Promise<{ ok: boolean; message: string }>
  leave: () => Promise<void>
  chat: (message: string) => Promise<{ ok: boolean; message: string }>
  resetChannel: () => void
}

export interface TestHooksApi {
  version: string
  router: Router
  currentRouteName: () => string | null
  routeLoadingHistory: () => RouteLoadingEntry[]
  clearRouteLoadingHistory: () => void
  contractHash: string
  fetchRemoteContractHash: typeof fetchRemoteContractHash
  roomSyncFields: string[]
  gameStateSchemaFields: string[]
  gameStateSchema: typeof GAME_STATE_SCHEMA
  defaultGameState: () => unknown
  gameState: () => unknown
  settlement: SettlementTestApi
  replay: ReplayTestApi
  spectate: SpectateTestApi
  crashNext: (routeName: string) => void
}

declare global {
  interface Window {
    __BS_TEST__?: TestHooksApi
  }
}

/** Wrap the shell so the crash probe renders inside its ScreenBoundary slot. */
export function createTestRoot(Root: Component): Component {
  return defineComponent({
    name: 'TestRoot',
    setup() {
      const route = useRoute()
      return () =>
        h(Root, null, {
          'screen-extra': () => (crashTarget.value === route.name ? h(CrashProbe) : null),
        })
    },
  })
}

const SETTLEMENT_EVENTS: readonly string[] = [
  'game_over',
  'game_state',
  'room_sync',
  'xp_gained',
  'rank_changed',
  'achievements_unlocked',
  'ships_updated',
]

export function installTestHooks(router: Router, pinia: Pinia): void {
  const history: RouteLoadingEntry[] = []
  watch(routeLoading, (loading) => {
    history.push({ path: router.currentRoute.value.fullPath, loading })
  })

  const game = useGameStore(pinia)
  const result = useResultStore(pinia)
  const replay = useReplayStore(pinia)
  const spectate = useSpectateStore(pinia)

  const settlement: SettlementTestApi = {
    socket: () => getSettlementSocket(),
    connected: () => settlementSocketConnected(),
    state: () =>
      JSON.parse(JSON.stringify({
        gameOver: result.gameOver,
        xp: result.xp,
        rank: result.rank,
        achievements: result.achievements,
        recentOpponent: result.recentOpponent,
      })),
    feed: (event, payload) => {
      if (!SETTLEMENT_EVENTS.includes(event)) throw new Error('unknown settlement event: ' + event)
      applySettlementEvent(event as SettlementEventName, payload, pinia)
    },
    createSocket: () => {
      const socket = io({ autoConnect: false, withCredentials: true, transports: ['websocket', 'polling'] })
      socket.connect()
      return socket
    },
  }

  const replayApi: ReplayTestApi = {
    state: () =>
      JSON.parse(JSON.stringify({
        status: replay.status,
        error: replay.error,
        matchId: replay.matchId,
        youAre: replay.youAre,
        k: replay.k,
        playing: replay.playing,
        speed: replay.speed,
        stepCount: replay.stepCount,
        truncated: replay.payload?.truncated ?? '',
      })),
    payload: () => JSON.parse(JSON.stringify(replay.payload)),
    frame: () => JSON.parse(JSON.stringify(replay.frame)),
    load: (matchId: string) => replay.load(matchId),
  }

  const spectateApi: SpectateTestApi = {
    state: () =>
      JSON.parse(JSON.stringify({
        phase: spectate.phase,
        error: spectate.error,
        roomId: spectate.roomId,
        endedReason: spectate.endedReason,
        winnerLabel: spectate.winnerLabel,
        stateValue: spectate.stateValue,
        currentPhase: spectate.currentPhase,
        currentAttacker: spectate.currentAttacker,
        attacksRemaining: spectate.attacksRemaining,
        round: spectate.round,
        fieldMagic: spectate.fieldMagic,
        ranked: spectate.ranked,
        seatLabels: spectate.seatLabels,
        sides: spectate.sides,
        attacks: spectate.attacks,
        count: spectate.count,
        limit: spectate.limit,
        me: spectate.me,
        roster: spectate.roster,
        chat: spectate.chat,
        chain: spectate.chain,
        logs: spectate.logs,
      })),
    feed: (event: string, payload: Record<string, unknown>) => {
      if (!SPECTATE_EVENTS.includes(event as SpectateEventName)) {
        throw new Error('unknown spectate event: ' + event)
      }
      applySpectateEvent(event as SpectateEventName, payload, pinia)
    },
    socket: () => getSpectateSocket(),
    connected: () => spectateSocketConnected(),
    join: (roomId: string) => joinSpectate(roomId, pinia),
    leave: () => leaveSpectate(pinia),
    chat: (message: string) => sendSpectateChat(message, pinia),
    resetChannel: () => resetSpectateChannelForTest(),
  }

  window.__BS_TEST__ = {
    version: 'ticket-28',
    router,
    currentRouteName: () => (router.currentRoute.value.name as string | null) ?? null,
    routeLoadingHistory: () => history.slice(),
    clearRouteLoadingHistory: () => {
      history.length = 0
    },
    contractHash: CONTRACT_SCHEMA_HASH,
    fetchRemoteContractHash,
    roomSyncFields: [...ROOM_SYNC_FIELDS],
    gameStateSchemaFields: Object.keys(GAME_STATE_SCHEMA.fields),
    gameStateSchema: GAME_STATE_SCHEMA,
    defaultGameState: () => defaultGameState(),
    gameState: () => JSON.parse(JSON.stringify(game.state)),
    settlement,
    replay: replayApi,
    spectate: spectateApi,
    crashNext: (routeName: string) => requestCrash(routeName),
  }
}