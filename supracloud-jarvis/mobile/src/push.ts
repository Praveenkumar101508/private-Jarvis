import * as Notifications from "expo-notifications";
import { Platform } from "react-native";
import { registerDevice } from "./api";

// Ask for permission, get this device's Expo push token, and register it with IRA
// (POST /mobile/devices). Returns the token, or null if permission was denied.
export async function registerForPush(): Promise<string | null> {
  const existing = await Notifications.getPermissionsAsync();
  let status = existing.status;
  if (status !== "granted") {
    status = (await Notifications.requestPermissionsAsync()).status;
  }
  if (status !== "granted") return null;

  const { data: token } = await Notifications.getExpoPushTokenAsync();
  await registerDevice(token, Platform.OS);
  return token;
}
