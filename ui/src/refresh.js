import { inject, provide, ref, watch } from 'vue'

const refreshKey = Symbol('antidetect-refresh')

export function useRefreshSignal() {
  const tick = ref(0)
  provide(refreshKey, tick)
  return tick
}

export function useOnRefresh(handler) {
  const tick = inject(refreshKey, null)
  if (tick) watch(tick, () => handler())
}
