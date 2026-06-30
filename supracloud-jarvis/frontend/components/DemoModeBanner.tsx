// Visible "Demo Mode" banner for the IRA portable demo.
// Renders only when NEXT_PUBLIC_IRA_DEMO_MODE=true (set by docker-compose.portable.yml),
// so normal deployments never show it.
export default function DemoModeBanner() {
  if (process.env.NEXT_PUBLIC_IRA_DEMO_MODE !== "true") return null;
  return (
    <div
      role="status"
      style={{
        position: "sticky",
        top: 0,
        zIndex: 1000,
        width: "100%",
        textAlign: "center",
        padding: "6px 12px",
        fontSize: "13px",
        fontWeight: 600,
        letterSpacing: "0.02em",
        color: "#0a0a0a",
        background: "linear-gradient(90deg,#f5d90a,#f0a020)",
      }}
    >
      DEMO MODE — local-first, egress off. External tools, shell, and destructive
      actions are disabled.
    </div>
  );
}
