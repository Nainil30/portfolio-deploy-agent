
# main.py
"""
Entry point for the Portfolio Deployment Agent.

USAGE:
    python main.py              Run the full agent workflow
    python main.py --dashboard  Launch the Streamlit dashboard

This is the file you run. Everything else is imported.
"""

import sys


def main():
    if "--dashboard" in sys.argv:
        import subprocess
        subprocess.run(["streamlit", "run", "dashboard/app.py"])
        return

    print()
    print("=" * 60)
    print("  PORTFOLIO DEPLOYMENT AGENT")
    print("  Powered by LangGraph + Groq")
    print("=" * 60)
    print()

    from src.graph.workflow import run_agent

    try:
        final_state = run_agent()

        if final_state.get("error"):
            print(f"\n❌ Error: {final_state['error']}")
        elif final_state.get("notification_sent"):
            print("\n✅ Agent completed successfully!")
        else:
            print("\n⚠️  Agent finished without sending notification.")

    except KeyboardInterrupt:
        print("\n\n⏹️  Agent stopped by user.")
    except Exception as e:
        print(f"\n❌ Agent failed: {e}")
        raise


if __name__ == "__main__":
    main()