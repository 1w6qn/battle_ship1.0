<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { acquireMatchChannel, emitMatchEvent, matchSocket } from '../../realtime/match'
import { useGameStore } from '../../stores/game'
import { BOARD_SIZE, usePlacementStore } from '../../stores/placement'

/**
 * Ticket #23: the opening placement screen.
 *
 * Data flow (port map 14 section 1.4):
 *   game_state / room_sync -> useGameStore (state, room, names, ships)
 *   reset_gameboard        -> usePlacementStore.applyReset (new_max_ships)
 *   clicks                 -> usePlacementStore draft cells
 *   confirm                -> place_ships ack -> submitted | verbatim rejection
 *   game_state{rock_paper_scissors} -> /rps (route name is frozen by #21)
 *
 * The screen never decides legality: it only counts the six single-cell ships
 * the legacy screen counted (the server validates the submission).
 */
const router = useRouter()
const route = useRoute()
const game = useGameStore()
const placement = usePlacementStore()

let releaseChannel: (() => void) | null = null
let offError: (() => void) | null = null
let offMessage: (() => void) | null = null
let submitToken = 0

const hasRoom = computed(() => Boolean(game.state.room_id))
const selfName = computed(() => game.state.player_name || '你')
const opponentName = computed(() => game.state.opponent_name || '对手')
const seatLabel = computed(() => game.state.player_seat || '—')
const canEdit = computed(() => hasRoom.value && !placement.locked)

interface BoardCellView {
  key: string
  x: number
  y: number
  ship: boolean
}

const boardCells = computed<BoardCellView[]>(() => {
  const cells: BoardCellView[] = []
  for (let y = 0; y < BOARD_SIZE; y += 1) {
    for (let x = 0; x < BOARD_SIZE; x += 1) {
      cells.push({ key: x + '-' + y, x, y, ship: placement.isPlaced(x, y) })
    }
  }
  return cells
})

const emptySlots = computed(() => {
  const missing = Math.max(0, placement.maxShips - placement.placedCount)
  return Array.from({ length: missing }, (_, index) => index)
})

function readText(payload: Record<string, unknown>, key: string): string {
  const value = payload[key]
  return typeof value === 'string' ? value : ''
}

function routeForState(state: string): void {
  if (route.name !== 'placement') return
  if (state === 'rock_paper_scissors') {
    void router.push({ name: 'rps' })
  } else if (state === 'attacking') {
    // A mid-game redeploy (回光返照 / 灵气复苏 / 败者食尘) sets room.state back
    // to placing_ships while the client may still see attacking; resetPhase
    // keeps this screen mounted until the server accepts the new board.
    if (!placement.resetPhase) void router.push({ name: 'game' })
  } else if (state === 'game_over') {
    void router.push({ name: 'game-over' })
  }
}

onMounted(() => {
  releaseChannel = acquireMatchChannel()
  const socket = matchSocket()
  if (socket) {
    offError = socket.on('error', (payload) => placement.noteNotice(readText(payload, 'message')))
    offMessage = socket.on('message', (payload) => placement.noteNotice(readText(payload, 'message')))
  }
  placement.resetForEntry()
  if (game.state.state === 'placing_ships') placement.adoptFromServer(game.state.ships)
})

onBeforeUnmount(() => {
  offError?.()
  offMessage?.()
  offError = null
  offMessage = null
  releaseChannel?.()
  releaseChannel = null
})

watch(
  () => game.state.ships,
  (ships) => {
    if (game.state.state !== 'placing_ships') return
    if (placement.pending) return
    placement.adoptFromServer(ships)
  },
  { deep: true },
)

watch(
  () => game.state.state,
  (state) => routeForState(state),
  { immediate: true },
)

function randomize(): void {
  placement.randomize()
}

function clearBoard(): void {
  placement.clearBoard()
}

async function confirm(): Promise<void> {
  if (!canEdit.value || !placement.canSubmit) return
  const socket = matchSocket()
  if (!socket || !socket.socket.connected) {
    placement.noteNotice('连接已断开，正在重连。稍后会自动同步房间状态，再试一次即可。')
    return
  }
  const roomId = game.state.room_id
  const playerId = game.state.player_id
  if (!roomId || !playerId) {
    placement.noteNotice('还没进入房间，请重新创建或加入房间。')
    return
  }
  const token = ++submitToken
  placement.beginPending()
  const ships = placement.cells.map((cell) => ({ positions: [{ x: cell.x, y: cell.y }] }))
  try {
    const ack = await emitMatchEvent(socket, 'place_ships', {
      room_id: roomId,
      player_id: playerId,
      ships,
    })
    if (token !== submitToken || !placement.pending) return
    placement.settleSubmit(ack?.status === 'success', typeof ack?.message === 'string' ? ack.message : '')
  } catch (error) {
    if (token !== submitToken || !placement.pending) return
    placement.settleSubmit(false, error instanceof Error ? error.message : '')
  }
}

function returnHome(): void {
  void router.push({ name: 'start' })
}
</script>

<template>
  <section
    class="screen placement"
    data-screen="placement"
    data-testid="screen-placement"
    aria-labelledby="screen-placement-title"
  >
    <header class="placement__head">
      <p class="placement__eyebrow">P4 · 布船</p>
      <h1 id="screen-placement-title" class="placement__title" data-testid="placement-heading">
        放置你的战舰
      </h1>
      <p class="placement__lead">6×6 棋盘各放 1 格，共 6 格 · 再点一次可取消</p>
    </header>

    <div class="placement__players">
      <span class="placement__player">你 <b data-testid="placement-self">{{ selfName }}</b></span>
      <span class="placement__seat" aria-label="座位">{{ seatLabel }}</span>
      <span class="placement__vs" aria-hidden="true">VS</span>
      <span class="placement__player placement__player--opponent">
        对手 <b data-testid="placement-opponent">{{ opponentName }}</b>
      </span>
    </div>

    <p v-if="!hasRoom" class="placement__empty" data-testid="placement-empty" role="status">
      还没进入房间，先创建或加入房间再布船。
    </p>

    <div class="placement__layout">
      <div class="placement__board-wrap">
        <div
          class="placement__board"
          data-testid="placement-board"
          role="grid"
          aria-label="布船棋盘，共 36 格"
        >
          <button
            v-for="cell in boardCells"
            :key="cell.key"
            type="button"
            class="placement__cell"
            :class="{ 'is-ship': cell.ship }"
            role="gridcell"
            :data-testid="'placement-cell-' + cell.x + '-' + cell.y"
            :aria-pressed="cell.ship ? 'true' : 'false'"
            :aria-label="
              '第 ' + (cell.x + 1) + ' 列第 ' + (cell.y + 1) + ' 行，' +
              (cell.ship ? '已放置战舰，点击撤销' : '空格，点击放置战舰')
            "
            :disabled="!canEdit"
            @click="placement.toggleCell(cell.x, cell.y)"
          >
            <span v-if="cell.ship" class="placement__mark" aria-hidden="true">◆</span>
          </button>
        </div>
      </div>

      <aside class="placement__side" aria-label="布船状态与操作">
        <p class="placement__count">
          已放置
          <b data-testid="placement-count">{{ placement.placedCount }}</b>
          <span class="placement__slash" aria-hidden="true">/</span>
          <span data-testid="placement-total">{{ placement.total }}</span>
        </p>

        <ol class="placement__ships" data-testid="placement-ships" aria-label="已放置的战舰格">
          <li
            v-for="cell in placement.cells"
            :key="cell.x + '-' + cell.y"
            class="placement__ship"
            :data-testid="'placement-ship-' + cell.x + '-' + cell.y"
          >
            {{ cell.x + 1 }},{{ cell.y + 1 }}
          </li>
          <li
            v-for="slot in emptySlots"
            :key="'empty-' + slot"
            class="placement__ship placement__ship--empty"
            aria-hidden="true"
          >
            空
          </li>
        </ol>

        <p
          v-if="placement.submitted"
          class="placement__submitted"
          data-testid="placement-submitted"
          role="status"
        >
          已提交
        </p>

        <p class="placement__hint" data-testid="placement-hint" role="status" aria-live="polite">
          {{ placement.hint }}
        </p>

        <p
          v-if="placement.pending"
          class="placement__pending"
          data-testid="placement-pending"
          role="status"
          aria-live="polite"
        >
          正在提交，等待服务器回执…
          <b data-testid="placement-pending-countdown">{{ placement.countdown }}s</b>
        </p>

        <p
          v-if="placement.error"
          class="placement__error"
          data-testid="placement-error"
          role="alert"
        >
          {{ placement.error }}
        </p>

        <p
          v-if="placement.resetMessage"
          class="placement__reset"
          data-testid="placement-reset-note"
          role="status"
        >
          {{ placement.resetMessage }}
        </p>

        <div class="placement__actions">
          <button
            type="button"
            class="button button--ghost"
            data-testid="placement-clear"
            :disabled="!canEdit || placement.placedCount === 0"
            @click="clearBoard"
          >
            清空
          </button>
          <button
            type="button"
            class="button button--ghost"
            data-testid="placement-random"
            :disabled="!canEdit"
            @click="randomize"
          >
            随机摆放
          </button>
          <button
            type="button"
            class="button"
            data-testid="placement-confirm"
            :disabled="!canEdit || !placement.canSubmit"
            @click="confirm"
          >
            确认放置
          </button>
          <button
            v-if="!hasRoom"
            type="button"
            class="button button--ghost"
            data-testid="placement-return-home"
            @click="returnHome"
          >
            返回首页
          </button>
        </div>
      </aside>
    </div>
  </section>
</template>

<style scoped>
.placement {
  gap: 10px;
}

.placement__head {
  display: grid;
  gap: 2px;
}

.placement__eyebrow {
  margin: 0;
  color: var(--accent);
  font-size: 12px;
  letter-spacing: 0.12em;
  text-transform: uppercase;
}

.placement__title {
  margin: 0;
  font-size: 26px;
}

.placement__lead {
  margin: 2px 0 0;
  color: var(--text-muted);
  font-size: 13px;
}

.placement__players {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px 14px;
  padding: 8px 14px;
  border: 1px solid var(--border);
  border-radius: var(--radius);
  background: var(--bg-elevated);
  font-size: 14px;
}

.placement__player--opponent {
  margin-left: auto;
}

.placement__seat {
  padding: 1px 8px;
  border: 1px solid var(--border);
  border-radius: 999px;
  color: var(--text-muted);
  font-size: 12px;
}

.placement__vs {
  color: var(--text-muted);
  font-size: 11px;
  letter-spacing: 0.12em;
}

.placement__empty {
  margin: 0;
  padding: 10px 14px;
  border: 1px dashed var(--border);
  border-radius: var(--radius);
  color: var(--text-muted);
  font-size: 13px;
}

.placement__layout {
  display: grid;
  grid-template-columns: max-content minmax(220px, 280px);
  gap: 14px;
  justify-content: center;
  align-items: start;
}

.placement__board-wrap {
  display: flex;
  justify-content: center;
  padding: 12px;
  border: 1px solid var(--border);
  border-radius: var(--radius);
  background: linear-gradient(160deg, #0d2230, #0a1a24 75%);
}

.placement__board {
  display: grid;
  grid-template-columns: repeat(6, var(--placement-cell));
  grid-auto-rows: var(--placement-cell);
  gap: 4px;
  --placement-cell: clamp(40px, min(11vw, 7vh), 56px);
}

.placement__cell {
  display: grid;
  place-items: center;
  padding: 0;
  border: 1px solid #24485c;
  border-radius: 7px;
  background: #0b1a24;
  color: var(--accent);
  font: inherit;
  cursor: pointer;
  transition: transform 120ms ease, background 120ms ease, border-color 120ms ease;
}

.placement__cell:hover:not(:disabled) {
  border-color: var(--accent);
  background: #113140;
}

.placement__cell:disabled {
  cursor: default;
  opacity: 0.62;
}

.placement__cell.is-ship {
  border-color: #3fb3cf;
  background: linear-gradient(160deg, #1c5f78, #14414f);
  box-shadow: inset 0 0 0 1px rgb(120 220 240 / 30%);
}

.placement__mark {
  font-size: 18px;
  line-height: 1;
}

.placement__side {
  display: grid;
  gap: 10px;
  padding: 14px;
  border: 1px solid var(--border);
  border-radius: var(--radius);
  background: var(--bg-elevated);
}

.placement__count {
  margin: 0;
  color: var(--text-muted);
  font-size: 13px;
}

.placement__count b {
  color: var(--text);
  font-size: 20px;
  font-variant-numeric: tabular-nums;
}

.placement__slash {
  margin: 0 2px;
  color: var(--text-muted);
}

.placement__ships {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  min-height: 30px;
  margin: 0;
  padding: 0;
  list-style: none;
}

.placement__ship {
  padding: 3px 8px;
  border: 1px solid #2b5568;
  border-radius: 6px;
  background: #0b1a24;
  color: var(--text);
  font-size: 12px;
  font-variant-numeric: tabular-nums;
}

.placement__ship--empty {
  border-style: dashed;
  color: var(--text-muted);
}

.placement__submitted {
  margin: 0;
  padding: 4px 10px;
  justify-self: start;
  border: 1px solid #2a8f68;
  border-radius: 999px;
  background: rgb(42 143 104 / 18%);
  color: #6fe0a0;
  font-size: 12px;
}

.placement__hint {
  margin: 0;
  color: var(--text-muted);
  font-size: 13px;
}

.placement__pending {
  margin: 0;
  padding: 6px 10px;
  border: 1px solid #2a5568;
  border-radius: 8px;
  background: #0b1a24;
  color: var(--accent);
  font-size: 13px;
}

.placement__pending b {
  font-variant-numeric: tabular-nums;
}

.placement__error {
  margin: 0;
  padding: 6px 10px;
  border: 1px solid #7a2f2a;
  border-radius: 8px;
  background: #2a1414;
  color: #ff9c8f;
  font-size: 13px;
}

.placement__reset {
  margin: 0;
  padding: 6px 10px;
  border: 1px dashed #7a6a2a;
  border-radius: 8px;
  background: #241f10;
  color: #ffd76a;
  font-size: 13px;
}

.placement__actions {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.button--ghost {
  border-color: var(--border);
  background: transparent;
  color: var(--text-muted);
}

.button--ghost:hover:not(:disabled) {
  background: #14303f;
  color: var(--text);
}

.button:disabled {
  cursor: not-allowed;
  opacity: 0.5;
}

@media (max-width: 760px) {
  .placement {
    gap: 6px;
    padding: 10px;
  }

  .placement__title {
    font-size: 22px;
  }

  .placement__lead {
    font-size: 12px;
  }

  .placement__layout {
    grid-template-columns: minmax(0, 1fr);
    gap: 10px;
  }

  .placement__board-wrap {
    padding: 10px;
  }

  .placement__side {
    padding: 10px;
    gap: 6px;
  }

  .placement__board {
    --placement-cell: clamp(40px, min(12.5vw, 7.2vh), 54px);
  }

  .placement__players {
    padding: 6px 10px;
    font-size: 13px;
  }

  .placement__actions .button {
    flex: 1 1 auto;
  }
}

@media (max-height: 720px) {
  .placement__eyebrow,
  .placement__lead {
    display: none;
  }

  .placement__title {
    font-size: 20px;
  }

  .placement__board {
    --placement-cell: clamp(40px, 6.6vh, 48px);
  }

  .placement__side {
    gap: 6px;
  }
}
</style>
