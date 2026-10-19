// GENERATED from backend contracts (JSON Schema). Do not edit by hand.
// Regenerate: python -m battleship.contracts.export_schema --format ts --out frontend/src/socket/events.gen.ts
export const CONTRACT_SCHEMA_VERSION = 1
export const CONTRACT_SCHEMA_HASH = 'e5c6d683cf63f3705cbb52745e14c1740decdc2d187b02f2a75d4f052b5213b6'

export const INBOUND_EVENTS = [
  'connect',
  'disconnect',
  'debug_status',
  'create_room',
  'join_room',
  'create_ai_room',
  'find_match',
  'cancel_match',
  'place_ships',
  'rps_choice',
  'attack',
  'enter_battle_phase',
  'enter_end_phase',
  'end_turn',
  'papal_discard',
  'papal_attack',
  'surrender',
  'chat_message',
  'quick_chat',
  'request_revealed_positions',
  'confirm_reinforcement_position',
  'confirm_sacrifice',
  'cancel_placement',
  'use_magic_card',
  'select_magic_target',
  'confirm_magic_target',
  'cancel_magic_selection',
  'get_magic_temp_data',
  'get_discard_pile',
  'chain_response',
  'remove_field_magic',
  'confirm_shenji_declare',
  'dice_discard_choose',
  'priority_response',
  'set_decline_priority',
  'get_reconnect_token',
  'rejoin_room',
  'request_hand_sync',
  'spectate_join',
  'spectate_leave',
  'spectate_chat_send',
  'lobby_subscribe',
  'lobby_unsubscribe',
  'lobby_refresh',
  'lobby_create_room',
  'lobby_chat_send',
  'close_room',
  'test_set_ai_rps_choice',
  'test_add_all_magic_cards',
  'test_set_player_ships',
  'test_clear_all_effects',
  'test_add_specific_magic_card',
  'test_get_game_state',
  'test_reset_game',
  'test_set_opponent_ships',
  'test_end_turn',
  'test_win_game',
  'test_lose_game',
  'test_get_multi_area_chain',
  'test_get_magic_cards_list',
  'test_auto_attack',
] as const

export const OUTBOUND_EVENTS = [
  'achievements_unlocked',
  'active_effects',
  'attack_result',
  'attacks_updated',
  'board_attacks_updated',
  'chain_request',
  'chain_resolved',
  'chat_message',
  'dice_discard_complete',
  'dice_discard_request',
  'dice_rolled',
  'error',
  'field_magic_updated',
  'frozen_area',
  'game_canceled',
  'game_log',
  'game_message',
  'game_over',
  'game_state',
  'hand_updated',
  'holy_heart_activated',
  'holy_heart_interrupted',
  'holy_heart_turn_updated',
  'lanyu_recalled',
  'last_stand_cells',
  'lingqi_complete',
  'lingqi_waiting',
  'lobby_chat',
  'lobby_chat_history',
  'lobby_hello',
  'lobby_state',
  'magic_chain_updated',
  'match_canceled',
  'match_queued',
  'message',
  'opponent_disconnected',
  'opponent_reconnected',
  'phase_updated',
  'placement_done',
  'placement_request',
  'player_ships_updated',
  'priority_request',
  'priority_setting_updated',
  'priority_waiting',
  'priority_waiting_end',
  'quick_chat',
  'rank_changed',
  'reconnect_token',
  'reconnect_warning',
  'reinforcement_activated',
  'reinforcement_turn_updated',
  'reset_gameboard',
  'resume_game',
  'revealed_positions',
  'room_sync',
  'rps_result',
  'sacrifice_cancelled',
  'sacrifice_request',
  'shenji_waiting',
  'shenji_waiting_end',
  'shenwei_hole',
  'shenwei_hole_restored',
  'shield_absorbed',
  'shields_added',
  'ship_sacrificed',
  'ships_updated',
  'spectate_board',
  'spectate_chat',
  'spectate_count_changed',
  'spectate_ended',
  'spectate_roster',
  'spectate_sync',
  'spectate_you',
  'taoyuan_complete',
  'taoyuan_waiting',
  'trap_expired',
  'trap_set',
  'trap_triggered',
  'turn_change',
  'turn_skipped',
  'wangyang_complete',
  'xp_gained',
] as const

export const DEBUG_EVENTS = [
  'test_set_ai_rps_choice',
  'test_add_all_magic_cards',
  'test_set_player_ships',
  'test_clear_all_effects',
  'test_add_specific_magic_card',
  'test_get_game_state',
  'test_reset_game',
  'test_set_opponent_ships',
  'test_end_turn',
  'test_win_game',
  'test_lose_game',
  'test_get_multi_area_chain',
  'test_get_magic_cards_list',
  'test_auto_attack',
] as const

export type InboundEvent = (typeof INBOUND_EVENTS)[number]
export type OutboundEvent = (typeof OUTBOUND_EVENTS)[number]
export type DebugEvent = (typeof DEBUG_EVENTS)[number]
export type RoomKind = 'matchmaking' | 'custom' | 'ai' | 'spectate'

export interface SocketIdentity {
  player_id: string | null
  user_id: number | null
}

export interface InboundEventEnvelope {
  event: string
  data: Record<string, unknown>
  namespace: string
  identity: SocketIdentity | null
}

export interface OutboundEventEnvelope {
  event: string
  data: Record<string, unknown>
  namespace: string
  to: string | null
  room: string | null
  skip_sid: string | null
}

export interface AckResponse {
  status: 'success' | 'error'
  message: string | null
  data: Record<string, unknown> | null
}
