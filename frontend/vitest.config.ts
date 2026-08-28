import vue from '@vitejs/plugin-vue'
import { defineConfig } from 'vitest/config'

export default defineConfig({
  plugins: [vue()],
  test: {
    clearMocks: true,
    environment: 'happy-dom',
    include: ['tests/unit/**/*.spec.ts'],
    restoreMocks: true,
  },
})
