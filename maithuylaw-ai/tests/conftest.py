import os

os.environ.setdefault("ENVIRONMENT", "development")
os.environ.setdefault("LLM_PROVIDER", "none")
os.environ.setdefault("MAITHUYLAW_SESSION_SECRET", "test-session-secret")
os.environ.setdefault("MAITHUYLAW_RATE_LIMIT_PER_MINUTE", "1000")
os.environ.setdefault("MAITHUYLAW_DAILY_LIMIT", "5000")
