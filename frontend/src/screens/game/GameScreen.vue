<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import BoardPanel from './BoardPanel.vue'
import { acquireBattleChannel, sendBattleEvent } from '../../realtime/battle'
import { cardArtUrl } from '../../cards/cardArt'
import { useGameStore } from '../../stores/game'
import { useMatchStore } from '../../stores/match'
import { useResultStore } from '../../stores/result'
import {
  areaFromAnchor,
  areaCells,
  buildOpponentBoard,
  buildSelfBoard,
  cardDisabledReason,
  cardSpeed,
  cardTestId,
  cardIdentity,
  chainCardTestId,
  chainItems,
  continuousLine,
  effectBadgeList,
  frozenAreaCells,
  hitCount,
  isMyTurn,
  lineFromCell,
  modeLabel,
  opponentId,
  phaseLabel,
  playRefusalReason,
  remainingShipText,
  speedGems,
  targetDescriptor,
  turnText,
  type CardLike,
  type Point,
  type TargetDescriptor,
  type PendingPickLike,
  type PlayabilityContext,
  type FrozenAreaLike,
} from './view'

/**
 * Ticket #27: the game screen (P4).
 *
 * Data comes only from the Pinia stores, and the stores are only fed by the
 * real socket frames (settlement channel + battle frames). The screen formats
 * server values; it never recomputes attack counts, ship survival or card
 * legality. Card graying/hints follow the frozen legacy client rules (D10) so
 * the UI keeps telling the player the same thing it did before the rewrite.
 *
 * The settlement channel is acquired on mount: that is what makes a game_over
 * emitted while this screen is mounted land in the result store, and it is why
 * the screen can hand over to /game-over without a reload.
 */
const router = useRouter()
const game = useGameStore()
const match = useMatchStore()
const result = useResultStore()

let releaseChannel: (() => void) | null = null
let ticker: number | null = null
const now = ref(Date.now())

onMounted(() => {
  releaseChannel = acquireBattleChannel()
  seenGameOverAt = result.gameOver ? result.gameOver.receivedAt : 0
  seenRoom = state.value.room_id
  ticker = window.setInterval(() => {
    now.value = Date.now()
  }, 250)
  void loadQuickChatCatalog()
  if (mq) mq.addEventListener('change', syncCompact)
  syncCompact()
})

onBeforeUnmount(() => {
  releaseChannel?.()
  releaseChannel = null
  if (ticker !== null) window.clearInterval(ticker)
  ticker = null
  if (chainSafety !== null) window.clearTimeout(chainSafety)
  if (mq) mq.removeEventListener('change', syncCompact)
})

const state = computed(() => game.state)
const hand = computed<CardLike[]>(() =>
  Array.isArray(state.value.hand) ? (state.value.hand as unknown as CardLike[]) : [],
)
const selfName = computed(() => state.value.player_name || '你')
const opponentName = computed(() => state.value.opponent_name || '对手')
const myTurn = computed(() => isMyTurn(state.value))
const phaseText = computed(() => phaseLabel(state.value.current_phase))
const modeText = computed(() => modeLabel(Boolean(state.value.ranked), state.value.mode))
const fieldMagic = computed(() => state.value.field_magic || '无')
const hasRoom = computed(() => Boolean(state.value.room_id))
const turnLabel = computed(() => turnText(state.value, selfName.value, opponentName.value))

const selectedCardIndex = ref(-1)
const selectedCardKey = ref('')
const noticeText = ref('')

// 仁王之盾 waits for the server's chain_resolved frame; only then may the
// player pick up to three own ships (legacy showRenwangChoice).
const shieldPicks = ref<number[]>([])
const shieldError = ref('')
const shieldOpen = computed(() => Boolean(match.shieldChoice))
const shieldSelectedKeys = computed<string[]>(() => {
  const ships = Array.isArray(state.value.ships) ? state.value.ships : []
  const keys: string[] = []
  for (const index of shieldPicks.value) {
    const ship = ships[index]
    for (const position of Array.isArray(ship?.positions) ? ship.positions : []) {
      keys.push(position.x + '-' + position.y)
    }
  }
  return keys
})

interface SelectionState {
  card: CardLike
  index: number
  descriptor: TargetDescriptor
  board: 'self' | 'opponent' | null
  anchor: Point | null
  lineDir: 'row' | 'col'
  picks: Point[]
  effectChoice: number | null
  error: string
}

const selection = ref<SelectionState | null>(null)
const chainBusy = computed(
  () => Boolean(state.value.chain_waiting) || chainItems(state.value.chain).length > 0,
)
const pendingPick = computed<PendingPickLike | null>(() => {
  if (match.pickRequest) {
    return { reason: match.pickRequest.reason, message: match.pickRequest.message }
  }
  const fallback = state.value.pending_sacrifice
  if (fallback && typeof fallback === 'object') {
    const record = fallback as Record<string, unknown>
    return { reason: String(record.reason ?? ''), message: String(record.message ?? '') }
  }
  return null
})
const playCtx = computed<PlayabilityContext>(() => ({
  lastAttack: match.lastAttack,
  pendingPick: pendingPick.value,
  chainBusy: chainBusy.value,
}))

const selfCells = computed(() =>
  buildSelfBoard(state.value, { shieldBroken: match.shieldBrokenSelf }),
)
const opponentCells = computed(() =>
  buildOpponentBoard(state.value, {
    revealed: match.revealed,
    shieldBroken: match.shieldBrokenOpponent,
  }),
)

const previewKeys = computed<string[]>(() => {
  const sel = selection.value
  if (!sel || !sel.anchor) return []
  const descriptor = sel.descriptor
  if (descriptor.kind === 'area' || descriptor.kind === 'shenwei') {
    return areaCells(areaFromAnchor(sel.anchor.x, sel.anchor.y, descriptor.size ?? 3))
  }
  if (descriptor.kind === 'line') {
    return areaCells(lineFromCell(sel.anchor.x, sel.anchor.y, sel.lineDir))
  }
  return []
})

const selectedKeys = computed<string[]>(() => (selection.value ? selection.value.picks.map((p) => p.x + '-' + p.y) : []))

const canConfirm = computed(() => {
  const sel = selection.value
  if (!sel) return false
  if (sel.error) return false
  const kind = sel.descriptor.kind
  if (kind === 'area' || kind === 'line') return sel.anchor !== null
  if (kind === 'continuous') return continuousLine(sel.picks) !== null
  if (kind === 'single') return sel.picks.length === 1
  if (kind === 'own_ships') return sel.picks.length === 2 && sel.effectChoice !== null
  if (kind === 'shenwei') return sel.board !== null && sel.anchor !== null
  return false
})

const pickCountText = computed(() => {
  const sel = selection.value
  if (!sel) return ''
  const kind = sel.descriptor.kind
  if (kind === 'continuous') return String(sel.picks.length) + ' / ' + String(sel.descriptor.length ?? 6)
  if (kind === 'own_ships') return String(sel.picks.length) + ' / ' + String(sel.descriptor.count ?? 2)
  if (kind === 'single') return sel.picks.length ? '已选中 1 格' : '尚未选中'
  if (kind === 'area' || kind === 'line' || kind === 'shenwei') {
    if (!sel.anchor) return '尚未选中'
    if (kind === 'line') {
      return (sel.lineDir === 'row' ? '第 ' : '第 ') + String((sel.lineDir === 'row' ? sel.anchor.y : sel.anchor.x) + 1) + (sel.lineDir === 'row' ? ' 行' : ' 列')
    }
    return '第 ' + String(sel.anchor.x + 1) + '-' + String(sel.anchor.x + (sel.descriptor.size ?? 3)) + ' 列，第 ' + String(sel.anchor.y + 1) + '-' + String(sel.anchor.y + (sel.descriptor.size ?? 3)) + ' 行'
  }
  return ''
})

const targetTitle = computed(() => {
  const sel = selection.value
  if (!sel) return ''
  return '使用「' + sel.card.name + '」：请选择目标'
})

const targetHint = computed(() => {
  const sel = selection.value
  if (!sel) return ''
  const kind = sel.descriptor.kind
  if (kind === 'area') return '在对手海域点击一个格子，确定 ' + String(sel.descriptor.size ?? 3) + '×' + String(sel.descriptor.size ?? 3) + ' 区域的左上角'
  if (kind === 'line') return '选择行或列，再在对手海域点击一个格子'
  if (kind === 'continuous') return '依次点击 6 个连续格子（正好一整行或一整列）'
  if (kind === 'single') return '在自己海域点击一艘还活着的战舰'
  if (kind === 'own_ships') return '在自己海域选择两艘战舰，然后选择要发动的效果'
  if (kind === 'shenwei') return '先选择作用棋盘，再点击 3×3 区域的左上角'
  return ''
})

const chainList = computed(() => chainItems(state.value.chain))
const selfEffects = computed(() => effectBadgeList(state.value.effect_badges?.self))
const opponentEffects = computed(() => effectBadgeList(state.value.effect_badges?.opponent))
const frozenMine = computed(() =>
  frozenAreaCells(state.value.frozen_area as unknown as FrozenAreaLike | null, state.value.player_id),
)
const frozenTheirs = computed(() =>
  frozenAreaCells(state.value.frozen_area as unknown as FrozenAreaLike | null, opponentId(state.value)),
)

const hits = computed(() => hitCount(Array.isArray(state.value.attacks) ? state.value.attacks : []))
const shots = computed(() => (Array.isArray(state.value.attacks) ? state.value.attacks.length : 0))
const shipsText = computed(() => remainingShipText(state.value))

const chainWindow = computed(() => match.chainWindow)
const speed3Hand = computed<CardLike[]>(() => chainWindow.value?.speed3Cards ?? [])
const chainRemaining = computed(() => {
  const window = chainWindow.value
  if (!window) return 0
  return Math.max(0, Math.ceil(window.countdown - (now.value - window.openedAt) / 1000))
})

const logs = computed(() => match.logs.slice().reverse())
const notices = computed(() => match.notices.slice(-4))
const quickChatMessages = computed(() => match.quickChat.slice(-8).reverse())
const chatMessages = computed(() => match.chat.slice(-30))

const quickChatOpen = ref(false)
const quickChatCatalog = ref<Array<{ id: string; text: string }>>([])
const chatDraft = ref('')
const chatError = ref('')
const CHAT_MAX_LENGTH = 100
const surrenderArmed = ref(false)
const busy = ref(false)
const sideOpen = ref(false)

interface QuickChatItem {
  id: string
  text: string
}

async function loadQuickChatCatalog(): Promise<void> {
  try {
    const response = await fetch('/api/quick_chat', {
      headers: { accept: 'application/json' },
      credentials: 'same-origin',
    })
    if (!response.ok) return
    const body = (await response.json()) as { items?: unknown }
    const items = Array.isArray(body.items) ? body.items : []
    quickChatCatalog.value = items
      .map((item) => {
        if (!item || typeof item !== 'object') return null
        const record = item as Record<string, unknown>
        const id = String(record.id ?? '')
        const text = String(record.text ?? '')
        return id && text ? { id, text } : null
      })
      .filter((item): item is QuickChatItem => item !== null)
  } catch {
    // The catalog is optional: a missing one only hides the phrase list.
  }
}

const compact = ref(false)
const activeBoard = ref<'self' | 'opponent'>('opponent')
let mq: MediaQueryList | null = null

function syncCompact(): void {
  compact.value = mq ? mq.matches : false
  if (compact.value) activeBoard.value = myTurn.value ? 'opponent' : 'self'
}

if (typeof window !== 'undefined' && typeof window.matchMedia === 'function') {
  mq = window.matchMedia('(max-width: 719px)')
}

watch(myTurn, (value) => {
  if (compact.value) activeBoard.value = value ? 'opponent' : 'self'
})

const selfHidden = computed(() => compact.value && activeBoard.value !== 'self')
const opponentHidden = computed(() => compact.value && activeBoard.value !== 'opponent')

let seenGameOverAt = 0
let seenRoom = ''
let navigating = false

function maybeGoToSettlement(): void {
  const record = result.gameOver
  if (!record || navigating) return
  if (record.receivedAt === seenGameOverAt) return
  seenGameOverAt = record.receivedAt
  navigating = true
  void router.push({ name: 'game-over' })
}

watch(
  () => result.gameOver?.receivedAt,
  () => maybeGoToSettlement(),
)

watch(
  () => state.value.room_id,
  (room) => {
    if (room && room !== seenRoom) {
      seenRoom = room
      match.reset()
      selection.value = null
      shieldPicks.value = []
      shieldError.value = ''
      clearCardSelection()
    }
  },
)

let chainSafety: number | null = null

watch(
  () => match.chainWindow,
  (next) => {
    if (chainSafety !== null) {
      window.clearTimeout(chainSafety)
      chainSafety = null
    }
    if (!next) return
    // Safety net: the server owns the window and emits chain_resolved when it
    // closes; a lost frame must not leave a blocking dialog on screen forever.
    chainSafety = window.setTimeout(() => {
      if (!match.chainWindow) return
      match.closeChainWindow()
      match.pushNotice('连锁响应窗口已关闭，等待服务端结算', 'warning')
    }, (next.countdown + 3) * 1000)
  },
)

watch(
  () => match.notices[match.notices.length - 1]?.id,
  (id) => {
    if (!id) return
    window.setTimeout(() => match.dismissNotice(id), 6000)
  },
)

function clearCardSelection(): void {
  selectedCardIndex.value = -1
  selectedCardKey.value = ''
  noticeText.value = ''
}

function cardDisabled(card: CardLike): string {
  return cardDisabledReason(card, state.value, playCtx.value)
}

function cardTestIdFor(card: CardLike, index: number): string {
  return cardTestId(card, index, hand.value)
}

function onCardClick(index: number): void {
  const card = hand.value[index]
  if (!card) return
  const key = cardTestId(card, index, hand.value)
  if (selectedCardIndex.value === index && selectedCardKey.value === key) {
    void playCard(index)
    return
  }
  selectedCardIndex.value = index
  selectedCardKey.value = key
  const disabled = cardDisabled(card)
  noticeText.value = disabled
}

async function playCard(index: number): Promise<void> {
  const card = hand.value[index]
  if (!card) return
  const refusal = playRefusalReason(card, state.value, playCtx.value)
  if (refusal) {
    match.pushNotice(refusal, 'warning')
    clearCardSelection()
    return
  }
  const descriptor = targetDescriptor(card.name)
  if (!descriptor) {
    await dispatchCard(card, {})
    // A card without a local target panel must not stay "selected": the next
    // card that lands in the same hand slot would otherwise be played on the
    // first click (the card that left the hand kept its index/key selected).
    clearCardSelection()
    return
  }
  selection.value = {
    card,
    index,
    descriptor,
    board: descriptor.board ?? null,
    anchor: null,
    lineDir: 'row',
    picks: [],
    effectChoice: null,
    error: '',
  }
  clearCardSelection()
}

async function dispatchCard(card: CardLike, targets: Record<string, unknown>): Promise<void> {
  if (busy.value) return
  busy.value = true
  try {
    const ack = await sendBattleEvent('use_magic_card', {
      room_id: state.value.room_id,
      player_id: state.value.player_id,
      card: { name: card.name, speed: card.speed, type: card.type, description: card.description ?? '' },
      targets,
    })
    selection.value = null
    if (ack.status !== 'success') {
      match.pushNotice('使用魔法卡失败：' + (ack.message || '未知错误'), 'error')
      return
    }
    match.pushNotice('已使用「' + card.name + '」')
    if (hand.value.some((item) => cardIdentity(item) === cardIdentity(card))) {
      // Self-healing like the legacy client: the server is authoritative.
      await sendBattleEvent('request_hand_sync', {
        room_id: state.value.room_id,
        player_id: state.value.player_id,
      })
    }
  } catch (error) {
    match.pushNotice('使用魔法卡失败：' + String(error), 'error')
  } finally {
    busy.value = false
  }
}

function setSelectionError(message: string): void {
  const sel = selection.value
  if (!sel) return
  sel.error = message
  noticeText.value = message
}

function pickCell(board: 'self' | 'opponent', x: number, y: number): void {
  const sel = selection.value
  if (!sel) return
  const kind = sel.descriptor.kind
  if (kind === 'area' || kind === 'shenwei') {
    if (kind === 'shenwei' && !sel.board) {
      setSelectionError('请先选择目标棋盘（自己或对方）')
      return
    }
    const targetBoard = kind === 'shenwei' ? sel.board : sel.descriptor.board
    const expected = targetBoard === 'self' ? 'self' : 'opponent'
    if (board !== expected) {
      setSelectionError(expected === 'self' ? '请在自己海域选择区域' : '请在对手海域选择区域')
      return
    }
    sel.anchor = { x, y }
    sel.error = ''
    return
  }
  if (kind === 'line') {
    if (board !== 'opponent') {
      setSelectionError('请在对手海域选择行列')
      return
    }
    sel.anchor = { x, y }
    sel.error = ''
    return
  }
  if (kind === 'continuous') {
    if (board !== 'opponent') {
      setSelectionError('请在对手海域选择格子')
      return
    }
    const existing = sel.picks.findIndex((cell) => cell.x === x && cell.y === y)
    if (existing >= 0) sel.picks.splice(existing, 1)
    else if (sel.picks.length < (sel.descriptor.length ?? 6)) sel.picks.push({ x, y })
    if (!continuousLine(sel.picks)) sel.error = ''
    return
  }
  if (kind === 'single' || kind === 'own_ships') {
    if (board !== 'self') {
      setSelectionError('请在自己海域选择战舰')
      return
    }
    const cell = selfCells.value.find((item) => item.x === x && item.y === y)
    if (!cell || !cell.ship || cell.sunk) {
      setSelectionError('请选择一艘还活着的战舰所在的格子')
      return
    }
    if (kind === 'single') {
      sel.picks = [{ x, y }]
      sel.error = ''
      return
    }
    const existing = sel.picks.findIndex((item) => item.x === x && item.y === y)
    if (existing >= 0) sel.picks.splice(existing, 1)
    else if (sel.picks.length < (sel.descriptor.count ?? 2)) sel.picks.push({ x, y })
    sel.error = ''
    return
  }
}

function setLineDir(direction: 'row' | 'col'): void {
  const sel = selection.value
  if (!sel) return
  sel.lineDir = direction
  sel.error = ''
}

function setBoardSide(side: 'self' | 'opponent'): void {
  const sel = selection.value
  if (!sel) return
  sel.board = side
  sel.anchor = null
  sel.error = ''
}

function setEffectChoice(choice: number): void {
  const sel = selection.value
  if (!sel) return
  sel.effectChoice = choice
  sel.error = ''
}

function cancelSelection(): void {
  selection.value = null
  clearCardSelection()
}

function buildTargets(sel: SelectionState): Record<string, unknown> {
  const descriptor = sel.descriptor
  const kind = descriptor.kind
  if (kind === 'area' && sel.anchor) {
    return { target_area: areaFromAnchor(sel.anchor.x, sel.anchor.y, descriptor.size ?? 3) }
  }
  if (kind === 'line' && sel.anchor) {
    return {
      target_line: {
        type: sel.lineDir,
        index: sel.lineDir === 'row' ? sel.anchor.y : sel.anchor.x,
      },
    }
  }
  if (kind === 'continuous') {
    return { target_cells: sel.picks }
  }
  if (kind === 'single' && sel.picks.length === 1) {
    const cell = sel.picks[0]
    return { target_area: { x1: cell.x, y1: cell.y, x2: cell.x, y2: cell.y } }
  }
  if (kind === 'own_ships') {
    return { selected_cells: sel.picks, effect_choice: sel.effectChoice }
  }
  if (kind === 'shenwei' && sel.anchor && sel.board) {
    return {
      board: sel.board,
      target_area: areaFromAnchor(sel.anchor.x, sel.anchor.y, 3),
    }
  }
  return {}
}

async function confirmSelection(): Promise<void> {
  const sel = selection.value
  if (!sel || !canConfirm.value) return
  await dispatchCard(sel.card, buildTargets(sel))
}

async function fire(x: number, y: number): Promise<void> {
  if (!myTurn.value || state.value.current_phase !== 'battle') return
  if (!(state.value.attacks_remaining > 0)) return
  const existing = (Array.isArray(state.value.attacks) ? state.value.attacks : []).some(
    (cell) => cell && cell.x === x && cell.y === y,
  )
  if (existing) return
  try {
    const ack = await sendBattleEvent('attack', {
      room_id: state.value.room_id,
      player_id: state.value.player_id,
      x,
      y,
    })
    if (ack.status !== 'success') match.pushNotice(ack.message || '攻击失败', 'error')
  } catch (error) {
    match.pushNotice('攻击失败：' + String(error), 'error')
  }
}

function onCell(board: 'self' | 'opponent', x: number, y: number): void {
  if (selection.value) {
    pickCell(board, x, y)
    return
  }
  if (match.shieldChoice) {
    toggleShieldShip(x, y)
    return
  }
  if (match.pickRequest) {
    void choosePickCell(board, x, y)
    return
  }
  if (board === 'opponent') void fire(x, y)
}

async function choosePickCell(board: 'self' | 'opponent', x: number, y: number): Promise<void> {
  const pick = match.pickRequest
  if (!pick || board !== 'self') return
  const offered = pick.ships.some((ship) => ship.positions.some((cell) => cell.x === x && cell.y === y))
  if (!offered) {
    match.pushNotice('请选择面板中列出的战舰格子')
    return
  }
  const ack = await sendBattleEvent('confirm_sacrifice', {
    room_id: state.value.room_id,
    player_id: state.value.player_id,
    position: { x, y },
  })
  if (ack.status === 'success') {
    match.clearPickRequest()
    match.pushNotice(ack.message || '已选择一艘战舰')
  } else {
    match.pushNotice(ack.message || '选择失败', 'error')
  }
}

function toggleShieldShip(x: number, y: number): void {
  if (!match.shieldChoice) return
  const ships = Array.isArray(state.value.ships) ? state.value.ships : []
  const index = ships.findIndex((ship) => {
    if (!ship || ship.alive === false) return false
    return (Array.isArray(ship.positions) ? ship.positions : []).some(
      (position) => position.x === x && position.y === y,
    )
  })
  if (index < 0) {
    shieldError.value = '请在自己海域选择一艘还活着的战舰'
    return
  }
  const at = shieldPicks.value.indexOf(index)
  if (at >= 0) {
    shieldPicks.value.splice(at, 1)
  } else {
    if (shieldPicks.value.length >= 3) {
      shieldError.value = '最多选择 3 艘战舰'
      return
    }
    shieldPicks.value.push(index)
  }
  shieldError.value = ''
}

async function confirmShieldChoice(): Promise<void> {
  if (!match.shieldChoice || !shieldPicks.value.length) return
  const picks = shieldPicks.value.slice(0, 3)
  try {
    const ack = await sendBattleEvent('confirm_magic_target', {
      room_id: state.value.room_id,
      player_id: state.value.player_id,
      temp_data_id: 'shield_choice',
      target_data: { ship_indices: picks },
    })
    if (ack.status !== 'success') {
      shieldError.value = ack.message || '加盾失败，请重新选择'
      return
    }
    match.clearShieldChoice()
    shieldPicks.value = []
    shieldError.value = ''
    match.pushNotice(ack.message || '已为战舰添加护盾')
  } catch (error) {
    shieldError.value = '加盾失败：' + String(error)
  }
}

async function cancelShieldChoice(): Promise<void> {
  try {
    const ack = await sendBattleEvent('cancel_magic_selection', {
      room_id: state.value.room_id,
      player_id: state.value.player_id,
    })
    match.clearShieldChoice()
    shieldPicks.value = []
    shieldError.value = ''
    match.pushNotice(ack.status === 'success' ? '已取消仁王之盾选择' : (ack.message || '已取消本次选择'))
  } catch (error) {
    shieldError.value = '取消失败：' + String(error)
  }
}

async function respondChain(card: CardLike): Promise<void> {
  const ack = await sendBattleEvent('chain_response', {
    room_id: state.value.room_id,
    player_id: state.value.player_id,
    chain: true,
    card: { name: card.name, speed: card.speed, type: card.type, description: card.description ?? '' },
    targets: [],
  })
  match.closeChainWindow()
  if (ack.status !== 'success') match.pushNotice('连锁失败：' + (ack.message || '未知错误'), 'error')
}

async function passChain(): Promise<void> {
  const ack = await sendBattleEvent('chain_response', {
    room_id: state.value.room_id,
    player_id: state.value.player_id,
    chain: false,
  })
  match.closeChainWindow()
  if (ack.status !== 'success') match.pushNotice(ack.message || '连锁响应失败', 'error')
}

async function sendQuickChat(item: QuickChatItem): Promise<void> {
  const ack = await sendBattleEvent('quick_chat', {
    room_id: state.value.room_id,
    player_id: state.value.player_id,
    msg_id: item.id,
  })
  if (ack.status === 'success') quickChatOpen.value = false
  else match.pushNotice(ack.message || '快捷语发送失败', 'error')
}

async function sendChat(): Promise<void> {
  const message = chatDraft.value.trim()
  if (!message) {
    chatError.value = '说点什么再发送吧'
    return
  }
  if (Array.from(message).length > CHAT_MAX_LENGTH) {
    chatError.value = '消息太长了，最多 ' + CHAT_MAX_LENGTH + ' 个字'
    return
  }
  try {
    const ack = await sendBattleEvent('chat_message', {
      room_id: state.value.room_id,
      message,
    })
    if (ack?.status === 'success') {
      chatDraft.value = ''
      chatError.value = ''
    } else {
      chatError.value = ack?.message || '消息发送失败，请稍后再试'
      match.pushNotice(chatError.value, 'error')
    }
  } catch (error) {
    chatError.value = '消息发送失败：' + String(error)
    match.pushNotice(chatError.value, 'error')
  }
}

async function turnAction(event: 'enter_battle_phase' | 'enter_end_phase' | 'end_turn'): Promise<void> {
  try {
    const ack = await sendBattleEvent(event, {
      room_id: state.value.room_id,
      player_id: state.value.player_id,
    })
    if (ack.status !== 'success') match.pushNotice(ack.message || '操作失败', 'error')
  } catch (error) {
    match.pushNotice('操作失败：' + String(error), 'error')
  }
}

async function surrender(): Promise<void> {
  if (!surrenderArmed.value) {
    surrenderArmed.value = true
    window.setTimeout(() => {
      surrenderArmed.value = false
    }, 4000)
    return
  }
  surrenderArmed.value = false
  const ack = await sendBattleEvent('surrender', {
    room_id: state.value.room_id,
    player_id: state.value.player_id,
  })
  if (ack.status !== 'success') match.pushNotice(ack.message || '投降失败', 'error')
}

function showBoard(side: 'self' | 'opponent'): void {
  activeBoard.value = side
}

const selfSubtitle = computed(() => '存活 ' + String(state.value.remaining_ships) + ' 艘')
const opponentSubtitle = computed(() => '存活 ' + String(state.value.opponent_remaining_ships) + ' 艘')
const myFrozenText = computed(() => (frozenMine.value.size ? '你的 3×3 区域被冻结' : ''))
const theirFrozenText = computed(() => (frozenTheirs.value.size ? '对方 3×3 区域被冻结' : ''))
</script>

<template>
  <section
    class="screen game"
    data-screen="game"
    data-testid="screen-game"
    :data-board-mode="compact ? 'tabs' : 'side'"
    aria-labelledby="screen-game-title"
  >
    <h1 id="screen-game-title" class="visually-hidden">对局</h1>

    <header class="game__hud" data-testid="game-hud">
      <div class="game__chips">
        <span class="game__chip" data-testid="game-round">第 {{ state.round }} 回合</span>
        <span class="game__chip" data-testid="game-phase">{{ phaseText }}</span>
        <span class="game__chip game__chip--turn" data-testid="game-attacker">{{ turnLabel }}</span>
        <span class="game__chip" data-testid="game-attacks">剩余攻击 {{ state.attacks_remaining }}</span>
        <span class="game__chip game__chip--muted" data-testid="game-mode">{{ modeText }}</span>
        <span class="game__chip game__chip--muted" data-testid="game-field-magic">场地：{{ fieldMagic }}</span>
      </div>
      <div class="game__players">
        <span class="game__name" data-testid="game-self-name">{{ selfName }}</span>
        <span class="game__vs" aria-hidden="true">VS</span>
        <span class="game__name" data-testid="game-opponent-name">{{ opponentName }}</span>
        <span class="game__ships" data-testid="game-ships">{{ shipsText }}</span>
      </div>
      <div class="game__effects">
        <ul class="game__badges" data-testid="game-effect-self" aria-label="我的效果">
          <li
            v-for="badge in selfEffects"
            :key="'self-' + badge.key"
            class="game__badge"
            :data-testid="'game-effect-self-' + badge.key"
            :title="badge.description + (badge.expires ? '（' + badge.expires + '）' : '')"
          >
            {{ badge.label }}
          </li>
        </ul>
        <ul class="game__badges game__badges--opponent" data-testid="game-effect-opponent" aria-label="对手的效果">
          <li
            v-for="badge in opponentEffects"
            :key="'opponent-' + badge.key"
            class="game__badge game__badge--opponent"
            :data-testid="'game-effect-opponent-' + badge.key"
            :title="badge.description + (badge.expires ? '（' + badge.expires + '）' : '')"
          >
            {{ badge.label }}
          </li>
        </ul>
      </div>
    </header>

    <p v-if="!hasRoom" class="game__empty" data-testid="game-empty">
      还没有收到对局数据。进对局时会自动显示双方海域、手牌与本回合状态；刷新后请从大厅或布船重新进入。
    </p>

    <div class="game__main">
      <aside class="game__log-side" aria-label="对局日志栏">

        <section class="game__panel game__panel--log" data-testid="game-log" aria-label="对局日志">
          <h2 class="game__panel-title">对局日志</h2>
          <p v-if="!logs.length" class="game__panel-empty">暂无记录</p>
          <ol v-else class="game__logs">
            <li
              v-for="(entry, index) in logs"
              :key="'log-' + index"
              class="game__log"
              :data-testid="'game-log-entry-' + index"
            >
              {{ entry.text }}
            </li>
          </ol>
        </section>
      </aside>

      <div class="game__boards" data-testid="game-board-switch">
        <div v-if="compact" class="game__tabs" role="tablist" aria-label="切换棋盘">
          <button
            type="button"
            class="game__tab"
            :class="{ 'game__tab--active': activeBoard === 'opponent' }"
            role="tab"
            :aria-selected="activeBoard === 'opponent'"
            data-testid="game-board-tab-opponent"
            @click="showBoard('opponent')"
          >
            对手海域
          </button>
          <button
            type="button"
            class="game__tab"
            :class="{ 'game__tab--active': activeBoard === 'self' }"
            role="tab"
            :aria-selected="activeBoard === 'self'"
            data-testid="game-board-tab-self"
            @click="showBoard('self')"
          >
            我的海域
          </button>
        </div>
        <BoardPanel
          board="opponent"
          board-testid="game-board-opponent"
          title-testid="game-board-title-opponent"
          :title="'对手海域 · ' + opponentName"
          :subtitle="opponentSubtitle + (theirFrozenText ? ' · ' + theirFrozenText : '')"
          :cells="opponentCells"
          :preview="previewKeys"
          :hidden="opponentHidden"
          :picking="!!selection"
          @cell="(x, y) => onCell('opponent', x, y)"
        />
        <BoardPanel
          board="self"
          board-testid="game-board-self"
          title-testid="game-board-title-self"
          :title="'我的海域 · ' + selfName"
          :subtitle="selfSubtitle + (myFrozenText ? ' · ' + myFrozenText : '')"
          :cells="selfCells"
          :selected="selectedKeys.concat(shieldSelectedKeys)"
          :hidden="selfHidden"
          :picking="!!selection || !!match.pickRequest || shieldOpen"
          @cell="(x, y) => onCell('self', x, y)"
        />
      </div>

      <p v-if="compact && chainList.length" class="game__chain-strip" data-testid="game-chain-summary">
        连锁：{{ chainList.map((item) => item.name).join(' → ') }}
      </p>
      <aside class="game__side" :class="{ 'game__side--open': sideOpen }">
        <section class="game__panel" data-testid="game-chain" aria-label="连锁">
          <h2 class="game__panel-title">连锁</h2>
          <p v-if="!chainList.length" class="game__panel-empty" data-testid="game-chain-empty">当前没有连锁</p>
          <ol v-else class="game__chain" data-testid="game-chain-stack">
            <li
              v-for="(item, index) in chainList"
              :key="'chain-' + index"
              class="game__chain-item"
              :class="{ 'game__chain-item--negated': item.negated }"
              :data-testid="'game-chain-item-' + index"
            >
              <b :data-testid="'game-chain-item-' + index + '-name'">{{ item.name }}</b>
              <span v-if="item.negated" class="game__chain-negated">已无效</span>
            </li>
          </ol>
        </section>

      </aside>
    </div>

    <div class="game__bottom">
      <section class="game__hand-wrap" aria-label="手牌">
        <div class="game__stats" data-testid="game-stats">
          <span data-testid="game-stat-hits">命中 {{ hits }}</span>
          <span data-testid="game-stat-shots">开火 {{ shots }}</span>
        </div>
        <div class="game__hand" data-testid="game-hand">
          <p v-if="!hand.length" class="game__hand-empty" data-testid="game-hand-empty">手上没有魔法卡</p>
          <button
            v-for="(card, index) in hand"
            :key="cardTestIdFor(card, index)"
            type="button"
            class="card"
            :class="{
              'card--selected': selectedCardIndex === index,
              'card--disabled': !!cardDisabled(card),
              'card--art': !!cardArtUrl(card.name),
            }"
            :data-testid="cardTestIdFor(card, index)"
            :data-card-name="card.name"
            :data-card-speed="String(card.speed)"
            :aria-pressed="selectedCardIndex === index"
            :aria-label="card.name + '，速阶 ' + String(card.speed) + '，' + card.type"
            :title="cardDisabled(card) || card.description || card.name"
            @click="onCardClick(index)"
          >
            <img
              v-if="cardArtUrl(card.name)"
              class="card__art"
              :src="cardArtUrl(card.name) || ''"
              alt=""
              aria-hidden="true"
              loading="eager"
              decoding="async"
            />
            <span class="card__name">{{ card.name }}</span>
            <span class="card__gems" :title="'速阶 ' + String(card.speed)">{{ speedGems(cardSpeed(card)) }}</span>
            <span class="card__type">{{ String(card.speed) }} · {{ card.type }}</span>
            <span class="card__desc">{{ card.description }}</span>
          </button>
        </div>
      </section>

      <div class="game__actions" data-testid="game-actions">
        <p class="game__hint" data-testid="game-turn-hint">{{ turnLabel }} · {{ phaseText }}</p>
        <button
          type="button"
          class="button game__action"
          data-testid="game-enter-battle"
          :disabled="!myTurn || state.current_phase !== 'preparation'"
          @click="turnAction('enter_battle_phase')"
        >
          进入战斗阶段
        </button>
        <button
          type="button"
          class="button game__action"
          data-testid="game-enter-end"
          :disabled="!myTurn || state.current_phase !== 'battle'"
          @click="turnAction('enter_end_phase')"
        >
          进入结束阶段
        </button>
        <button
          type="button"
          class="button game__action"
          data-testid="game-end-turn"
          :disabled="!myTurn || state.current_phase !== 'end'"
          @click="turnAction('end_turn')"
        >
          结束回合
        </button>
        <button
          type="button"
          class="button game__action game__action--danger"
          data-testid="game-surrender"
          @click="surrender"
        >
          {{ surrenderArmed ? '再次点击确认投降' : '投降' }}
        </button>
        <button
          type="button"
          class="button game__action"
          data-testid="game-quick-chat-button"
          @click="quickChatOpen = !quickChatOpen"
        >
          快捷语
        </button>
        <button
          v-if="compact"
          type="button"
          class="button game__action"
          data-testid="game-log-toggle"
          @click="sideOpen = !sideOpen"
        >
          日志
        </button>
      </div>
    </div>

    <section v-if="quickChatOpen" class="game__drawer" data-testid="game-quick-chat" aria-label="局内聊天">
      <header class="game__drawer-head">
        <h2 class="game__panel-title">局内聊天</h2>
        <button type="button" class="button game__action" data-testid="game-quick-chat-close" @click="quickChatOpen = false">
          关闭
        </button>
      </header>
      <section class="game__chat-text" data-testid="game-chat" aria-label="文字聊天">
        <ol class="game__chat-log" data-testid="game-chat-messages" aria-live="polite">
          <li
            v-for="(message, index) in chatMessages"
            :key="'chat-' + index"
            class="game__chat-line"
            :class="{ 'game__chat-line--mine': message.username === selfName }"
            :data-testid="'game-chat-message-' + index"
          >
            <b>{{ message.username }}</b>：{{ message.message }}
          </li>
        </ol>
        <p v-if="!chatMessages.length" class="game__panel-empty" data-testid="game-chat-empty">还没有人说话</p>
        <p v-if="chatError" class="game__target-error" data-testid="game-chat-error">{{ chatError }}</p>
        <div class="game__chat-form">
          <input
            v-model="chatDraft"
            class="game__chat-input"
            type="text"
            :maxlength="CHAT_MAX_LENGTH"
            placeholder="说点什么…"
            aria-label="聊天内容"
            data-testid="game-chat-input"
            @keydown.enter.prevent="sendChat"
          />
          <button type="button" class="button game__action" data-testid="game-chat-send" @click="sendChat">
            发送
          </button>
        </div>
      </section>
      <h3 class="game__panel-title">快捷语</h3>
      <ul class="game__chat-items">
        <li v-for="item in quickChatCatalog" :key="item.id">
          <button
            type="button"
            class="button game__chat-item"
            :data-testid="'game-quick-chat-item-' + item.id"
            @click="sendQuickChat(item)"
          >
            {{ item.text }}
          </button>
        </li>
      </ul>
      <p v-if="!quickChatCatalog.length" class="game__panel-empty">快捷语目录暂不可用</p>
      <ol class="game__chat-log" data-testid="game-quick-chat-messages">
        <li
          v-for="(message, index) in quickChatMessages"
          :key="'qc-' + index"
          class="game__chat-message"
          :data-testid="'game-quick-chat-message-' + index"
        >
          <b>{{ message.name }}</b>：{{ message.text }}
        </li>
      </ol>
    </section>

    <section v-if="selection" class="game__target" data-testid="game-target" aria-label="目标选择">
      <h2 class="game__panel-title" data-testid="game-target-title">{{ targetTitle }}</h2>
      <p class="game__target-hint" data-testid="game-target-hint">{{ targetHint }}</p>
      <p class="game__target-selected" data-testid="game-target-selected">已选：{{ pickCountText }}</p>
      <p v-if="selection.error" class="game__target-error" data-testid="game-target-error">{{ selection.error }}</p>
      <div v-if="selection.descriptor.kind === 'line'" class="game__target-row">
        <button
          type="button"
          class="button game__action"
          data-testid="game-target-line-row"
          :class="{ 'game__action--active': selection.lineDir === 'row' }"
          @click="setLineDir('row')"
        >
          整行
        </button>
        <button
          type="button"
          class="button game__action"
          data-testid="game-target-line-col"
          :class="{ 'game__action--active': selection.lineDir === 'col' }"
          @click="setLineDir('col')"
        >
          整列
        </button>
      </div>
      <div v-if="selection.descriptor.kind === 'shenwei'" class="game__target-row">
        <button
          type="button"
          class="button game__action"
          data-testid="game-target-board-self"
          :class="{ 'game__action--active': selection.board === 'self' }"
          @click="setBoardSide('self')"
        >
          我的棋盘
        </button>
        <button
          type="button"
          class="button game__action"
          data-testid="game-target-board-opponent"
          :class="{ 'game__action--active': selection.board === 'opponent' }"
          @click="setBoardSide('opponent')"
        >
          对手棋盘
        </button>
      </div>
      <div v-if="selection.descriptor.kind === 'own_ships'" class="game__target-row">
        <button
          type="button"
          class="button game__action"
          data-testid="game-target-effect-destroy"
          :class="{ 'game__action--active': selection.effectChoice === 1 }"
          @click="setEffectChoice(1)"
        >
          摧毁对方一艘战舰
        </button>
        <button
          type="button"
          class="button game__action"
          data-testid="game-target-effect-skip"
          :class="{ 'game__action--active': selection.effectChoice === 2 }"
          @click="setEffectChoice(2)"
        >
          跳过对方本回合
        </button>
      </div>
      <div class="game__target-row">
        <button
          type="button"
          class="button game__action"
          data-testid="game-target-confirm"
          :disabled="!canConfirm"
          @click="confirmSelection"
        >
          确认使用
        </button>
        <button type="button" class="button game__action" data-testid="game-target-cancel" @click="cancelSelection">
          取消
        </button>
      </div>
    </section>

    <section
      v-if="shieldOpen"
      class="game__target game__shield-choice"
      data-testid="game-shield-choice"
      role="dialog"
      aria-label="仁王之盾选择"
    >
      <h2 class="game__panel-title" data-testid="game-shield-choice-title">「仁王之盾」：请选择要保护的战舰</h2>
      <p class="game__target-hint" data-testid="game-shield-choice-hint">
        在自己海域点击高亮的战舰格；再点一次取消选择。
      </p>
      <p class="game__target-selected" data-testid="game-shield-choice-count">
        已选 {{ shieldPicks.length }} / 3 艘
      </p>
      <p v-if="shieldError" class="game__target-error" data-testid="game-shield-choice-error">{{ shieldError }}</p>
      <p class="game__target-hint" data-testid="game-shield-choice-status">
        服务端没有选择倒计时；点「取消选择」可放弃本次加盾。
      </p>
      <div class="game__target-row">
        <button
          type="button"
          class="button game__action"
          data-testid="game-shield-choice-confirm"
          :disabled="shieldPicks.length === 0"
          @click="confirmShieldChoice"
        >
          确认加盾
        </button>
        <button type="button" class="button game__action" data-testid="game-shield-choice-cancel" @click="cancelShieldChoice">
          取消选择
        </button>
      </div>
    </section>

    <section v-if="chainWindow" class="game__chain-window" data-testid="game-chain-window" role="alertdialog" aria-label="连锁响应">
      <h2 class="game__panel-title">连锁响应窗口</h2>
      <p class="game__target-hint">
        对方使用了
        <b data-testid="game-chain-window-card">{{ chainWindow.card ? chainWindow.card.name : '魔法卡' }}</b>
        ，你可以用速阶 3 的卡连锁它。
      </p>
      <p class="game__chain-countdown" data-testid="game-chain-window-countdown">剩余 {{ chainRemaining }} 秒</p>
      <div class="game__target-row">
        <button
          v-for="(card, index) in speed3Hand"
          :key="chainCardTestId(card, index, speed3Hand)"
          type="button"
          class="button game__action"
          :data-testid="chainCardTestId(card, index, speed3Hand)"
          @click="respondChain(card)"
        >
          连锁「{{ card.name }}」
        </button>
        <button type="button" class="button game__action" data-testid="game-chain-pass" @click="passChain">
          不响应
        </button>
      </div>
    </section>

    <section v-if="match.pickRequest" class="game__pick" data-testid="game-ship-pick" role="alertdialog" aria-label="选船">
      <h2 class="game__panel-title">请选择一艘自己的战舰</h2>
      <p class="game__target-hint" data-testid="game-ship-pick-message">{{ match.pickRequest.message }}</p>
      <p class="game__panel-empty">在自己海域点击高亮的战舰格子。</p>
    </section>

    <p v-if="pendingPick && !match.pickRequest" class="game__banner" data-testid="game-pending-pick">
      待处理：{{ pendingPick.message }}
    </p>
    <p v-if="state.priority_waiting" class="game__banner" data-testid="game-priority-waiting">
      等待对方响应「{{ state.priority_waiting.action_text }}」
    </p>
    <p v-if="state.shenji_waiting" class="game__banner" data-testid="game-shenji-waiting">
      {{ state.shenji_waiting.text }}
    </p>

    <p v-if="noticeText" class="game__notice-text" data-testid="game-card-hint">{{ noticeText }}</p>

    <ul v-if="notices.length" class="game__notices" data-testid="game-notices" aria-live="polite">
      <li
        v-for="notice in notices"
        :key="notice.id"
        class="game__notice"
        :class="'game__notice--' + notice.kind"
        :data-testid="'game-notice-' + notice.id"
      >
        {{ notice.text }}
      </li>
    </ul>
  </section>
</template>

<style scoped>
.game {
  position: relative;
  gap: 8px;
  padding: 8px 12px 12px;
  min-height: 0;
}

.visually-hidden {
  position: absolute;
  width: 1px;
  height: 1px;
  overflow: hidden;
  clip: rect(0 0 0 0);
  white-space: nowrap;
}

.game__hud {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px 12px;
}

.game__chips {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.game__chip {
  padding: 4px 11px;
  border: 1px solid var(--border-strong);
  border-radius: 999px;
  background: rgba(21, 26, 48, 0.7);
  font-size: 12px;
  font-variant-numeric: tabular-nums;
}

.game__chip--turn {
  border-color: var(--accent-strong);
  background: var(--accent-soft);
  color: var(--text);
}

.game__chip--muted {
  color: var(--text-muted);
}

.game__players {
  display: flex;
  align-items: baseline;
  gap: 8px;
  margin-left: auto;
  font-size: 13px;
}

.game__vs {
  color: var(--text-muted);
  font-size: 11px;
}

.game__name {
  font-weight: 600;
}

.game__ships {
  color: var(--accent);
  font-variant-numeric: tabular-nums;
}



.game__effects {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  width: 100%;
}

.game__badges {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
  margin: 0;
  padding: 0;
  list-style: none;
}

.game__badge {
  padding: 2px 8px;
  border: 1px solid rgba(201, 162, 76, 0.55);
  border-radius: 999px;
  background: var(--gold-soft);
  color: var(--gold-strong);
  font-size: 11px;
}

.game__badge--opponent {
  border-color: var(--border);
  background: rgba(21, 26, 48, 0.7);
  color: var(--text-muted);
}

.game__empty {
  margin: 0;
  padding: 10px 14px;
  border: 1px dashed var(--border);
  border-radius: var(--radius);
  color: var(--text-muted);
  font-size: 13px;
}

.game__main {
  display: flex;
  flex: 1;
  gap: 14px;
  min-height: 0;
  align-items: stretch;
}

/* C+ game layout: battle log on the left, both seas in the centre, a tall
   dashed chain rail, then the bottom hand/action strip. */
.game__log-side {
  display: flex;
  flex: 0 0 280px;
  width: 280px;
  min-height: 0;
}

.game__log-side .game__panel {
  align-self: flex-start;
  width: 100%;
  max-height: 360px;
}

.game__boards {
  display: flex;
  flex: 1;
  gap: 18px;
  min-width: 0;
  flex-wrap: wrap;
  align-content: flex-start;
  justify-content: flex-start;
  padding-top: 82px;
  --cell: clamp(38px, min(3.5vw, calc((100dvh - 430px) / 6)), 50px);
}

.game__tabs {
  display: flex;
  gap: 6px;
  width: 100%;
}

.game__tab {
  flex: 1;
  padding: 6px 10px;
  border: 1px solid var(--border);
  border-radius: 8px;
  background: var(--bg-sunken);
  color: var(--text-muted);
  font: inherit;
  font-size: 13px;
}

.game__tab--active {
  border-color: var(--accent-strong);
  color: var(--text);
  background: var(--accent-soft);
}

.game__side {
  display: flex;
  flex-direction: column;
  gap: 8px;
  flex: 0 0 200px;
  width: 200px;
  min-height: 0;
}

.game__side > .game__panel {
  flex: 1;
  padding: 12px;
  border: 1px dashed rgba(230, 199, 120, 0.45);
  background: rgba(32, 28, 16, 0.22);
}

.game__panel {
  padding: 10px 12px;
  border: 1px solid var(--panel-line);
  border-radius: 10px;
  background: var(--panel);
  min-height: 0;
}

.game__panel--log {
  flex: 1;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.game__panel-title {
  margin: 0 0 8px;
  padding-bottom: 7px;
  border-bottom: 1px dashed var(--line-dash);
  color: var(--text);
  font-size: 12px;
  font-weight: 600;
  letter-spacing: 0.08em;
}

.game__panel-empty {
  margin: 0;
  color: var(--text-muted);
  font-size: 12px;
}

.game__chain {
  display: flex;
  flex-direction: column;
  gap: 4px;
  margin: 0;
  padding: 0;
  list-style: none;
}

.game__chain-item {
  display: flex;
  align-items: baseline;
  gap: 6px;
  padding: 4px 8px;
  border: 1px solid rgba(124, 92, 240, 0.5);
  border-radius: 8px;
  background: var(--accent-soft);
  font-size: 13px;
}

.game__chain-item--negated {
  border-color: rgba(255, 92, 108, 0.45);
  background: rgba(42, 20, 24, 0.8);
  text-decoration: line-through;
  opacity: 0.7;
}

.game__chain-negated {
  color: var(--danger);
  font-size: 11px;
  text-decoration: none;
}

.game__logs {
  display: flex;
  flex-direction: column;
  gap: 3px;
  margin: 0;
  padding: 0;
  list-style: none;
  overflow-y: auto;
  min-height: 0;
  font-size: 12px;
  color: var(--text-muted);
}

.game__log {
  line-height: 1.4;
}

.game__bottom {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto minmax(0, 1fr);
  align-items: end;
  gap: 12px;
}

.game__hand-wrap {
  grid-column: 2;
  justify-self: center;
  display: flex;
  flex-direction: column;
  gap: 4px;
  min-width: 0;
}

.game__stats {
  display: flex;
  gap: 12px;
  color: var(--text-muted);
  font-size: 12px;
  font-variant-numeric: tabular-nums;
}

.game__hand {
  display: flex;
  gap: 8px;
  overflow-x: auto;
  padding-bottom: 4px;
  min-height: 150px;
}

.game__hand-empty {
  margin: 0;
  align-self: center;
  color: var(--text-muted);
  font-size: 13px;
}

.card {
  position: relative;
  display: flex;
  flex-direction: column;
  gap: 2px;
  width: 96px;
  min-width: 96px;
  aspect-ratio: 2 / 3;
  padding: 6px 8px;
  overflow: hidden;
  border: 1px solid var(--border);
  border-radius: 10px;
  background: linear-gradient(170deg, #232b52, #12172e);
  color: var(--text);
  font: inherit;
  text-align: left;
  cursor: pointer;
}

.card--art {
  padding: 0;
}

.card--art .card__name,
.card--art .card__gems,
.card--art .card__type,
.card--art .card__desc {
  display: none;
}

.card__art {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
  object-fit: cover;
}

.card:hover {
  border-color: var(--accent-strong);
}

.card--selected {
  border-color: var(--accent);
  box-shadow: 0 0 0 2px rgba(124, 92, 240, 0.45);
}

.card--disabled {
  opacity: 0.45;
  cursor: not-allowed;
}

.card__name {
  font-size: 13px;
  font-weight: 700;
}

.card__gems {
  color: var(--accent);
  font-size: 10px;
  letter-spacing: 1px;
}

.card__type {
  color: var(--text-muted);
  font-size: 10px;
}

.card__desc {
  display: -webkit-box;
  -webkit-line-clamp: 3;
  -webkit-box-orient: vertical;
  overflow: hidden;
  color: var(--text-muted);
  font-size: 10px;
  line-height: 1.35;
}

.game__actions {
  grid-column: 3;
  justify-self: end;
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px;
  max-width: 380px;
}

.game__hint {
  flex-basis: 100%;
  margin: 0;
  color: var(--text-muted);
  font-size: 12px;
}

.game__action {
  padding: 6px 10px;
  font-size: 12px;
}

.game__action:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}

.game__action--active {
  border-color: var(--accent);
  color: var(--accent);
}

.game__action--danger {
  border-color: #6b2b26;
  background: #2a1414;
}

.game__target,
.game__chain-window,
.game__pick,
.game__drawer {
  position: absolute;
  z-index: 20;
  right: 12px;
  bottom: 12px;
  width: min(420px, calc(100% - 24px));
  display: flex;
  flex-direction: column;
  gap: 6px;
  padding: 12px;
  border: 1px solid var(--accent-strong);
  border-radius: var(--radius);
  background: #0b1c26;
  box-shadow: 0 12px 32px rgb(0 0 0 / 45%);
}

.game__drawer {
  right: 12px;
  top: 12px;
  bottom: auto;
  max-height: 70%;
  overflow-y: auto;
}

@media (max-width: 1279px) {
  .game__log-side {
    display: none;
  }

  .game__side {
    flex-basis: 190px;
    width: 190px;
  }

  .game__boards {
    padding-top: 0;
  }

  .game__tab {
    min-height: 40px;
  }

  .game__action {
    min-height: 40px;
  }
}

@media (max-width: 899px) {
  .game {
    padding: 3px 10px 4px;
    gap: 4px;
  }

  .game__main {
    gap: 6px;
  }

  .game__bottom {
    display: flex;
    gap: 6px;
  }

  .game__hand-wrap {
    flex: 1;
    justify-self: stretch;
  }

  .game__actions {
    justify-self: auto;
  }

  .game__hand {
    min-height: 100px;
  }
}

.game__chain-window {
  border-color: #ffd76a;
  left: 12px;
  right: auto;
}

.game__pick {
  left: 12px;
  right: auto;
  bottom: 12px;
  border-color: var(--danger);
}

.game__drawer-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}

.game__target-hint,
.game__target-selected {
  margin: 0;
  color: var(--text-muted);
  font-size: 12px;
}

.game__target-error {
  margin: 0;
  color: var(--danger);
  font-size: 12px;
}

.game__target-row {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.game__chain-countdown {
  margin: 0;
  color: #ffd76a;
  font-size: 13px;
  font-variant-numeric: tabular-nums;
}

.game__chat-items {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin: 0;
  padding: 0;
  list-style: none;
}

.game__chat-item {
  padding: 4px 8px;
  font-size: 12px;
}

.game__chat-log {
  display: flex;
  flex-direction: column;
  gap: 4px;
  margin: 6px 0 0;
  padding: 0;
  list-style: none;
  color: var(--text-muted);
  font-size: 12px;
}

.game__chat-text {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.game__chat-line {
  overflow-wrap: anywhere;
}

.game__chat-line b {
  color: var(--accent);
}

.game__chat-line--mine b {
  color: var(--text);
}

.game__chat-form {
  display: flex;
  align-items: center;
  gap: 6px;
}

.game__chat-input {
  flex: 1 1 auto;
  min-width: 0;
  padding: 6px 9px;
  border: 1px solid var(--border);
  border-radius: 8px;
  background: #081824;
  color: var(--text);
  font: inherit;
  font-size: 13px;
}

.game__banner {
  margin: 0;
  padding: 6px 10px;
  border: 1px solid #b8872e;
  border-radius: 8px;
  background: #2a2412;
  color: #ffd76a;
  font-size: 12px;
}

.game__notice-text {
  margin: 0;
  color: var(--text-muted);
  font-size: 12px;
}

.game__notices {
  position: absolute;
  z-index: 30;
  left: 12px;
  top: 12px;
  display: flex;
  flex-direction: column;
  gap: 4px;
  margin: 0;
  padding: 0;
  list-style: none;
  max-width: min(420px, calc(100% - 24px));
}

.game__notice {
  padding: 5px 10px;
  border: 1px solid var(--border);
  border-radius: 8px;
  background: #0b1c26;
  font-size: 12px;
}

.game__notice--warning {
  border-color: #b8872e;
  color: #ffd76a;
}

.game__notice--error {
  border-color: var(--danger);
  color: var(--danger);
}

@media (max-width: 900px) {
  .game__side {
    width: 200px;
  }
}

@media (max-width: 719px) {
  .game {
    padding: 6px;
    gap: 4px;
  }

  .game__main {
    flex-direction: column;
  }

  .game__boards {
    display: block;
    --cell: clamp(32px, min(12vw, calc((100dvh - 500px) / 6)), 40px);
  }

  .game__side {
    display: none;
  }

  .game__side--open {
    display: flex;
    position: absolute;
    z-index: 25;
    inset: 6px;
    width: auto;
    padding: 8px;
    border: 1px solid var(--border);
    border-radius: var(--radius);
    background: #0b1c26;
    overflow-y: auto;
  }

  .game__chain-strip {
    margin: 0;
    color: var(--accent);
    font-size: 11px;
  }

  .game__panel--log {
    max-height: none;
    flex: 0 1 auto;
  }

  .game__hint {
    display: none;
  }

  .game__chip {
    font-size: 11px;
    padding: 2px 7px;
  }

  .game__bottom {
    flex-wrap: wrap;
    gap: 6px;
  }

  .game__actions {
    max-width: none;
    width: 100%;
  }

  .game__hand {
    min-height: 104px;
  }

  .game__stats {
    display: none;
  }

  .card {
    width: 70px;
    min-width: 70px;
    padding: 4px 6px;
  }

  .card--art {
    padding: 0;
  }

  .card__desc {
    -webkit-line-clamp: 2;
    font-size: 9px;
  }

  .game__target,
  .game__drawer,
  .game__pick,
  .game__chain-window {
    left: 6px;
    right: 6px;
    width: auto;
    bottom: 6px;
  }

  .game__drawer {
    top: 6px;
    bottom: auto;
    max-height: 60%;
  }
}
</style>
