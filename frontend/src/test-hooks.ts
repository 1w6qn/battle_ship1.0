import type { Pinia } from 'pinia'
import { defineComponent, h, watch, type Component } from 'vue'
import { useRoute, type Router } from 'vue-router'
import { io, type Socket } from 'socket.io-client'
import { routeLoading } from './router'
import { fetchRemoteContractHash, type TypedSocket } from './socket/client'
import { CONTRACT_SCHEMA_HASH, ROOM_SYNC_FIELDS } from './socket/events.gen'
import { useGameStore } from './stores/game'
import { useResultStore } from './stores/result'
import { useLobbyStore } from './stores/lobby'
import { GAME_STATE_SCHEMA, defaultGameState } from './stores/gameStateSchema'
import {
  applySettlementEvent,
  getSettlementSocket,
  settlementSocketConnected,
  type SettlementEventName,
} from './realtime/settlement'
import {
  applyLobbyEvent,
  getLobbySocket,
  lobbySocketConnected,
  type LobbyEventName,
} from './realtime/lobby'
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

export interface LobbyTestApi {
  socket: () => TypedSocket | null
  connected: () => boolean
  state: () => {
    hello: unknown
    snapshot: unknown
    chat: unknown[]
    connected: boolean
    subscribed: boolean
    queueMode: string | null
    ownRoomId: string
    ownRoomName: string
    ownRoomPublic: boolean
    activeInvite: unknown
    friends: unknown[]
    friendsLoaded: boolean
    friendsGuest: boolean
    friendsError: string
    notice: string
    error: string
    startedRoomId: string
  }
  /** Feed the exact production handler with a frozen payload (test build only). */
  feed: (event: string, payload: Record<string, unknown>) => void
  /** Deterministic friends fixture for screenshots (no wire event exists). */
  setFriends: (payload: Record<string, unknown>) => void
  setNotice: (text: string) => void
  clearError: () => void
  clearChat: () => void
  clearOwnRoom: () => void
  reset: () => void
  /** A second real Socket.IO client, used to seat/invite the other player. */
  createSocket: () => Socket
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
  lobby: LobbyTestApi
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

const LOBBY_EVENTS: readonly string[] = [
  'lobby_hello',
  'lobby_state',
  'lobby_chat_history',
  'lobby_chat',
  'match_queued',
  'match_canceled',
  'friend_invite',
  'game_state',
  'room_sync',
  'error',
]

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
  const lobbyStore = useLobbyStore(pinia)

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

  const lobby: LobbyTestApi = {
    socket: () => getLobbySocket(),
    connected: () => lobbySocketConnected(),
    state: () =>
      JSON.parse(JSON.stringify({
        hello: lobbyStore.hello,
        snapshot: lobbyStore.snapshot,
        chat: lobbyStore.chat,
        connected: lobbyStore.connected,
        subscribed: lobbyStore.subscribed,
        queueMode: lobbyStore.queueMode,
        ownRoomId: lobbyStore.ownRoomId,
        ownRoomName: lobbyStore.ownRoomName,
        ownRoomPublic: lobbyStore.ownRoomPublic,
        activeInvite: lobbyStore.activeInvite,
        friends: lobbyStore.friends,
        friendsLoaded: lobbyStore.friendsLoaded,
        friendsGuest: lobbyStore.friendsGuest,
        friendsError: lobbyStore.friendsError,
        notice: lobbyStore.notice,
        error: lobbyStore.error,
        startedRoomId: lobbyStore.startedRoomId,
      })),
    feed: (event, payload) => {
      if (!LOBBY_EVENTS.includes(event)) throw new Error('unknown lobby event: ' + event)
      applyLobbyEvent(event as LobbyEventName, payload, pinia)
    },
    setFriends: (payload) => lobbyStore.recordFriends(payload),
    setNotice: (text) => lobbyStore.setNotice(text),
    clearError: () => lobbyStore.clearError(),
    clearChat: () => lobbyStore.clearChat(),
    clearOwnRoom: () => lobbyStore.clearOwnRoom(),
    reset: () => lobbyStore.reset(),
    createSocket: () => {
      const socket = io({ autoConnect: false, withCredentials: true, transports: ['websocket', 'polling'] })
      socket.connect()
      return socket
    },
  }

  window.__BS_TEST__ = {
    version: 'ticket-22',
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
    lobby,
    crashNext: (routeName: string) => requestCrash(routeName),
  }
}