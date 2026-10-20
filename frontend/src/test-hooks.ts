import type { Pinia } from 'pinia'
import { defineComponent, h, watch, type Component } from 'vue'
import { useRoute, type Router } from 'vue-router'
import { io, type Socket } from 'socket.io-client'
import { routeLoading } from './router'
import { fetchRemoteContractHash, type TypedSocket } from './socket/client'
import { CONTRACT_SCHEMA_HASH, ROOM_SYNC_FIELDS } from './socket/events.gen'
import { useGameStore } from './stores/game'
import { useLeaderboardStore } from './stores/leaderboard'
import { useProfileStore } from './stores/profile'
import { useResultStore } from './stores/result'
import { useSettingsStore } from './stores/settings'
import { GAME_STATE_SCHEMA, defaultGameState } from './stores/gameStateSchema'
import {
  applySettlementEvent,
  getSettlementSocket,
  settlementSocketConnected,
  type SettlementEventName,
} from './realtime/settlement'
import {
  applyMatchEvent,
  MATCH_EVENTS,
  setMatchAckInterceptor,
  type MatchEventName,
} from './realtime/match'
import { usePlacementStore } from './stores/placement'
import { useRpsStore } from './stores/rps'
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

export interface ScreensTestApi {
  /** Read-only snapshots of the ticket #25 screen stores. */
  profile: () => unknown
  leaderboard: () => unknown
  settings: () => unknown
}

export interface MatchTestApi {
  /** Mirror of the placement / rps local state (draft board, wait, timeout). */
  state: () => { placement: Record<string, unknown>; rps: Record<string, unknown> }
  /** Feed the exact production handler with a frozen payload (test build only). */
  feed: (event: string, payload: Record<string, unknown>) => void
  /** Shrink the 6s ack waits so the timeout state is deterministic. */
  configureAckTiming: (options: { ackTimeoutMs?: number; tickMs?: number }) => void
  /** Drop the next match command frame, simulating a lost ack. */
  silenceNextAck: () => void
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
  screens: ScreensTestApi
  match: MatchTestApi
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
  const profile = useProfileStore(pinia)
  const leaderboard = useLeaderboardStore(pinia)
  const settings = useSettingsStore(pinia)

  const snapshot = (value: unknown): unknown => JSON.parse(JSON.stringify(value))

  const screens: ScreensTestApi = {
    profile: () =>
      snapshot({
        ownStatus: profile.ownStatus,
        viewerName: profile.viewerName,
        viewed: profile.viewed,
      }),
    leaderboard: () =>
      snapshot({
        activeTab: leaderboard.activeTab,
        record: leaderboard.record,
        ranked: leaderboard.ranked,
      }),
    settings: () =>
      snapshot({
        profileStatus: settings.profileStatus,
        privacy: settings.privacy,
        replay: settings.replay,
        spectate: settings.spectate,
        passwordMessage: settings.passwordMessage,
        wallpaper: settings.wallpaper,
      }),
  }

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

  const placement = usePlacementStore(pinia)
  const rps = useRpsStore(pinia)
  let silencedAcks = 0
  setMatchAckInterceptor(() => {
    if (silencedAcks > 0) {
      silencedAcks -= 1
      return true
    }
    return false
  })

  const match: MatchTestApi = {
    state: () =>
      JSON.parse(JSON.stringify({
        placement: {
          maxShips: placement.maxShips,
          cells: placement.cells,
          placedCount: placement.placedCount,
          submitted: placement.submitted,
          pending: placement.pending,
          countdown: placement.countdown,
          error: placement.error,
          resetMessage: placement.resetMessage,
          resetPhase: placement.resetPhase,
          canSubmit: placement.canSubmit,
          hint: placement.hint,
        },
        rps: {
          result: rps.result,
          pendingChoice: rps.pendingChoice,
          waiting: rps.waiting,
          countdown: rps.countdown,
          error: rps.error,
        },
      })),
    feed: (event, payload) => {
      if (!MATCH_EVENTS.includes(event as MatchEventName)) throw new Error('unknown match event: ' + event)
      applyMatchEvent(event as MatchEventName, payload, pinia)
    },
    configureAckTiming: (options) => {
      placement.configureAckTiming(options)
      rps.configureAckTiming(options)
    },
    silenceNextAck: () => {
      silencedAcks += 1
    },
  }

  window.__BS_TEST__ = {
    version: 'ticket-25+ticket-23',
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
    screens,
    match,
    crashNext: (routeName: string) => requestCrash(routeName),
  }
}
