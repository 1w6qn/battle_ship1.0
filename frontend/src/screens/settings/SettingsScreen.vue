<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { useSettingsStore, type PrivacyKey } from '../../stores/settings'
import { useAudioStore } from '../../stores/audio'

/**
 * Ticket #25: settings.
 *
 * The two account switches and every privacy checkbox are written on change and
 * re-read from the server response; the screen never keeps a local "maybe it
 * saved" state. The card payload always carries the frozen eleven fields.
 */
const router = useRouter()
const settings = useSettingsStore()
const audio = useAudioStore()

const oldPassword = ref('')
const newPassword = ref('')

const privacyRows: { key: PrivacyKey; testid: string; label: string; hint: string }[] = [
  { key: 'show_stats', testid: 'settings-privacy-stats', label: '显示战绩亮点', hint: '最高连胜 / 胜率 / 总场次' },
  { key: 'show_fav_cards', testid: 'settings-privacy-favcards', label: '显示最爱用的卡', hint: '名片上的常用卡牌' },
  { key: 'show_history', testid: 'settings-privacy-history', label: '公开对局历史', hint: '别人能在你的名片上看到战绩列表' },
  { key: 'show_guestbook', testid: 'settings-privacy-guestbook', label: '公开留言板', hint: '别人可以在你的名片上留言' },
  { key: 'show_rank', testid: 'settings-privacy-rank', label: '公开段位', hint: '关闭后他人看不到你的段位与排位分（段位榜不受影响）' },
  { key: 'friend_requests_open', testid: 'settings-privacy-friend-requests', label: '允许他人加我好友', hint: '关闭后陌生人不能向你发好友申请' },
]

const anonymous = computed(
  () => settings.profileStatus === 'anonymous' || settings.replay.status === 'anonymous',
)
const profileFailed = computed(() => settings.profileStatus === 'error')
const privacyReady = computed(() => settings.profileStatus === 'ready')

function toggleStatus(kind: 'replay' | 'spectate'): string {
  const state = kind === 'replay' ? settings.replay : settings.spectate
  if (state.status === 'anonymous') return '登录后才能修改'
  if (state.saving) return '保存中…'
  if (state.error) return state.error
  if (state.status === 'loading') return '正在读取…'
  if (state.value === null) return '状态未知'
  return state.value ? '已开启' : '已关闭'
}

const privacyStatus = computed(() => {
  if (!privacyReady.value) return '登录后才能修改'
  if (settings.privacySaving) return '保存中…'
  if (settings.privacyMessage) return settings.privacyMessage
  return '改动会立即保存'
})

const wallpaperStatus = computed(() => {
  const state = settings.wallpaper
  if (state.status === 'loading') return '正在检查本机壁纸库…'
  if (state.status === 'error') return '读取失败：' + state.error
  if (state.status === 'ready') {
    if (state.available === false) return state.reason || '当前环境不可用'
    return '本机可用：发现 ' + state.dirs + ' 个壁纸目录，' + state.items.length + ' 张壁纸'
  }
  return '壁纸库管理暂未迁移；本机可用性可以先检查。'
})


function onSfxVolume(event: Event): void {
  const target = event.target as HTMLInputElement | null
  if (target) audio.setSfxVolume(Number(target.value) / 100)
}

function onBgmVolume(event: Event): void {
  const target = event.target as HTMLInputElement | null
  if (target) audio.setBgmVolume(Number(target.value) / 100)
}

async function onReplayChange(event: Event): Promise<void> {
  const target = event.target as HTMLInputElement | null
  if (!target) return
  await settings.setToggle('replay', target.checked)
}

async function onSpectateChange(event: Event): Promise<void> {
  const target = event.target as HTMLInputElement | null
  if (!target) return
  await settings.setToggle('spectate', target.checked)
}

async function onPrivacyChange(key: PrivacyKey, event: Event): Promise<void> {
  const target = event.target as HTMLInputElement | null
  if (!target) return
  await settings.setPrivacy(key, target.checked)
}

async function submitPassword(): Promise<void> {
  const ok = await settings.changePassword(oldPassword.value, newPassword.value)
  if (ok) {
    oldPassword.value = ''
    newPassword.value = ''
  }
}

async function toggleWallpaper(): Promise<void> {
  await settings.checkWallpapers()
}

// Phase 5 removed the old panel, so there is no legacy wallpaper manager to
// link to any more. The entry stays visible (players look for it) but explains
// that managing/applying wallpapers is still a migration residual.
const WALLPAPER_MIGRATION_NOTE = '壁纸库管理暂未迁移；本机可用性可以先检查。'

onMounted(() => {
  void settings.loadOwn()
  void settings.loadToggle('replay')
  void settings.loadToggle('spectate')
})
</script>

<template>
  <section
    class="screen settings"
    data-screen="settings"
    data-testid="screen-settings"
    aria-labelledby="screen-settings-title"
  >
    <div class="settings__modal">
      <header class="settings__head">
        <p class="settings__eyebrow">P4 · 设置</p>
        <h1 id="screen-settings-title" class="settings__title" data-testid="settings-heading">设置</h1>
        <p class="settings__hint">回放与观战开关、名片隐私、密码与壁纸入口；改动立即生效。</p>
      </header>

      <div class="settings__layout">
        <nav class="settings__nav" aria-label="设置分区">
          <a href="#settings-audio">音效与音乐</a>
          <a href="#settings-replay">对局回放</a>
          <a href="#settings-spectate">观战</a>
          <a href="#settings-privacy">名片隐私</a>
          <a href="#settings-password">修改密码</a>
          <a href="#settings-wallpaper">动态壁纸</a>
        </nav>

        <div class="settings__panes">

      <section class="settings__block settings__audio" data-testid="settings-audio">
        <h2 class="settings__block-title">音效与背景音乐</h2>
        <div class="settings__audio-row">
          <button
            type="button"
            class="button"
            data-testid="settings-sfx-mute"
            :aria-pressed="audio.sfxMuted"
            @click="audio.toggleSfxMute()"
          >
            {{ audio.sfxMuted ? '音效：已静音' : '音效：开启' }}
          </button>
          <button type="button" class="button" data-testid="settings-sfx-preview" @click="audio.previewSfx()">
            试听
          </button>
        </div>
        <label class="settings__range">
          <span>音效音量</span>
          <input
            type="range"
            min="0"
            max="100"
            step="1"
            :value="audio.sfxVolumePercent"
            data-testid="settings-sfx-volume"
            @input="onSfxVolume"
          />
          <output data-testid="settings-sfx-volume-value">{{ audio.sfxVolumePercent }}%</output>
        </label>

        <div class="settings__audio-row">
          <button
            type="button"
            class="button"
            data-testid="settings-bgm-toggle"
            :aria-pressed="audio.bgmPlaying"
            @click="audio.toggleBgmPlay()"
          >
            {{ audio.bgmPlaying ? '背景音乐：暂停' : '背景音乐：播放' }}
          </button>
          <button
            type="button"
            class="button button--ghost"
            data-testid="settings-bgm-mute"
            :aria-pressed="audio.bgmMuted"
            @click="audio.toggleBgmMute()"
          >
            {{ audio.bgmMuted ? '取消静音' : '静音' }}
          </button>
        </div>
        <label class="settings__range">
          <span>音乐音量</span>
          <input
            type="range"
            min="0"
            max="100"
            step="1"
            :value="audio.bgmVolumePercent"
            data-testid="settings-bgm-volume"
            @input="onBgmVolume"
          />
          <output data-testid="settings-bgm-volume-value">{{ audio.bgmVolumePercent }}%</output>
        </label>
        <p class="settings__note" data-testid="settings-bgm-status" role="status">
          {{ audio.bgmStatus }}（浏览器可能要求先点一下页面才出声）
        </p>
      </section>

    <section v-if="anonymous" class="settings__login" data-testid="settings-login-required">
      <h2>需要先登录</h2>
      <p>回放开关、观战开关、隐私与密码都绑定账号。</p>
      <a class="button" href="/login">前往登录</a>
    </section>
    <p v-else-if="profileFailed" class="settings__state settings__state--error" data-testid="settings-error" role="alert">
      无法加载设置：{{ settings.profileError }}
    </p>

    <template v-else>
      <section id="settings-replay" class="settings__block" data-testid="settings-replay">
        <h2 class="settings__block-title">对局回放</h2>
        <label class="settings__switch">
          <input
            type="checkbox"
            data-testid="settings-allow-replay"
            :checked="settings.replay.value === true"
            :disabled="settings.replay.status !== 'ready' || settings.replay.saving"
            @change="onReplayChange"
          />
          <span>允许保留我的对局回放</span>
        </label>
        <p class="settings__note" data-testid="settings-replay-status" role="status">
          {{ toggleStatus('replay') }}
        </p>
        <p class="settings__note">任一方关闭，这一局就不会留下回放。</p>
      </section>

      <section id="settings-spectate" class="settings__block" data-testid="settings-spectate">
        <h2 class="settings__block-title">观战</h2>
        <label class="settings__switch">
          <input
            type="checkbox"
            data-testid="settings-allow-spectate"
            :checked="settings.spectate.value === true"
            :disabled="settings.spectate.status !== 'ready' || settings.spectate.saving"
            @change="onSpectateChange"
          />
          <span>允许他人观战我的对局</span>
        </label>
        <p class="settings__note" data-testid="settings-spectate-status" role="status">
          {{ toggleStatus('spectate') }}
        </p>
        <p class="settings__note">观众只能看到双方已轰过的格子，看不到你的船位。</p>
      </section>

      <section id="settings-privacy" class="settings__block" data-testid="settings-privacy">
        <h2 class="settings__block-title">名片隐私</h2>
        <label v-for="row in privacyRows" :key="row.key" class="settings__switch">
          <input
            type="checkbox"
            :data-testid="row.testid"
            :checked="settings.privacy[row.key]"
            :disabled="!privacyReady || settings.privacySaving"
            @change="onPrivacyChange(row.key, $event)"
          />
          <span>
            {{ row.label }}
            <small class="settings__switch-hint">{{ row.hint }}</small>
          </span>
        </label>
        <p class="settings__note" data-testid="settings-privacy-status" role="status">{{ privacyStatus }}</p>
      </section>

      <section id="settings-password" class="settings__block" data-testid="settings-password">
        <h2 class="settings__block-title">修改密码</h2>
        <form class="settings__form" @submit.prevent="submitPassword">
          <label>
            <span>原密码</span>
            <input
              v-model="oldPassword"
              type="password"
              autocomplete="current-password"
              data-testid="settings-old-password"
            />
          </label>
          <label>
            <span>新密码（至少 6 位）</span>
            <input
              v-model="newPassword"
              type="password"
              autocomplete="new-password"
              data-testid="settings-new-password"
            />
          </label>
          <button type="submit" class="button" data-testid="settings-change-password" :disabled="settings.passwordSaving">
            更改密码
          </button>
        </form>
        <p
          v-if="settings.passwordMessage"
          class="settings__note"
          :class="{ 'is-error': settings.passwordError }"
          data-testid="settings-password-msg"
          role="status"
        >
          {{ settings.passwordMessage }}
        </p>
      </section>

      <section id="settings-wallpaper" class="settings__block" data-testid="settings-wallpaper">
        <h2 class="settings__block-title">动态壁纸</h2>
        <p class="settings__note">
          壁纸库（扫描本机 / 选择文件）还在迁移中；这里可以先检查本机能不能用。
        </p>
        <div class="settings__wallpaper-actions">
          <button
            type="button"
            class="button"
            data-testid="settings-wallpaper-entry"
            disabled
            :title="WALLPAPER_MIGRATION_NOTE"
          >
            壁纸库管理（暂未迁移）
          </button>
          <button type="button" class="button button--ghost" data-testid="settings-wallpaper-check" @click="toggleWallpaper">
            检查本机壁纸库
          </button>
        </div>
        <p class="settings__note" data-testid="settings-wallpaper-status" role="status">{{ wallpaperStatus }}</p>
      </section>

      <footer class="settings__actions">
        <button type="button" class="button button--ghost" data-testid="settings-back" @click="router.push({ name: 'start' })">
          返回首页
        </button>
      </footer>
    </template>
        </div>
      </div>
    </div>
  </section>
</template>

<style scoped>
/* C+ settings: one 1040px modal, left section rail + right scrolling pane. */
.settings {
  align-items: center;
  justify-content: center;
  padding: 24px;
}

.settings__modal {
  display: flex;
  flex-direction: column;
  width: 1040px;
  max-width: 100%;
  max-height: calc(100vh - 104px);
  overflow: hidden;
  border: 1px solid var(--panel-line);
  border-radius: var(--radius);
  background: var(--panel);
  box-shadow: var(--shadow-panel);
}

.settings__head {
  flex: 0 0 auto;
  padding: 16px 22px 12px;
  border-bottom: 1px dashed var(--line-dash);
}

.settings__eyebrow {
  margin: 0 0 2px;
  color: #8f9bc4;
  font-size: 10px;
  letter-spacing: 0.18em;
  text-transform: uppercase;
}

.settings__title {
  margin: 0;
  font-size: 24px;
  line-height: 1.2;
}

.settings__hint {
  margin: 2px 0 0;
  color: var(--text-muted);
  font-size: 12px;
}

.settings__layout {
  display: grid;
  grid-template-columns: 182px minmax(0, 1fr);
  gap: 18px;
  min-height: 0;
  padding: 16px 22px 20px;
}

.settings__nav {
  display: flex;
  flex-direction: column;
  gap: 2px;
  align-self: start;
  padding: 8px;
  border: 1px solid var(--panel-line);
  border-radius: 10px;
  background: rgba(13, 17, 34, 0.5);
}

.settings__nav a {
  padding: 10px 12px;
  border: 1px solid transparent;
  border-radius: 8px;
  color: var(--text-muted);
  font-size: 13px;
}

.settings__nav a:hover {
  border-color: rgba(124, 92, 240, 0.5);
  background: var(--accent-soft);
  color: var(--text);
}

.settings__nav a:first-child {
  border-color: rgba(124, 92, 240, 0.55);
  background: var(--accent-soft);
  color: var(--text);
}

.settings__panes {
  display: grid;
  align-content: start;
  gap: 12px;
  min-height: 0;
  padding-right: 8px;
  overflow-y: auto;
}

.settings__login,
.settings__state {
  margin: 0;
  padding: 14px 16px;
  border: 1px dashed var(--border);
  border-radius: var(--radius);
  background: rgba(13, 17, 34, 0.55);
  color: var(--text-muted);
  font-size: 13px;
}

.settings__state--error {
  border-color: var(--danger);
  color: var(--danger);
}

.settings__login h2 {
  margin: 0 0 6px;
  color: var(--text);
  font-size: 18px;
}

.settings__login p {
  margin: 0 0 10px;
}

.settings__block {
  display: grid;
  gap: 10px;
  padding: 14px 16px;
  border: 1px solid var(--panel-line);
  border-radius: 10px;
  background: rgba(13, 17, 34, 0.5);
}

.settings__block-title {
  margin: 0;
  padding-bottom: 8px;
  border-bottom: 1px dashed var(--line-dash);
  color: var(--text);
  font-size: 12px;
  font-weight: 600;
  letter-spacing: 0.08em;
}

.settings__switch {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  font-size: 13px;
  cursor: pointer;
}

.settings__switch input {
  width: 18px;
  height: 18px;
  margin: 2px 0 0;
  accent-color: var(--accent);
}

.settings__switch-hint {
  display: block;
  margin-top: 1px;
  color: var(--text-muted);
  font-size: 11px;
}

.settings__note {
  margin: 0;
  color: var(--text-muted);
  font-size: 12px;
}

.settings__note.is-error {
  color: var(--danger);
}

.settings__form {
  display: grid;
  gap: 10px;
  max-width: 340px;
}

.settings__form label {
  display: grid;
  gap: 4px;
  color: var(--text-muted);
  font-size: 12px;
}

.settings__form input {
  padding: 8px 10px;
  border: 1px solid var(--border);
  border-radius: 8px;
  background: var(--bg-sunken);
  color: var(--text);
  font: inherit;
}

.settings__form button {
  justify-self: start;
}

.settings__wallpaper-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.settings__actions {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  padding-top: 4px;
}

.settings__actions .button {
  min-height: 40px;
  padding: 8px 20px;
}

.settings__actions [data-testid='settings-back'] {
  border-color: var(--border-strong);
  background: rgba(13, 17, 34, 0.72);
  color: var(--text-muted);
}

.settings__audio-row {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.settings__range {
  display: flex;
  align-items: center;
  gap: 10px;
  font-size: 13px;
  color: var(--text-muted);
}

.settings__range input[type='range'] {
  flex: 1;
  min-width: 120px;
  accent-color: var(--accent);
}

.settings__range output {
  min-width: 42px;
  text-align: right;
  color: var(--text);
  font-variant-numeric: tabular-nums;
}

@media (max-width: 860px) {
  .settings {
    justify-content: flex-start;
    padding: 12px;
  }

  .settings__modal {
    max-height: none;
  }

  .settings__layout {
    grid-template-columns: minmax(0, 1fr);
    gap: 10px;
    padding: 12px;
  }

  .settings__nav {
    flex-direction: row;
    flex-wrap: wrap;
  }

  .settings__nav a {
    padding: 8px 10px;
    font-size: 12px;
  }

  .settings__panes {
    overflow: visible;
    padding-right: 0;
  }
}
</style>