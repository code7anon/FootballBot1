import asyncio
from app.config import get_settings
from app.db import SessionLocal
from app.services.worker import run_cycle

settings = get_settings()

async def main():
    while True:
        db = SessionLocal()
        try:
            await run_cycle(db)
        except Exception as exc:
            print(f"worker cycle failed: {exc}", flush=True)
        finally:
            db.close()
        await asyncio.sleep(settings.poll_seconds)

if __name__ == "__main__":
    asyncio.run(main())
