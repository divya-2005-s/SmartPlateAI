import type { CapacitorConfig } from '@capacitor/cli'

const serverUrl = process.env.CAP_SERVER_URL?.trim() || undefined

const config: CapacitorConfig = {
  appId: 'com.example.smartplateai',
  appName: 'SmartPlateAI',
  webDir: 'dist',
  server: serverUrl ? { url: serverUrl, cleartext: serverUrl.startsWith('http://') } : undefined,
}

export default config
