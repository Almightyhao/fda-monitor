import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vitejs.dev/config/
export default defineConfig({
  plugins: [react()],
  // ⚠️ 注意：下面這一行非常重要！
  // 如果您的 GitHub 倉庫叫 fda-monitor，這裡就填 '/fda-monitor/'
  base: '/fda-monitor/', 
})