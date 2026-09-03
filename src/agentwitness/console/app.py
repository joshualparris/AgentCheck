import os
import json
import asyncio
from pathlib import Path
from fastapi import FastAPI
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

app = FastAPI()

app.mount("/static", StaticFiles(directory=Path(__file__).parent / "static"), name="static")

@app.get("/")
def get_index():
    with open(Path(__file__).parent / "static" / "index.html", "r") as f:
        return HTMLResponse(content=f.read())

async def file_tail(path: Path):
    if not path.exists():
        # wait until it exists
        while not path.exists():
            await asyncio.sleep(1)
            
    with open(path, "r", encoding="utf-8") as f:
        f.seek(0, 2) # go to end
        while True:
            line = f.readline()
            if not line:
                await asyncio.sleep(0.5)
                continue
            yield line

@app.get("/api/stream")
async def stream():
    # Tail the transcript
    conv_id = os.environ.get("AW_CONVERSATION_ID", "")
    app_data = Path(os.environ.get("APPDATA")) / ".gemini" / "antigravity"
    transcript_path = app_data / "brain" / conv_id / ".system_generated" / "logs" / "transcript.jsonl"
    
    aw_dir = Path(os.environ.get("AW_DATA_DIR", ".agentwitness"))
    receipts_path = aw_dir / "receipts.jsonl"

    async def event_generator():
        # Let's just tail the transcript for now, plus any receipts updates?
        # Actually, reading both asynchronously is a bit complex in one generator.
        # Let's write an async tailer for both files and interleave them.
        import asyncio
        q = asyncio.Queue()

        async def tail_file(path, file_type):
            if not path.exists():
                while not path.exists():
                    await asyncio.sleep(1)
            with open(path, "r", encoding="utf-8") as f:
                # To get existing history
                f.seek(0)
                while True:
                    line = f.readline()
                    if not line:
                        await asyncio.sleep(0.5)
                        continue
                    await q.put((file_type, line))

        asyncio.create_task(tail_file(transcript_path, "transcript"))
        asyncio.create_task(tail_file(receipts_path, "receipt"))

        while True:
            file_type, line = await q.get()
            try:
                data = json.loads(line)
            except:
                continue
                
            payload = json.dumps({"type": file_type, "data": data})
            yield f"data: {payload}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")
