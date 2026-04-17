import httpx
import logging
from enum import Enum
from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any
from fastapi import APIRouter, HTTPException, Query, Path, Depends
from api.auth import get_current_user
from api.config import ConfigManager, ProviderType

logger = logging.getLogger(__name__)

config_manager = ConfigManager()

router = APIRouter(prefix="/api/explore", tags=["explore"])

class NodeType(str, Enum):
    PROVIDER_ROOT = "PROVIDER_ROOT"
    ORGANIZATION = "ORGANIZATION"
    USER = "USER"
    REPOSITORY = "REPOSITORY"
    FOLDER = "FOLDER"
    WORKFLOW = "WORKFLOW"
    JOB = "JOB"

class Node(BaseModel):
    id: str = Field(..., description="Unique identifier for the node")
    name: str = Field(..., description="Display name of the node")
    type: NodeType = Field(..., description="Type of the node in the hierarchy")
    path: str = Field(..., description="Hierarchical path to this node")
    has_children: bool = Field(default=False, description="Whether this node can be expanded further")
    url: Optional[str] = Field(default=None, description="External URL to view this node")
    metadata: Optional[Dict[str, Any]] = Field(default=None, description="Provider-specific metadata")

class NodeList(BaseModel):
    provider: ProviderType = Field(..., description="The git provider")
    path: str = Field(..., description="The path that was explored")
    nodes: List[Node] = Field(..., description="List of child nodes under the given path")

import time

# Simple TTL Cache
class SimpleTTLCache:
    """
    A simple thread-safe, time-to-live (TTL) memory cache for API responses.

    Behavioral Contracts:
    - Evicts items lazily upon attempted access after their TTL has expired.

    Performance Expectations:
    - O(1) read and write performance.
    - Not suitable for distributed caching across multiple worker processes.

    Failure Modes:
    - Unbounded memory growth if items are never accessed again (no active cleanup loop).
    """
    def __init__(self, ttl):
        self.ttl = ttl
        self.cache = {}
        self.timestamps = {}

    def __contains__(self, key):
        if key in self.cache:
            if time.time() - self.timestamps[key] < self.ttl:
                return True
            else:
                del self.cache[key]
                del self.timestamps[key]
        return False

    def __getitem__(self, key):
        return self.cache[key]

    def __setitem__(self, key, value):
        self.cache[key] = value
        self.timestamps[key] = time.time()

# Caching responses for 5 minutes
explore_cache = SimpleTTLCache(ttl=300)

class ProviderPathNotFoundError(Exception):
    pass

class ProviderNotImplementedError(Exception):
    pass

async def _fetch_all_github_pages(client, url, headers, is_workflow=False):
    results = []
    while url:
        resp = await client.get(url, headers=headers)
        if resp.status_code == 403:
            raise ProviderPathNotFoundError("GitHub API Rate Limit Exceeded (403). Please wait before trying again.")
        if resp.status_code != 200:
            break
        data = resp.json()
        if is_workflow and isinstance(data, dict) and "workflows" in data:
            results.extend(data["workflows"])
        elif isinstance(data, list):
            results.extend(data)
            
        link_header = resp.headers.get("Link", "")
        next_url = None
        if link_header:
            links = link_header.split(",")
            for link in links:
                parts = link.split(";")
                if len(parts) == 2 and 'rel="next"' in parts[1]:
                    next_url = parts[0].strip()[1:-1]
        url = next_url
    return results

async def github_explore(path: str) -> List[Node]:
    """
    Explores the GitHub hierarchy (User -> Orgs -> Repos -> Workflows) given a generic path.

    Behavioral Contracts:
    - Maps GitHub's nested structures into a flat `NodeList` for tree navigation.

    Performance Expectations:
    - Performs HTTP requests dynamically based on the path depth. Responses are cached by the caller.

    Failure Modes:
    - Raises `ProviderPathNotFoundError` if authentication tokens are missing, rate limits are hit (403), or the API returns 404.
    """
    token = config_manager.get_value("github_token", "GITHUB_TOKEN")
    if not token:
        raise ProviderPathNotFoundError("GitHub token not configured")
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github.v3+json"}
    parts = [p for p in path.strip("/").split("/") if p]

    async with httpx.AsyncClient(timeout=10.0) as client:
        if len(parts) == 0:
            # Root: Return authenticated user and orgs
            nodes = []
            user_resp = await client.get("https://api.github.com/user", headers=headers)
            if user_resp.status_code == 403:
                raise ProviderPathNotFoundError("GitHub API Rate Limit Exceeded (403)")
            if user_resp.status_code == 200:
                user_data = user_resp.json()
                login = user_data.get("login")
                nodes.append(Node(id=login, name=login, type=NodeType.USER, path=login, has_children=True, url=user_data.get("html_url")))

            orgs = await _fetch_all_github_pages(client, "https://api.github.com/user/orgs?per_page=100", headers)
            for org in orgs:
                login = org.get("login")
                nodes.append(Node(id=login, name=login, type=NodeType.ORGANIZATION, path=login, has_children=True, url=org.get("url")))
            return nodes
        elif len(parts) == 1:
            # Owner: List repositories
            owner = parts[0]
            repos = await _fetch_all_github_pages(client, f"https://api.github.com/users/{owner}/repos?per_page=100", headers)
            if repos:
                return [Node(id=r.get("name"), name=r.get("name"), type=NodeType.REPOSITORY, path=f"{owner}/{r.get('name')}", has_children=True, url=r.get("html_url")) for r in repos]
            raise ProviderPathNotFoundError(f"Owner {owner} not found, has no repos, or rate limited")
        elif len(parts) == 2:
            # Repo: List workflows
            owner, repo = parts[0], parts[1]
            wfs = await _fetch_all_github_pages(client, f"https://api.github.com/repos/{owner}/{repo}/actions/workflows?per_page=100", headers, is_workflow=True)
            if wfs:
                return [Node(id=str(w.get("id")), name=w.get("name"), type=NodeType.WORKFLOW, path=f"{owner}/{repo}/{w.get('id')}", has_children=False, url=w.get("html_url")) for w in wfs]
            raise ProviderPathNotFoundError(f"Workflows for {owner}/{repo} not found or rate limited")

    return []

async def forgejo_explore(path: str) -> List[Node]:
    token = config_manager.get_value("forgejo_token", "FORGEJO_TOKEN")
    url = config_manager.get_value("forgejo_url", "FORGEJO_URL")
    if not token or not url:
        raise ProviderPathNotFoundError("Forgejo token or URL not configured")
    url = url.rstrip('/')
    headers = {"Authorization": f"token {token}", "Accept": "application/json"}
    parts = [p for p in path.strip("/").split("/") if p]

    async with httpx.AsyncClient(timeout=10.0) as client:
        if len(parts) == 0:
            nodes = []
            user_resp = await client.get(f"{url}/api/v1/user", headers=headers)
            if user_resp.status_code == 200:
                user_data = user_resp.json()
                login = user_data.get("login", user_data.get("username"))
                if login:
                    nodes.append(Node(id=login, name=login, type=NodeType.USER, path=login, has_children=True, url=f"{url}/{login}"))

            orgs_resp = await client.get(f"{url}/api/v1/user/orgs", headers=headers)
            if orgs_resp.status_code == 200:
                for org in orgs_resp.json():
                    login = org.get("username")
                    nodes.append(Node(id=login, name=login, type=NodeType.ORGANIZATION, path=login, has_children=True, url=f"{url}/{login}"))
            return nodes
        elif len(parts) == 1:
            owner = parts[0]
            # Try orgs first, then users
            repos_resp = await client.get(f"{url}/api/v1/orgs/{owner}/repos?limit=100", headers=headers)
            if repos_resp.status_code != 200:
                repos_resp = await client.get(f"{url}/api/v1/users/{owner}/repos?limit=100", headers=headers)
            if repos_resp.status_code == 200:
                return [Node(id=r.get("name"), name=r.get("name"), type=NodeType.REPOSITORY, path=f"{owner}/{r.get('name')}", has_children=True, url=r.get("html_url")) for r in repos_resp.json()]
            raise ProviderPathNotFoundError(f"Owner {owner} not found or no access")
        elif len(parts) == 2:
            owner, repo = parts[0], parts[1]
            return [Node(id="any", name="Any Workflow", type=NodeType.WORKFLOW, path=f"{owner}/{repo}/any", has_children=False)]

    return []

async def jenkins_explore(path: str) -> List[Node]:
    user = config_manager.get_value("jenkins_user", "JENKINS_USER")
    token = config_manager.get_value("jenkins_token", "JENKINS_TOKEN")
    base_url = config_manager.get_value("jenkins_url", "JENKINS_URL")
    if not base_url:
        raise HTTPException(status_code=400, detail="Jenkins URL is not configured. Please update your settings.")

    base_url = base_url.rstrip('/')
    auth = (user, token) if user and token else None

    # Jenkins path maps directly to folder path: job/Folder/job/Subfolder
    # If path is empty, we query base_url/api/json
    query_url = f"{base_url}/{path}/api/json?tree=jobs[name,url,_class]" if path else f"{base_url}/api/json?tree=jobs[name,url,_class]"

    async with httpx.AsyncClient(timeout=10.0, auth=auth) as client:
        resp = await client.get(query_url)
        if resp.status_code == 200:
            data = resp.json()
            jobs = data.get("jobs", [])
            nodes = []
            for j in jobs:
                j_class = j.get("_class", "")
                j_name = j.get("name", "unknown")
                j_url = j.get("url", "")
                # Next path is job/{name}
                next_path = f"{path}/job/{j_name}" if path else f"job/{j_name}"

                is_folder = "Folder" in j_class or "MultiBranchProject" in j_class or "OrganizationFolder" in j_class
                node_type = NodeType.FOLDER if is_folder else NodeType.JOB

                nodes.append(Node(id=j_name, name=j_name, type=node_type, path=next_path, has_children=is_folder, url=j_url))
            return nodes
        elif resp.status_code in (401, 403):
            raise HTTPException(status_code=401, detail="Jenkins authentication failed. Please verify your User and Token in the configuration.")
        raise ProviderPathNotFoundError(f"Jenkins path {path} not found")

async def fetch_provider_nodes(provider: ProviderType, path: str) -> List[Node]:
    if provider == ProviderType.github:
        return await github_explore(path)
    elif provider in (ProviderType.forgejo, ProviderType.gitea):
        return await forgejo_explore(path)
    elif provider == ProviderType.jenkins:
        return await jenkins_explore(path)
    else:
        raise ValueError(f"Unknown provider routing: {provider}")

@router.get("/{provider}/nodes", response_model=NodeList)
async def get_nodes(
    provider: ProviderType = Path(..., description="The provider name"),
    path: str = Query("", description="The hierarchical path to explore. Leave empty for the root level. GitHub/Gitea/Forgejo expect 'owner/repo'. Jenkins expects 'job/name-of-job' (the 'job/' prefix is required by its API)."),
    user: str = Depends(get_current_user)
):
    provider_lower = provider.value.lower()
    if provider_lower not in ["github", "forgejo", "gitea", "jenkins"]:
        raise HTTPException(status_code=400, detail=f"Unsupported provider: {provider}")

    cache_key = f"{provider_lower}:{path}"
    if cache_key in explore_cache:
        return explore_cache[cache_key]

    try:
        nodes = await fetch_provider_nodes(provider, path)
        result = NodeList(provider=provider, path=path, nodes=nodes)
        explore_cache[cache_key] = result
        return result
    except ProviderPathNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ProviderNotImplementedError as e:
        raise HTTPException(status_code=501, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error exploring {provider_lower} path '{path}': {e}")
        raise HTTPException(status_code=500, detail="Internal server error while fetching nodes.")
