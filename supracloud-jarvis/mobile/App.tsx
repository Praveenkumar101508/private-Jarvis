import React, { useEffect, useState } from "react";
import {
  ActivityIndicator,
  Alert,
  Button,
  SafeAreaView,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  View,
} from "react-native";

import { clearToken, getToken, setToken } from "./src/auth";
import { listTasks, login, ping, submitTask, TaskResult } from "./src/api";
import { registerForPush } from "./src/push";

export default function App() {
  const [booting, setBooting] = useState(true);
  const [token, setTok] = useState<string | null>(null);

  useEffect(() => {
    getToken().then((t) => {
      setTok(t);
      setBooting(false);
    });
  }, []);

  if (booting) {
    return (
      <SafeAreaView style={styles.center}>
        <ActivityIndicator />
      </SafeAreaView>
    );
  }
  return token ? <Home onLogout={() => clearToken().then(() => setTok(null))} />
               : <Login onAuthed={setTok} />;
}

function Login({ onAuthed }: { onAuthed: (t: string) => void }) {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);

  async function doLogin() {
    setBusy(true);
    try {
      const t = await login(username.trim(), password);
      await setToken(t);
      onAuthed(t);
    } catch (e: any) {
      Alert.alert("Login failed", String(e?.message ?? e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <SafeAreaView style={styles.container}>
      <Text style={styles.title}>IRA</Text>
      <TextInput style={styles.input} placeholder="Username" autoCapitalize="none"
        value={username} onChangeText={setUsername} />
      <TextInput style={styles.input} placeholder="Password" secureTextEntry
        value={password} onChangeText={setPassword} />
      {busy ? <ActivityIndicator /> : <Button title="Sign in" onPress={doLogin} />}
    </SafeAreaView>
  );
}

function Home({ onLogout }: { onLogout: () => void }) {
  const [status, setStatus] = useState("…");
  const [tasks, setTasks] = useState<any[]>([]);
  const [pending, setPending] = useState<TaskResult | null>(null);

  const refresh = () => listTasks().then((d) => setTasks(d.tasks ?? [])).catch(() => {});

  useEffect(() => {
    ping().then((d) => setStatus(`connected · v${d.version}`)).catch((e) => setStatus(`offline (${e})`));
    refresh();
  }, []);

  async function enablePush() {
    try {
      const t = await registerForPush();
      Alert.alert(t ? "Notifications enabled" : "Permission denied");
    } catch (e: any) {
      Alert.alert("Push setup failed", String(e?.message ?? e));
    }
  }

  // Demo: submit the gated "email" task. Side-effecting → confirmation required first.
  async function sendDemoEmail() {
    try {
      const res = await submitTask("email", {
        to: "you@example.com", subject: "Hello from IRA", body: "Queued from the phone.",
      });
      if (res.status === "confirmation_required") {
        setPending(res);
      } else {
        Alert.alert("Queued", `Task ${res.task?.id}`);
        refresh();
      }
    } catch (e: any) {
      Alert.alert("Submit failed", String(e?.message ?? e));
    }
  }

  async function confirmPending() {
    if (!pending?.token) return;
    try {
      const res = await submitTask("email", {
        to: "you@example.com", subject: "Hello from IRA", body: "Queued from the phone.",
      }, pending.token);
      setPending(null);
      Alert.alert("Confirmed", `Task ${res.task?.id ?? ""} queued`);
      refresh();
    } catch (e: any) {
      Alert.alert("Confirm failed", String(e?.message ?? e));
    }
  }

  return (
    <SafeAreaView style={styles.container}>
      <ScrollView>
        <Text style={styles.title}>IRA</Text>
        <Text style={styles.muted}>{status}</Text>

        <View style={styles.row}><Button title="Enable notifications" onPress={enablePush} /></View>
        <View style={styles.row}><Button title="Send demo email (gated)" onPress={sendDemoEmail} /></View>

        {pending && (
          <View style={styles.card}>
            <Text style={styles.cardTitle}>Confirm action</Text>
            <Text style={styles.muted}>{pending.preview}</Text>
            <Button title="Approve & run" onPress={confirmPending} />
          </View>
        )}

        <Text style={styles.section}>Recent tasks</Text>
        <Button title="Refresh" onPress={refresh} />
        {tasks.map((t) => (
          <View key={t.id} style={styles.card}>
            <Text>{t.type} — {t.status}</Text>
          </View>
        ))}

        <View style={styles.logout}><Button title="Sign out" color="#a00" onPress={onLogout} /></View>
      </ScrollView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  center: { flex: 1, justifyContent: "center", alignItems: "center" },
  container: { flex: 1, padding: 20, gap: 10 },
  title: { fontSize: 32, fontWeight: "700", marginTop: 20 },
  section: { fontSize: 18, fontWeight: "600", marginTop: 20 },
  muted: { color: "#666" },
  input: { borderWidth: 1, borderColor: "#ccc", borderRadius: 8, padding: 12 },
  row: { marginTop: 8 },
  card: { borderWidth: 1, borderColor: "#eee", borderRadius: 8, padding: 12, marginTop: 8, gap: 6 },
  cardTitle: { fontWeight: "600" },
  logout: { marginTop: 30, marginBottom: 40 },
});
