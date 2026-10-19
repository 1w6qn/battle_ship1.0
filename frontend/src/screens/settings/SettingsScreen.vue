<script setup lang="ts">
import ScreenScaffold from '../../components/ScreenScaffold.vue'
</script>

<template>
  <ScreenScaffold
    screen="settings"
    title="设置"
    hint="音效、壁纸与隐私开关（#28 迁移）。"
  >
    <div class="screen__actions">
      <button type="button" class="button" data-testid="settings-primary-action">保存设置</button>
      <p class="screen__note">
        占位组件：路由 / 错误边界 / 构建产物门禁可用；业务逻辑见后续票据。
      </p>
    </div>
  </ScreenScaffold>
</template>
