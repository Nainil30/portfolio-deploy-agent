# main.py
"""
Entry point for the Portfolio Deployment Agent.

USAGE:
    python main.py            Full run — saves deployment, sends Telegram
    python main.py --check    Analysis only — shows recommendation, saves nothing
    python main.py --reset    Clear this month's deployment history
    python main.py --dashboard  Launch Streamlit dashboard
"""

import sys


def main():
    args = sys.argv[1:]

    if "--dashboard" in args:
        import subprocess
        subprocess.run(["python", "-m", "streamlit", "run", "dashboard/app.py"])
        return

    if "--reset" in args:
        _reset_month()
        return

    check_only = "--check" in args

    if check_only:
        print()
        print("=" * 60)
        print("  PORTFOLIO DEPLOYMENT AGENT — CHECK MODE")
        print("  Analysis only. Nothing saved. Nothing sent.")
        print("=" * 60)
    else:
        print()
        print("=" * 60)
        print("  PORTFOLIO DEPLOYMENT AGENT")
        print("  Powered by LangGraph + Groq")
        print("=" * 60)

    print()

    from src.graph.workflow import run_agent

    try:
        final_state = run_agent(check_only=check_only)

        if final_state.get("error"):
            print(f"\n❌ Error: {final_state['error']}")
        elif check_only:
            print("\n✅ Check complete. Nothing was saved or sent.")
            print("   Run without --check to deploy for real.")
        elif final_state.get("notification_sent"):
            print("\n✅ Agent completed successfully!")
        else:
            print("\n⚠️  Agent finished without sending notification.")

    except KeyboardInterrupt:
        print("\n\n⏹️  Stopped by user.")
    except Exception as e:
        print(f"\n❌ Agent failed: {e}")
        raise


def _reset_month():
    """Clear this month's deployment records so you can re-run."""
    from datetime import datetime
    from src.tools.database import _connect

    month = datetime.now().strftime("%Y-%m")
    conn = _connect()
    deleted = conn.execute(
        "DELETE FROM deployments WHERE month = ?", (month,)
    ).rowcount
    conn.commit()
    conn.close()
    print(f"Cleared {deleted} deployment record(s) for {month}.")
    print("You can now run: python main.py")


if __name__ == "__main__":
    main()
