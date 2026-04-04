import asyncio
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
import os
from pydantic import BaseModel
from typing import Optional
from api.storage import RepoStorage
from api.git_providers import fetch_github_status, fetch_forgejo_status, fetch_github_logs, fetch_forgejo_logs

app = FastAPI()
storage = RepoStorage()

class RepoItem(BaseModel):
    provider: str
    owner: str
    repo: str
    custom_links: Optional[list] = None

# Mount static files
os.makedirs("static", exist_ok=True)
app.mount("/static", StaticFiles(directory="static"), name="static")

@app.get("/")
async def read_index():
    return FileResponse("static/index.html")

@app.get("/api/logs")
async def get_logs(provider: str, owner: str, repo: str):
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
            results[i]["custom_links"] = r.get("custom_links", [])

    return results

@app.post("/api/repos")
async def add_repo(item: RepoItem):
    storage.add_repo(item.provider, item.owner, item.repo, item.custom_links)
    return {"message": "added"}

@app.delete("/api/repos")
async def remove_repo(item: RepoItem):
    storage.remove_repo(item.provider, item.owner, item.repo)
    return {"message": "removed"}