/// <reference types="vite/client" />

declare global {
  interface Window {
    __BASELINER__?: {
      API_BASE_URL?: string
    }
  }
}

export {}
