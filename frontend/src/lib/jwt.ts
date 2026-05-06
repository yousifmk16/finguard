export interface JwtPayload {
  sub?: string;
  role?: string;
  iat?: number;
  exp?: number;
  [key: string]: unknown;
}

function base64UrlDecode(input: string): string {
  const padded = input.replace(/-/g, "+").replace(/_/g, "/").padEnd(
    input.length + ((4 - (input.length % 4)) % 4),
    "=",
  );
  const binary = atob(padded);
  // Convert binary string to UTF-8 string for non-ASCII safety.
  const bytes = Uint8Array.from(binary, (ch) => ch.charCodeAt(0));
  return new TextDecoder("utf-8").decode(bytes);
}

/**
 * Read the payload of a JWT without verifying its signature. The server is
 * still the source of truth — this is only used to surface non-secret claims
 * (sub, role, exp) inside the UI.
 */
export function decodeJwtPayload(token: string): JwtPayload | null {
  const parts = token.split(".");
  if (parts.length !== 3) return null;
  try {
    return JSON.parse(base64UrlDecode(parts[1])) as JwtPayload;
  } catch {
    return null;
  }
}
