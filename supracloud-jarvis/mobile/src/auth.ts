import * as SecureStore from "expo-secure-store";

// The JWT access token is kept in the OS secure store (Keychain / Keystore).
const KEY = "ira_access_token";

export async function getToken(): Promise<string | null> {
  return SecureStore.getItemAsync(KEY);
}

export async function setToken(token: string): Promise<void> {
  await SecureStore.setItemAsync(KEY, token);
}

export async function clearToken(): Promise<void> {
  await SecureStore.deleteItemAsync(KEY);
}
