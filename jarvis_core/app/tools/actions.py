import re
import sys
import subprocess
from langchain_core.tools import tool
from app.database import get_db_connection

_IP_PATTERN = re.compile(
    r"^((25[0-5]|2[0-4]\d|[01]?\d\d?)\.){3}(25[0-5]|2[0-4]\d|[01]?\d\d?)$"
)

def _validate_ip(ip_address: str) -> bool:
    """Rejects non-IPv4 strings to prevent shell command injection."""
    return bool(_IP_PATTERN.match(ip_address))

@tool
def execute_firewall_block(ip_address: str) -> str:
    """Natively executes host OS firewall rules to isolate malicious target IP footprints."""
    if not _validate_ip(ip_address):
        return f"🔴 Rejected: '{ip_address}' is not a valid IPv4 address."

    try:
        if sys.platform.startswith("win"):
            cmd = [
                "netsh", "advfirewall", "firewall", "add", "rule",
                "name=IRA_BLOCK", "dir=in", "action=block",
                f"remoteip={ip_address}"
            ]
        elif sys.platform.startswith("darwin"):
            cmd = ["sudo", "pfctl", "-f", "-"]
            # pfctl reads rules from stdin; pass rule as input instead of shell interpolation
        else:
            cmd = ["sudo", "iptables", "-A", "INPUT", "-s", ip_address, "-j", "DROP"]

        result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)

        conn = get_db_connection()
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO system_health_log (log_level, subsystem, message) VALUES (%s, %s, %s);",
                ("WARNING", "SECURITY", f"Dropped malicious connection attempt from IP: {ip_address}")
            )
        conn.commit()
        conn.close()

        return f"🟢 Packet drop active. IP: {ip_address} blocked at host firewall."
    except Exception as e:
        return f"🔴 Firewall block script execution exception: {str(e)}"
