interface ImportMetaEnvShape {
  readonly VITE_API_BASE_URL?: string;
}

const meta = import.meta as unknown as { env: ImportMetaEnvShape };

export const API_BASE_URL: string = meta.env.VITE_API_BASE_URL ?? "/api/v1";
