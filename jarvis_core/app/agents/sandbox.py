import os
import sys
import subprocess
from typing import Dict
from app.database import get_db_connection

def run_agent_script_in_sandbox(script_name: str, code_content: str) -> Dict:
    """Compiles client agent scripts inside an isolated local folder path to enable recursive correction."""
    sandbox_dir = os.path.abspath("./app/agents/generated/deliverables")
    os.makedirs(sandbox_dir, exist_ok=True)

    target_file_path = os.path.join(sandbox_dir, script_name)
    with open(target_file_path, "w", encoding="utf-8") as f:
        f.write(code_content)

    try:
        result = subprocess.run(
            [sys.executable, target_file_path],
            capture_output=True, text=True, timeout=15
        )

        if result.returncode == 0:
            return {"status": "SUCCESS", "output": result.stdout}

        conn = get_db_connection()
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO system_health_log (log_level, subsystem, message, traceback) VALUES (%s, %s, %s, %s);",
                ("ERROR", "SANDBOX_COMPILER", f"Script runtime failure inside: {script_name}", result.stderr)
            )
        conn.commit()
        conn.close()

        return {"status": "CRASHED", "error_trace": result.stderr}
    except subprocess.TimeoutExpired:
        return {"status": "TIMEOUT", "error_trace": "Process runtime overflow limits hit."}
