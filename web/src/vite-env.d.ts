/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** Base path for the API; `/api` by default (stripped by the dev proxy). */
  readonly VITE_API_BASE?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}