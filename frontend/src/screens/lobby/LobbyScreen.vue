<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { acquireLobbyChannel, getLobbySocket } from '../../realtime/lobby'
import {
  lobbyPlayerName,
  useLobbyStore,
  type LobbyFilter,
  type LobbyFriend,
  type LobbyMatch,
  type LobbyRoom,
} from '../../stores/lobby'
import {
  FILTERS,
  filterMatches,
  filterRooms,
  initial,
  inviteDisabledReason,
  levelText,
  matchNamesText,
  matchSpectateText,
  matchesEmptyText,
  queueModeText,
  rankText,
  roomJoinable,
  roomSeatsText,
  roomsEmptyText,
  showsMatches,
  showsRooms,
  statusText,
  timeText,
} from './view'

/**
 * Ticket #24: the lobby screen.
 *
 * Data comes from the real lobby broadcast and the already-implemented friends
 * routes. This component only formats server values and keeps view state
 * (search text, active filter, drafts). "Me" is lobby_hello.key compared with
 * the broadcast keys — the server cannot add is_me to a broadcast.
 */
const router = useRouter()
const lobby = useLobbyStore()

const filter = ref<LobbyFilter>('all')
const query = ref('')
const roomName = ref('')
const roomPublic = ref(true)
const chatDraft = ref('')
const invitingUsername = ref('')
const acceptingInvite = ref(false)
const friendsBusy = ref(false)
const chatEl = ref<HTMLElement | null>(null)

let releaseChannel: (() => void) | null = null

const filteredRooms = computed(() => filterRooms(lobby.rooms, filter.value, query.value))
const filteredMatches = computed(() => filterMatches(lobby.matches, filter.value, query.value))
const roomsVisible = computed(() => showsRooms(filter.value))
const matchesVisible = computed(() => showsMatches(filter.value))
const roomsEmpty = computed(() => roomsEmptyText(lobby.rooms.length, filter.value, query.value))
const matchesEmpty = computed(() => matchesEmptyText(lobby.matches.length, query.value))
const friendListVisible = computed(
  () => lobby.friendsLoaded && !lobby.friendsGuest && !lobby.friendsError,
)
const queueLabel = computed(() => queueModeText(lobby.queueMode))

function countText(value: number): string {
  return lobby.hasSnapshot ? String(value) : '—'
}

function isMePlayer(key: string): boolean {
  return Boolean(lobby.myKey) && key === lobby.myKey
}

function isMineChat(key: string): boolean {
  return Boolean(lobby.myKey) && key === lobby.myKey
}

function playerNameClass(style: string): string {
  return style === 'rainbow' ? 'lobby__player-name lobby__player-name--rainbow' : 'lobby__player-name'
}

function avatarStyle(avatar: string): Record<string, string> {
  if (!avatar) return {}
  const safe = avatar.replace(/["\\]/g, '')
  return { backgroundImage: 'url("' + safe + '")' }
}

function chatKey(seq: number, key: string, ts: number): string {
  return seq > 0 ? 'seq-' + seq : 'line-' + key + '-' + ts
}

function friendStatus(friend: LobbyFriend): string {
  if (!friend.online) return '离线'
  return friend.inGame ? '对局中' : '在线'
}

function friendInviteReason(friend: LobbyFriend): string {
  return inviteDisabledReason(friend) || '邀请他打一局'
}

function setNotice(text: string): void {
  lobby.clearError()
  lobby.setNotice(text)
}

function fail(message: string): void {
  lobby.setError(message)
}

function socketOrFail() {
  const socket = getLobbySocket()
  if (!socket || !socket.socket.connected) {
    fail('连接尚未就绪，请稍后再试')
    return null
  }
  return socket
}

function ackField(ack: unknown, key: string): unknown {
  return (ack as Record<string, unknown>)[key]
}

function refresh(): void {
  const socket = socketOrFail()
  if (!socket) return
  void socket.emitEvent('lobby_refresh', {}).catch((error: unknown) => {
    fail(error instanceof Error ? error.message : String(error))
  })
}

function createRoom(): void {
  const socket = socketOrFail()
  if (!socket) return
  const name = roomName.value.trim()
  void socket
    .emitEvent('lobby_create_room', {
      name,
      public: roomPublic.value,
      player_name: lobbyPlayerName(),
    })
    .then((ack) => {
      if (ack.status !== 'success') {
        fail(ack.message || '创建房间失败')
        return
      }
      const roomId = String(ackField(ack, 'room_id') || '')
      if (!roomId) {
        fail('创建房间失败：服务端没有返回房号')
        return
      }
      const createdName = String(ackField(ack, 'name') || name)
      const isPublic = ackField(ack, 'public') !== false
      lobby.setOwnRoom(roomId, createdName, isPublic)
      roomName.value = ''
      setNotice('房间已创建：' + roomId + '，等待玩家加入')
    })
    .catch((error: unknown) => {
      fail(error instanceof Error ? error.message : String(error))
    })
}

function joinRoom(room: LobbyRoom): void {
  if (!roomJoinable(room)) return
  const socket = socketOrFail()
  if (!socket) return
  void socket
    .emitEvent('join_room', { room_id: room.roomId, player_name: lobbyPlayerName() })
    .then((ack) => {
      if (ack.status !== 'success') {
        fail(ack.message || '加入房间失败')
        return
      }
      setNotice('已加入房间 ' + room.roomId + '，对局即将开始')
    })
    .catch((error: unknown) => {
      fail(error instanceof Error ? error.message : String(error))
    })
}

function closeRoom(roomId: string): void {
  if (!roomId) return
  const socket = socketOrFail()
  if (!socket) return
  void socket
    .emitEvent('close_room', { room_id: roomId })
    .then((ack) => {
      if (ack.status !== 'success') {
        fail(ack.message || '解散房间失败')
        return
      }
      if (lobby.ownRoomId === roomId) lobby.clearOwnRoom()
      setNotice('房间已解散')
    })
    .catch((error: unknown) => {
      fail(error instanceof Error ? error.message : String(error))
    })
}

function closeOwnRoom(): void {
  closeRoom(lobby.ownRoomId)
}

function startMatch(mode: 'casual' | 'ranked'): void {
  const socket = socketOrFail()
  if (!socket) return
  void socket
    .emitEvent('find_match', { player_name: lobbyPlayerName(), mode })
    .then((ack) => {
      if (ack.status === 'error') fail(ack.message || '匹配失败')
    })
    .catch((error: unknown) => {
      fail(error instanceof Error ? error.message : String(error))
    })
}

function cancelMatch(): void {
  const socket = socketOrFail()
  if (!socket) return
  void socket.emitEvent('cancel_match', {}).catch((error: unknown) => {
    fail(error instanceof Error ? error.message : String(error))
  })
}

function sendChat(): void {
  const text = chatDraft.value.trim()
  if (!text) return
  const socket = socketOrFail()
  if (!socket) return
  void socket
    .emitEvent('lobby_chat_send', { message: text })
    .then((ack) => {
      if (ack.status === 'error') {
        fail(ack.message || '发送失败')
        return
      }
      chatDraft.value = ''
    })
    .catch((error: unknown) => {
      fail(error instanceof Error ? error.message : String(error))
    })
}

async function loadFriends(): Promise<void> {
  if (friendsBusy.value) return
  friendsBusy.value = true
  try {
    const response = await fetch('/api/friends', {
      credentials: 'same-origin',
      headers: { accept: 'application/json' },
    })
    if (response.status === 401) {
      lobby.recordFriendsGuest()
      return
    }
    const body = (await response.json().catch(() => ({}))) as Record<string, unknown>
    if (!response.ok) {
      const message = typeof body.error === 'string' ? body.error : '读取好友列表失败'
      lobby.recordFriendsError(message)
      return
    }
    lobby.recordFriends(body)
  } catch (error) {
    lobby.recordFriendsError(error instanceof Error ? error.message : '读取好友列表失败')
  } finally {
    friendsBusy.value = false
  }
}

async function inviteFriend(friend: LobbyFriend): Promise<void> {
  if (!friend.username || invitingUsername.value) return
  const reason = inviteDisabledReason(friend)
  if (reason) {
    fail(reason)
    return
  }
  invitingUsername.value = friend.username
  try {
    const response = await fetch('/api/friends/invite', {
      method: 'POST',
      credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json', accept: 'application/json' },
      body: JSON.stringify({ username: friend.username }),
    })
    const body = (await response.json().catch(() => ({}))) as Record<string, unknown>
    if (!response.ok || body.status !== 'ok' || !body.room_id) {
      const message =
        typeof body.error === 'string' ? body.error : '邀战失败，请稍后再试'
      fail(message)
      return
    }
    const roomId = String(body.room_id)
    const socket = socketOrFail()
    if (!socket) return
    const joined = await socket.emitEvent('join_room', {
      room_id: roomId,
      player_name: lobbyPlayerName(),
    })
    if (joined.status !== 'success') {
      fail(joined.message || '进入房间失败')
      return
    }
    lobby.setOwnRoom(roomId, '好友邀战', true)
    setNotice('已邀请 ' + friend.username + '，等待对方进入房间 ' + roomId)
  } catch (error) {
    fail(error instanceof Error ? error.message : '邀战失败，请稍后再试')
  } finally {
    invitingUsername.value = ''
  }
}

async function acceptInvite(): Promise<void> {
  const invite = lobby.activeInvite
  if (!invite || acceptingInvite.value) return
  const socket = socketOrFail()
  if (!socket) return
  acceptingInvite.value = true
  try {
    const ack = await socket.emitEvent('join_room', {
      room_id: invite.roomId,
      player_name: lobbyPlayerName(),
    })
    if (ack.status !== 'success') {
      fail(ack.message || '进入房间失败')
      return
    }
    lobby.clearInvite()
    setNotice('已进入房间 ' + invite.roomId + '，等待对局开始…')
  } catch (error) {
    fail(error instanceof Error ? error.message : '进入房间失败')
  } finally {
    acceptingInvite.value = false
  }
}

function dismissInvite(): void {
  lobby.clearInvite()
}

function openSpectate(match: LobbyMatch): void {
  void router.push({ name: 'spectate', query: { room_id: match.roomId } })
}

function backHome(): void {
  void router.push({ name: 'start' })
}

function maybeLeaveLobbyForMatch(): void {
  const roomId = lobby.takeStartedRoom()
  if (roomId) void router.push({ name: 'placement' })
}

watch(() => lobby.startedRoomId, maybeLeaveLobbyForMatch)

// Keep the newest line visible without ever clearing the frame (legacy
// behaviour). The draft lives in a separate input, so this cannot wipe it.
watch(
  () => lobby.chat.length,
  async () => {
    await nextTick()
    if (chatEl.value) chatEl.value.scrollTop = chatEl.value.scrollHeight
  },
)

onMounted(() => {
  releaseChannel = acquireLobbyChannel()
  void loadFriends()
  maybeLeaveLobbyForMatch()
})

onBeforeUnmount(() => {
  // A late room_sync after the route change must not leave a stale "start a
  // match" flag for the next time this screen is mounted.
  lobby.takeStartedRoom()
  releaseChannel?.()
  releaseChannel = null
})
</script>

<template>
  <section
    class="screen lobby"
    data-screen="lobby"
    data-testid="screen-lobby"
    :data-lobby-filter="filter"
    aria-labelledby="screen-lobby-title"
  >
    <header class="lobby__head">
      <div class="lobby__title-block">
        <p class="lobby__eyebrow">P4 · 大厅</p>
        <h1 id="screen-lobby-title" class="lobby__title" data-testid="lobby-heading">游戏大厅</h1>
        <p class="lobby__hint">匹配、房间、公屏与好友邀战都在这一页，状态由服务端实时推送。</p>
      </div>

      <div class="lobby__topbar" aria-label="大厅统计">
        <span class="lobby__stat">在线玩家 <b data-testid="lobby-online-count">{{ countText(lobby.onlineCount) }}</b></span>
        <span class="lobby__stat">大厅中 <b data-testid="lobby-lobby-count">{{ countText(lobby.lobbyCount) }}</b></span>
        <span class="lobby__stat">休闲队列 <b data-testid="lobby-queue-casual">{{ countText(lobby.queueCasual) }}</b></span>
        <span class="lobby__stat">排位队列 <b data-testid="lobby-queue-ranked">{{ countText(lobby.queueRanked) }}</b></span>
        <span v-if="queueLabel" class="lobby__queue" data-testid="lobby-queue-state">{{ queueLabel }}</span>
        <button type="button" class="button button--ghost" data-testid="lobby-refresh" @click="refresh">刷新</button>
      </div>
    </header>

    <p v-if="lobby.notice" class="lobby__notice" data-testid="lobby-notice" role="status">{{ lobby.notice }}</p>
    <p v-if="lobby.error" class="lobby__error" data-testid="lobby-error" role="alert">
      {{ lobby.error }}
      <button type="button" class="lobby__dismiss" data-testid="lobby-error-dismiss" @click="lobby.clearError">知道了</button>
    </p>

    <div class="lobby__filterbar">
      <input
        v-model="query"
        type="search"
        class="lobby__search"
        data-testid="lobby-search"
        maxlength="20"
        placeholder="搜索房名、房主或对局玩家…"
        aria-label="搜索房间或对局"
      />
      <div class="lobby__seg" role="group" aria-label="大厅状态筛选">
        <button
          v-for="item in FILTERS"
          :key="item.value"
          type="button"
          class="lobby__seg-btn"
          :class="{ 'is-active': filter === item.value }"
          :aria-pressed="filter === item.value ? 'true' : 'false'"
          :data-testid="'lobby-filter-' + item.value"
          @click="filter = item.value"
        >
          {{ item.label }}
        </button>
      </div>
    </div>

    <div class="lobby__columns" :data-filter="filter">
      <section v-if="roomsVisible" class="lobby__panel lobby__panel--rooms" aria-label="房间列表">
        <div class="lobby__panel-head">
          <h2 class="lobby__panel-title">房间列表</h2>
          <span class="lobby__panel-meta">{{ lobby.rooms.length }} 间在等</span>
        </div>

        <div v-if="lobby.ownRoomId" class="lobby__own" data-testid="lobby-own-room">
          <div class="lobby__own-main">
            <b>我的房间</b>
            <span class="lobby__own-name">{{ lobby.ownRoomName || '未命名房间' }}</span>
            <code data-testid="lobby-own-room-id">{{ lobby.ownRoomId }}</code>
            <span>{{ lobby.ownRoomPublic ? '公开' : '私密' }} · 等待玩家加入</span>
          </div>
          <button type="button" class="button button--danger" data-testid="lobby-own-room-close" @click="closeOwnRoom">
            解散房间
          </button>
        </div>

        <ul class="lobby__list" data-testid="lobby-rooms">
          <li
            v-for="room in filteredRooms"
            :key="room.roomId"
            class="lobby__room"
            :class="{ 'is-full': !roomJoinable(room), 'is-own': room.roomId === lobby.ownRoomId }"
            :data-testid="'lobby-room-' + room.roomId"
          >
            <span class="lobby__room-main">
              <span class="lobby__room-state">{{ roomJoinable(room) ? '等待加入' : '已满' }}</span>
              <b class="lobby__room-name">{{ room.name }}</b>
              <span class="lobby__muted">房主 {{ room.host || '—' }}</span>
              <span class="lobby__muted">房号 {{ room.roomId }}</span>
            </span>
            <span class="lobby__room-seats">{{ roomSeatsText(room) }}</span>
            <button
              type="button"
              class="button button--small"
              :data-testid="'lobby-room-join-' + room.roomId"
              :disabled="!roomJoinable(room)"
              :title="roomJoinable(room) ? '加入这间房' : '这间房已经坐满了'"
              @click="joinRoom(room)"
            >
              加入
            </button>
            <button
              v-if="room.roomId === lobby.ownRoomId"
              type="button"
              class="button button--small button--danger"
              :data-testid="'lobby-room-close-' + room.roomId"
              @click="closeRoom(room.roomId)"
            >
              解散
            </button>
          </li>
        </ul>
        <p v-if="!filteredRooms.length" class="lobby__empty" data-testid="lobby-rooms-empty">{{ roomsEmpty }}</p>

        <div class="lobby__create">
          <input
            v-model="roomName"
            type="text"
            class="lobby__input"
            data-testid="lobby-room-name"
            maxlength="20"
            placeholder="房间名（可留空）"
            aria-label="房间名"
          />
          <label class="lobby__checkbox" title="取消勾选 = 私密房，只能凭房号加入">
            <input v-model="roomPublic" type="checkbox" data-testid="lobby-room-public" />
            公开
          </label>
          <button type="button" class="button" data-testid="lobby-create-room" @click="createRoom">创建房间</button>
        </div>
      </section>

      <section v-if="matchesVisible" class="lobby__panel lobby__panel--matches" aria-label="进行中的对局">
        <div class="lobby__panel-head">
          <h2 class="lobby__panel-title">进行中的对局</h2>
          <span class="lobby__panel-meta">{{ lobby.matches.length }} 局</span>
        </div>
        <ul class="lobby__list" data-testid="lobby-matches">
          <li
            v-for="match in filteredMatches"
            :key="match.roomId"
            class="lobby__match"
            :data-testid="'lobby-match-' + match.roomId"
          >
            <span class="lobby__match-main">
              <b class="lobby__match-name">{{ matchNamesText(match) }}</b>
              <span v-if="match.ranked" class="lobby__tag">排位</span>
              <span class="lobby__muted">第 {{ match.round }} 回合 · {{ matchSpectateText(match) }}</span>
            </span>
            <button
              type="button"
              class="button button--small"
              :data-testid="'lobby-match-spectate-' + match.roomId"
              @click="openSpectate(match)"
            >
              观战
            </button>
          </li>
        </ul>
        <p v-if="!filteredMatches.length" class="lobby__empty" data-testid="lobby-matches-empty">{{ matchesEmpty }}</p>
      </section>

      <section class="lobby__panel lobby__panel--players" aria-label="在线玩家">
        <div class="lobby__panel-head">
          <h2 class="lobby__panel-title">在线玩家</h2>
          <span class="lobby__panel-meta">{{ lobby.players.length }} 人</span>
        </div>
        <ul class="lobby__list" data-testid="lobby-players">
          <li
            v-for="player in lobby.players"
            :key="player.key"
            class="lobby__player"
            :class="{ 'is-me': isMePlayer(player.key) }"
            :data-testid="'lobby-player-' + player.key"
          >
            <span class="lobby__avatar" :style="avatarStyle(player.avatar)">{{ player.avatar ? '' : initial(player.name) }}</span>
            <span class="lobby__player-main">
              <span class="lobby__player-line">
                <span :class="playerNameClass(player.nameStyle)">{{ player.name }}</span>
                <span v-if="isMePlayer(player.key)" class="lobby__tag" data-testid="lobby-player-me">我</span>
                <span v-if="player.guest" class="lobby__tag lobby__tag--muted">游客</span>
                <span v-if="player.title" class="lobby__player-title">{{ player.title }}</span>
              </span>
              <span class="lobby__player-meta">
                <span>{{ levelText(player) }}</span>
                <span v-if="rankText(player)">{{ rankText(player) }}</span>
                <span class="lobby__status" :data-status="player.status">{{ statusText(player) }}</span>
              </span>
            </span>
          </li>
        </ul>
        <p v-if="!lobby.players.length" class="lobby__empty" data-testid="lobby-players-empty">当前没有在线玩家</p>
      </section>

      <section class="lobby__panel lobby__panel--friends" data-testid="lobby-friends" aria-label="好友邀战">
        <div class="lobby__panel-head">
          <h2 class="lobby__panel-title">好友邀战</h2>
          <button type="button" class="button button--small button--ghost" data-testid="lobby-friends-refresh" @click="loadFriends">
            刷新
          </button>
        </div>
        <p v-if="lobby.friendsGuest" class="lobby__empty" data-testid="lobby-friends-guest">登录后可以邀请好友对战。</p>
        <p v-else-if="lobby.friendsError" class="lobby__empty lobby__empty--error" data-testid="lobby-friends-error">{{ lobby.friendsError }}</p>
        <ul v-else-if="friendListVisible" class="lobby__list" data-testid="lobby-friend-list">
          <li
            v-for="friend in lobby.friends"
            :key="friend.userId"
            class="lobby__friend"
            :data-testid="'lobby-friend-' + friend.userId"
          >
            <span class="lobby__avatar lobby__avatar--small" :style="avatarStyle(friend.avatar)">{{ friend.avatar ? '' : initial(friend.username) }}</span>
            <span class="lobby__friend-main">
              <b>{{ friend.username || friend.userId }}</b>
              <span class="lobby__muted">{{ friendStatus(friend) }} · Lv.{{ friend.level }}</span>
            </span>
            <button
              type="button"
              class="button button--small"
              :data-testid="'lobby-friend-invite-' + friend.userId"
              :disabled="Boolean(inviteDisabledReason(friend)) || invitingUsername === friend.username"
              :title="friendInviteReason(friend)"
              @click="inviteFriend(friend)"
            >
              {{ invitingUsername === friend.username ? '邀战中…' : '邀战' }}
            </button>
          </li>
        </ul>
        <p v-if="friendListVisible && !lobby.friends.length" class="lobby__empty" data-testid="lobby-friends-empty">
          还没有好友。加好友后就能在这里直接邀战。
        </p>
        <p v-else-if="!lobby.friendsLoaded" class="lobby__empty">正在读取好友列表…</p>
      </section>

      <section class="lobby__panel lobby__panel--chat" aria-label="大厅公屏">
        <div class="lobby__panel-head">
          <h2 class="lobby__panel-title">大厅公屏</h2>
          <span class="lobby__panel-meta">{{ lobby.chat.length }} 条</span>
        </div>
        <div ref="chatEl" class="lobby__chat" data-testid="lobby-chat" role="log" aria-live="polite">
          <div
            v-for="item in lobby.chat"
            :key="chatKey(item.seq, item.key, item.ts)"
            class="lobby__chat-item"
            :class="{ 'is-me': isMineChat(item.key) }"
            :data-testid="'lobby-chat-message-' + chatKey(item.seq, item.key, item.ts)"
          >
            <span class="lobby__chat-time">{{ timeText(item.ts) }}</span>
            <span class="lobby__chat-name">{{ item.name }}：</span>
            <span class="lobby__chat-text">{{ item.message }}</span>
          </div>
          <p v-if="!lobby.chat.length" class="lobby__empty" data-testid="lobby-chat-empty">还没有人说话，打个招呼吧。</p>
        </div>
        <div class="lobby__chat-row">
          <input
            v-model="chatDraft"
            type="text"
            class="lobby__input"
            data-testid="lobby-chat-input"
            maxlength="120"
            placeholder="说点什么…"
            aria-label="大厅聊天输入"
            @keydown.enter.prevent="sendChat"
          />
          <button type="button" class="button" data-testid="lobby-chat-send" @click="sendChat">发送</button>
        </div>
      </section>
    </div>

    <div v-if="lobby.activeInvite" class="lobby__invite" data-testid="lobby-invite-banner" role="status">
      <span class="lobby__invite-text">
        <b>{{ lobby.activeInvite.fromUsername }}</b> 邀请你加入房间
        <code>{{ lobby.activeInvite.roomId }}</code>
      </span>
      <button type="button" class="button" data-testid="lobby-invite-accept" :disabled="acceptingInvite" @click="acceptInvite">
        进入房间
      </button>
      <button type="button" class="button button--ghost" data-testid="lobby-invite-dismiss" @click="dismissInvite">
        忽略
      </button>
    </div>

    <footer class="lobby__actions">
      <button
        type="button"
        class="button"
        data-testid="lobby-match-casual"
        :disabled="lobby.queueMode === 'casual'"
        @click="startMatch('casual')"
      >
        快速匹配
      </button>
      <button
        type="button"
        class="button button--ghost"
        data-testid="lobby-match-ranked"
        :disabled="lobby.queueMode === 'ranked'"
        @click="startMatch('ranked')"
      >
        排位匹配
      </button>
      <button v-if="lobby.queueMode" type="button" class="button button--ghost" data-testid="lobby-match-cancel" @click="cancelMatch">
        取消匹配
      </button>
      <button type="button" class="button button--ghost" data-testid="lobby-back-home" @click="backHome">返回首页</button>
    </footer>
  </section>
</template>

<style scoped>
.lobby {
  gap: 12px;
}

.lobby__head {
  display: flex;
  flex-wrap: wrap;
  gap: 10px 18px;
  align-items: flex-start;
  justify-content: space-between;
}

.lobby__title-block {
  min-width: 0;
}

.lobby__eyebrow {
  margin: 0 0 4px;
  color: var(--accent);
  font-size: 12px;
  letter-spacing: 0.12em;
  text-transform: uppercase;
}

.lobby__title {
  margin: 0;
  font-size: 28px;
}

.lobby__hint {
  margin: 4px 0 0;
  max-width: 62ch;
  color: var(--text-muted);
  font-size: 13px;
}

.lobby__topbar {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px 10px;
}

.lobby__stat {
  padding: 3px 8px;
  border: 1px solid var(--border);
  border-radius: 999px;
  color: var(--text-muted);
  font-size: 12px;
  white-space: nowrap;
}

.lobby__stat b {
  color: var(--text);
  font-variant-numeric: tabular-nums;
}

.lobby__queue {
  color: var(--accent);
  font-size: 12px;
}

.lobby__notice,
.lobby__error {
  margin: 0;
  padding: 7px 10px;
  border: 1px solid var(--border);
  border-radius: 8px;
  font-size: 13px;
}

.lobby__notice {
  color: var(--accent);
  background: #0f2b34;
}

.lobby__error {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
  color: #ffb4a8;
  background: #2a1414;
  border-color: #6a2a2a;
}

.lobby__dismiss {
  margin-left: auto;
  padding: 2px 8px;
  border: 1px solid #6a2a2a;
  border-radius: 6px;
  background: transparent;
  color: inherit;
  font: inherit;
  font-size: 12px;
  cursor: pointer;
}

.lobby__filterbar {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
}

.lobby__search,
.lobby__input {
  min-width: 0;
  padding: 7px 10px;
  border: 1px solid var(--border);
  border-radius: 8px;
  background: #0b1a24;
  color: var(--text);
  font: inherit;
}

.lobby__search {
  flex: 1 1 210px;
}

.lobby__seg {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
}

.lobby__seg-btn {
  padding: 6px 11px;
  border: 1px solid var(--border);
  border-radius: 999px;
  background: transparent;
  color: var(--text-muted);
  font: inherit;
  font-size: 13px;
  cursor: pointer;
}

.lobby__seg-btn.is-active {
  border-color: var(--accent-strong);
  background: #0f3a47;
  color: var(--text);
}

.lobby__columns {
  display: grid;
  grid-template-columns: minmax(0, 1fr);
  gap: 12px;
}

.lobby__panel {
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 12px;
  border: 1px solid var(--border);
  border-radius: var(--radius);
  background: var(--bg-elevated);
}

.lobby__panel-head {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}

.lobby__panel-title {
  margin: 0;
  color: var(--text-muted);
  font-size: 11px;
  font-weight: 600;
  letter-spacing: 0.2em;
}

.lobby__panel-meta {
  color: var(--text-muted);
  font-size: 11px;
  font-variant-numeric: tabular-nums;
}

.lobby__list {
  display: flex;
  flex-direction: column;
  gap: 6px;
  max-height: 280px;
  margin: 0;
  padding: 0;
  overflow-y: auto;
  list-style: none;
}

.lobby__player,
.lobby__room,
.lobby__match,
.lobby__friend {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
  padding: 7px 8px;
  border: 1px solid transparent;
  border-radius: 8px;
  background: #0b1a24;
}

.lobby__player.is-me {
  border-color: var(--accent-strong);
}

.lobby__avatar {
  display: grid;
  flex: none;
  place-items: center;
  width: 32px;
  height: 32px;
  border-radius: 50%;
  background-color: #14303f;
  background-position: center;
  background-size: cover;
  color: var(--accent);
  font-size: 14px;
  font-weight: 700;
}

.lobby__avatar--small {
  width: 26px;
  height: 26px;
  font-size: 12px;
}

.lobby__player-main,
.lobby__friend-main,
.lobby__room-main,
.lobby__match-main {
  display: flex;
  flex: 1;
  flex-wrap: wrap;
  align-items: center;
  gap: 2px 8px;
  min-width: 0;
}

.lobby__friend-main {
  flex-direction: column;
  align-items: flex-start;
  gap: 0;
}

.lobby__player-line {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 5px;
  min-width: 0;
}

.lobby__player-name {
  overflow-wrap: anywhere;
}

.lobby__player-name--rainbow {
  background: linear-gradient(90deg, #7ee8fa, #ffd76a, #ff8a7a, #7ee8fa);
  background-clip: text;
  color: transparent;
}

.lobby__player-meta {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px;
  color: var(--text-muted);
  font-size: 12px;
}

.lobby__player-title {
  color: #ffd76a;
  font-size: 11px;
}

.lobby__tag {
  padding: 1px 6px;
  border: 1px solid var(--accent-strong);
  border-radius: 999px;
  color: var(--accent);
  font-size: 10px;
}

.lobby__tag--muted {
  border-color: var(--border);
  color: var(--text-muted);
}

.lobby__status[data-status='idle'] {
  color: #9ad7b0;
}

.lobby__status[data-status='matching'] {
  color: #ffd76a;
}

.lobby__status[data-status='in_room'] {
  color: var(--accent);
}

.lobby__status[data-status='in_game'] {
  color: #ff9d8f;
}

.lobby__room-seats {
  flex: none;
  color: var(--text-muted);
  font-size: 12px;
  font-variant-numeric: tabular-nums;
}

.lobby__room-name,
.lobby__match-name {
  overflow-wrap: anywhere;
}

.lobby__room.is-full {
  opacity: 0.72;
}

.lobby__room.is-own {
  border-color: #3d6b4c;
}

.lobby__muted {
  color: var(--text-muted);
  font-size: 12px;
}

.lobby__empty {
  margin: 0;
  padding: 10px;
  border: 1px dashed var(--border);
  border-radius: 8px;
  color: var(--text-muted);
  font-size: 12px;
}

.lobby__empty--error {
  color: #ffb4a8;
}

.lobby__own {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
  padding: 8px 10px;
  border: 1px solid #3d6b4c;
  border-radius: 8px;
  background: #0c2118;
}

.lobby__own-main {
  display: flex;
  flex: 1;
  flex-wrap: wrap;
  align-items: center;
  gap: 4px 8px;
  min-width: 0;
  font-size: 12px;
}

.lobby__own-name {
  font-weight: 700;
}

.lobby__own code,
.lobby__invite code {
  padding: 1px 5px;
  border: 1px solid var(--border);
  border-radius: 5px;
}

.lobby__create {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
}

.lobby__create .lobby__input {
  flex: 1 1 150px;
}

.lobby__checkbox {
  display: flex;
  align-items: center;
  gap: 5px;
  color: var(--text-muted);
  font-size: 12px;
  white-space: nowrap;
}

.lobby__chat {
  display: flex;
  flex-direction: column;
  gap: 4px;
  min-height: 120px;
  max-height: 300px;
  overflow-y: auto;
  padding: 8px;
  border: 1px solid var(--border);
  border-radius: 8px;
  background: #08141c;
}

.lobby__chat-item {
  display: flex;
  flex-wrap: wrap;
  gap: 2px 6px;
  color: var(--text);
  font-size: 13px;
}

.lobby__chat-item.is-me .lobby__chat-name {
  color: var(--accent);
}

.lobby__chat-time {
  color: var(--text-muted);
  font-size: 11px;
  font-variant-numeric: tabular-nums;
}

.lobby__chat-name {
  color: #ffd76a;
  font-size: 12px;
}

.lobby__chat-text {
  overflow-wrap: anywhere;
}

.lobby__chat-row {
  display: flex;
  gap: 8px;
}

.lobby__chat-row .lobby__input {
  flex: 1;
}

.lobby__invite {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
  padding: 9px 12px;
  border: 1px solid #3d6b4c;
  border-radius: 8px;
  background: #0c2118;
}

.lobby__invite-text {
  flex: 1 1 240px;
  min-width: 0;
  font-size: 13px;
}

.lobby__actions {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: auto;
  padding-top: 4px;
}

.button--small {
  padding: 4px 9px;
  font-size: 12px;
}

.button--ghost {
  border-color: var(--border);
  background: transparent;
  color: var(--text-muted);
}

.button--ghost:hover {
  background: #14303f;
  color: var(--text);
}

.button--danger {
  border-color: #6a2a2a;
  background: #2a1414;
  color: #ffb4a8;
}

.button--danger:hover {
  background: #3a1b1b;
}

.button:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

@media (min-width: 980px) {
  .lobby__columns {
    grid-template-columns: minmax(0, 1.45fr) minmax(0, 1fr) minmax(0, 1.05fr);
  }

  .lobby__panel--rooms {
    grid-column: 1;
    grid-row: 1;
  }

  .lobby__panel--matches {
    grid-column: 1;
    grid-row: 2;
  }

  .lobby__panel--players {
    grid-column: 2;
    grid-row: 1;
  }

  .lobby__panel--friends {
    grid-column: 2;
    grid-row: 2;
  }

  .lobby__panel--chat {
    grid-column: 3;
    grid-row: 1 / span 2;
  }

  .lobby__columns[data-filter='watchable'] .lobby__panel--matches {
    grid-row: 1 / span 2;
  }

  .lobby__columns[data-filter='joinable'] .lobby__panel--rooms,
  .lobby__columns[data-filter='full'] .lobby__panel--rooms {
    grid-row: 1 / span 2;
  }
}

@media (max-width: 520px) {
  .lobby__title {
    font-size: 23px;
  }

  .lobby__list,
  .lobby__chat {
    max-height: 240px;
  }

  .lobby__room,
  .lobby__match {
    flex-wrap: wrap;
  }
}
</style>