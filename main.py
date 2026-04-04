import asyncio
import json
from fastapi import FastAPI, Request, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, StreamingResponse
import os
from pydantic import BaseModel
from typing import Optional
from api.storage import RepoStorage
from api.git_providers import fetch_github_status, fetch_forgejo_status, fetch_github_logs, fetch_forgejo_logs, fetch_github_artifacts, fetch_forgejo_artifacts

app = FastAPI()
storage = RepoStorage()

class RepoItem(BaseModel):
    provider: str
    owner: str
    repo: str
    custom_links: Optional[list] = None

LOGS_DIR = os.environ.get("LOGS_DIR", "logs")
os.makedirs(LOGS_DIR, exist_ok=True)

MAX_LOG_SIZE = 2 * 1024 * 1024  # 2MB

# Mount static files
os.makedirs("static", exist_ok=True)
app.mount("/static", StaticFiles(directory="static"), name="static")

@app.get("/")
async def read_index():
    return FileResponse("static/index.html")

@app.get("/llms.txt")
async def read_llms_txt():
    return FileResponse("static/llms.txt")

@app.get("/api/artifacts")
async def get_artifacts(provider: str, owner: str, repo: str):
    github_token = os.environ.get("GITHUB_TOKEN", "")
    forgejo_token = os.environ.get("FORGEJO_TOKEN", "")
    forgejo_url = os.environ.get("FORGEJO_URL", "")
    
    if provider == "github":
        return await fetch_github_artifacts(owner, repo, github_token)
    elif provider == "forgejo":
        return await fetch_forgejo_artifacts(owner, repo, forgejo_token, forgejo_url)
    return {"error": "Unknown provider"}

@app.post("/api/logs")
async def post_logs(provider: str, owner: str, repo: str, request: Request):
    # To prevent DDOS from massive payloads, read the request stream in chunks
    # and buffer only the last MAX_LOG_SIZE bytes in a cyclic buffer
    buffer = bytearray()
    
    async for chunk in request.stream():
        buffer.extend(chunk)
        if len(buffer) > MAX_LOG_SIZE * 2:
            # Keep the buffer from growing unboundedly, truncate to last MAX_LOG_SIZE
            buffer = buffer[-MAX_LOG_SIZE:]
            
    # The final log text is the tail of the buffer
    log_text = buffer.decode('utf-8', errors='replace')
        
    # Apply truncation to log_text if it exceeds the limit
    if len(log_text) > MAX_LOG_SIZE:
        log_text = "[TRUNCATED...]\n" + log_text[-MAX_LOG_SIZE:]

    safe_provider = "".join(c for c in provider if c.isalnum() or c in "-_")
    safe_owner = "".join(c for c in owner if c.isalnum() or c in "-_")
    safe_repo = "".join(c for c in repo if c.isalnum() or c in "-_")
    
    if not safe_provider or not safe_owner or not safe_repo:
        raise HTTPException(status_code=400, detail="Invalid provider, owner, or repo.")
    
    filename = f"{safe_provider}_{safe_owner}_{safe_repo}_latest.log"
    filepath = os.path.join(LOGS_DIR, filename)
    
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(log_text)
        
    return {"message": "Log saved successfully", "file": filename}

@app.get("/api/logs")
async def get_logs(provider: str, owner: str, repo: str):
    safe_provider = "".join(c for c in provider if c.isalnum() or c in "-_")
    safe_owner = "".join(c for c in owner if c.isalnum() or c in "-_")
    safe_repo = "".join(c for c in repo if c.isalnum() or c in "-_")
    
    filename = f"{safe_provider}_{safe_owner}_{safe_repo}_latest.log"
    filepath = os.path.join(LOGS_DIR, filename)
    
    if os.path.exists(filepath):
        with open(filepath, "r", encoding="utf-8") as f:
            return {"log": f.read()}

    github_token = os.environ.get("GITHUB_TOKEN", "")
    forgejo_token = os.environ.get("FORGEJO_TOKEN", "")
    forgejo_url = os.environ.get("FORGEJO_URL", "")
    
    if provider == "github":
        return {"log": await fetch_github_logs(owner, repo, github_token)}
    elif provider == "forgejo":
        return {"log": await fetch_forgejo_logs(owner, repo, forgejo_token, forgejo_url)}
    return {"log": "Unknown provider"}

@app.get("/api/status")
async def get_status():
    repos = storage.get_repos()
    tasks = []
    github_token = os.environ.get("GITHUB_TOKEN", "")
    forgejo_token = os.environ.get("FORGEJO_TOKEN", "")
    forgejo_url = os.environ.get("FORGEJO_URL", "")

    for r in repos:
        if r["provider"] == "github":
            tasks.append(fetch_github_status(r["owner"], r["repo"], github_token))
        elif r["provider"] == "forgejo":
            tasks.append(fetch_forgejo_status(r["owner"], r["repo"], forgejo_token, forgejo_url))

    results = await asyncio.gather(*tasks)
    
    for i, r in enumerate(repos):
        if i < len(results):
            res = results[i]
            res["custom_links"] = r.get("custom_links", [])
            
            # Detect if a completely new run has started
            current_url = res.get("url")
            saved_url = r.get("last_run_url")
            
            if current_url and current_url != "#" and current_url != saved_url:
                # Update the stored last_run_url so we don't clear the log again for this run
                storage.update_repo_run_url(res.get("provider"), res.get("owner"), res.get("repo"), current_url)
                
                # Clear any old local log file from previous runs
                safe_provider = "".join(c for c in res.get("provider", "") if c.isalnum() or c in "-_")
                safe_owner = "".join(c for c in res.get("owner", "") if c.isalnum() or c in "-_")
                safe_repo = "".join(c for c in res.get("repo", "") if c.isalnum() or c in "-_")
                
                if safe_provider and safe_owner and safe_repo:
                    filepath = os.path.join(LOGS_DIR, f"{safe_provider}_{safe_owner}_{safe_repo}_latest.log")
                    if os.path.exists(filepath):
                        try:
                            os.remove(filepath)
                        except Exception:
                            pass

    return results

@app.post("/api/repos")
async def add_repo(item: RepoItem):
    storage.add_repo(item.provider, item.owner, item.repo, item.custom_links)
    return {"message": "added"}

@app.delete("/api/repos")
async def remove_repo(item: RepoItem):
    storage.remove_repo(item.provider, item.owner, item.repo)
    return {"message": "removed"}

@app.get("/api/wait")
async def wait_status(provider: str, owner: str, repo: str):
    github_token = os.environ.get("GITHUB_TOKEN", "")
    forgejo_token = os.environ.get("FORGEJO_TOKEN", "")
    forgejo_url = os.environ.get("FORGEJO_URL", "")

    async def event_stream():
        yield "waiting for complete."
        while True:
            if provider == "github":
                result = await fetch_github_status(owner, repo, github_token)
            elif provider == "forgejo":
                result = await fetch_forgejo_status(owner, repo, forgejo_token, forgejo_url)
            else:
                yield "\nError: Unknown provider\n"
                break

            status = result.get("status")
            if status in ["running", "in_progress", "queued", "waiting", "requested", "pending"]:
                yield "."
                await asyncio.sleep(10)
            else:
                yield f"\nStatus changed to {status}\n{json.dumps(result)}\n"
                break

    return StreamingResponse(event_stream(), media_type="text/plain")