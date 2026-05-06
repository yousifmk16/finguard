import { apiFetch } from "@/lib/api";
import type { UserRole } from "./AuthContext";

export interface LoginRequestBody {
  email: string;
  password: string;
}

export interface TokenResponse {
  access_token: string;
  token_type: "bearer";
  expires_in: number;
  role: UserRole;
}

export function loginRequest(body: LoginRequestBody, signal?: AbortSignal): Promise<TokenResponse> {
  return apiFetch<TokenResponse>("/auth/login", {
    method: "POST",
    body,
    signal,
  });
}
