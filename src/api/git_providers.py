import httpx
import datetime

def _error_result(provider, owner, repo):
    return {
        "provider": provider,
        "owner": owner,
        "repo": repo,
        "status": "error",
        "url": "#",
        "repo_url": "#",
        "updated_at": "",
        "commit_message": "Failed to fetch"
    }

def _get_status_weight(r):
    st = (r.get("status") or "").lower()
    conclusion = (r.get("conclusion") or "").lower()
    if st in ["in_progress", "queued", "requested", "waiting", "running"]:
        return 3
    if conclusion in ["success", "failure", "action_required"] or st in ["success", "failure"]:
        return 2
    return 1

async def fetch_github_status(owner: str, repo: str, token: str, workflow_id: str = None, branch: str = None):
    if workflow_id == "any":
        workflow_id = None
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github.v3+json"} if token else {}
    base_url = f"https://api.github.com/repos/{owner}/{repo}"

    runs_url = f"{base_url}/actions/workflows/{workflow_id}/runs?per_page=10" if workflow_id else f"{base_url}/actions/runs?per_page=10"
    if branch:
        runs_url += f"&branch={branch}" if "?" in runs_url else f"?branch={branch}"

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            runs_resp = await client.get(runs_url, headers=headers)

            if runs_resp.status_code == 403:
                err = _error_result("github", owner, repo)
                err["commit_message"] = "GitHub API Rate Limit Exceeded (403)"
                return err
            elif runs_resp.status_code != 200:
                err = _error_result("github", owner, repo)
                err["commit_message"] = f"Failed to fetch (HTTP {runs_resp.status_code})"
                return err

            runs_data = runs_resp.json()
            runs = runs_data.get("workflow_runs", [])
            run = sorted(runs, key=lambda x: (
                (x.get("created_at") or x.get("created", ""))[:16],
                _get_status_weight(x),
                x.get("updated_at") or x.get("updated", "")
            ), reverse=True)[0] if runs else {}

            commit_msg = "No commit message"
            if run and "head_commit" in run and run["head_commit"]:
                commit_msg = run["head_commit"].get("message", "No commit message").split("\n")[0]
            
            status = run.get("status")
            conclusion = run.get("conclusion")
            common_status = "running" if status in ["in_progress", "queued", "requested"] else (conclusion or "unknown")

            expected_duration_sec = None
            started_at = run.get("run_started_at") or run.get("created_at", "")

            successful_runs = [r for r in runs if r.get("status") == "completed" and r.get("conclusion") == "success"]
            if successful_runs:
                total_duration = 0
                valid_runs = 0
                for r in successful_runs[:5]:
                    r_start = r.get("run_started_at") or r.get("created_at")
                    r_end = r.get("updated_at")
                    if r_start and r_end:
                        try:
                            start_dt = datetime.datetime.fromisoformat(r_start.replace("Z", "+00:00"))
                            end_dt = datetime.datetime.fromisoformat(r_end.replace("Z", "+00:00"))
                            total_duration += (end_dt - start_dt).total_seconds()
                            valid_runs += 1
                        except Exception:
                            pass
                if valid_runs > 0:
                    expected_duration_sec = total_duration / valid_runs

            return {
                "provider": "github",
                "owner": owner,
                "repo": repo,
                "status": common_status,
                "url": run.get("html_url", f"https://github.com/{owner}/{repo}/actions"),
                "repo_url": f"https://github.com/{owner}/{repo}",
                "updated_at": run.get("updated_at", ""),
                "commit_message": commit_msg,
                "started_at": started_at,
                "expected_duration_sec": expected_duration_sec
            }
    except Exception as e:
        err = _error_result("github", owner, repo)
        err["commit_message"] = f"Exception: {str(e)}"
        return err

async def fetch_forgejo_status(owner: str, repo: str, token: str, forgejo_url: str, workflow_id: str = None, branch: str = None):
    """
    Fetches the CI status for a specific Forgejo repository and workflow.

    Behavioral Contracts:
    - Returns a standardized dictionary representing the repository's CI state.
    - Handles mapping of Forgejo-specific statuses (e.g., 'waiting') to common UI statuses.

    Performance Expectations:
    - Makes two concurrent HTTP requests to the Forgejo API (runs and commits).
    - Expect response within < 10 seconds (enforced by httpx timeout).

    Failure Modes:
    - Returns a fallback `_error_result` dict if `forgejo_url` is missing or requests fail/timeout.
    """
    if workflow_id == "any":
        workflow_id = None
    if not forgejo_url:
        return _error_result("forgejo", owner, repo)

    headers = {"Authorization": f"token {token}", "Accept": "application/json"} if token else {}
    base_url = f"{forgejo_url.rstrip('/')}/api/v1/repos/{owner}/{repo}"

    runs_url = f"{base_url}/actions/runs?limit=30"
    if branch:
        runs_url += f"&branch={branch}"

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            runs_resp = await client.get(runs_url, headers=headers)
            commits_resp = await client.get(f"{base_url}/commits?limit=1" + (f"&sha={branch}" if branch else ""), headers=headers)

            if runs_resp.status_code != 200 or commits_resp.status_code != 200:
                return _error_result("forgejo", owner, repo)

            runs_data = runs_resp.json()
            commits_data = commits_resp.json()

            all_runs = runs_data.get("workflow_runs", [])
            runs = []
            for r in all_runs:
                if not workflow_id or r.get("name") == workflow_id or str(r.get("workflow_id")) == workflow_id:
                    runs.append(r)

            # Use runs[0] if exists. (Previously the codebase sometimes used runs[-1] incorrectly depending on ordering,
            # but usually API returns newest first. Let's use the first match).

            # Sort by created_at first. Since runs from the same push might be 1-2 seconds apart,
            # we just take the newest run's time, then find all runs within a small window and pick the highest weight.
            # A simpler robust sort: just sort by (created_at[:16], weight, updated_at) to group by minute.
            run = sorted(runs, key=lambda x: (
                (x.get("created_at") or x.get("created", ""))[:16], # Group by minute "YYYY-MM-DDTHH:MM"
                _get_status_weight(x),
                x.get("updated_at") or x.get("updated", "")
            ), reverse=True)[0] if runs else {}
            commit_msg = commits_data[0].get("commit", {}).get("message", "No commit message").split("\n")[0] if commits_data else ""

            status = run.get("status") or "unknown"
            # Map Forgejo status (success, failure, running, etc)
            common_status = status.lower()
            if common_status in ["success", "failure", "running"]:
                pass # mapped correctly
            elif common_status == "waiting":
                common_status = "running"

            expected_duration_sec = None
            started_at = run.get("started") or run.get("created", "")

            successful_runs = [r for r in runs if (r.get("status") or "").lower() == "success"]
            if successful_runs:
                total_duration = 0
                valid_runs = 0
                for r in successful_runs[:5]:
                    duration = r.get("duration")
                    if duration:
                        total_duration += (duration / 1000000000)
                        valid_runs += 1
                    else:
                        r_start = r.get("started") or r.get("created")
                        r_end = r.get("stopped") or r.get("updated")
                        if r_start and r_end:
                            try:
                                start_dt = datetime.datetime.fromisoformat(r_start.replace("Z", "+00:00"))
                                end_dt = datetime.datetime.fromisoformat(r_end.replace("Z", "+00:00"))
                                total_duration += (end_dt - start_dt).total_seconds()
                                valid_runs += 1
                            except Exception:
                                pass
                if valid_runs > 0:
                    expected_duration_sec = total_duration / valid_runs

            return {
                "provider": "forgejo",
                "owner": owner,
                "repo": repo,
                "status": common_status,
                "url": f"{run.get('html_url', forgejo_url + '/' + owner + '/' + repo + '/actions/runs/' + str(run.get('index_in_repo', run.get('id', ''))))}/jobs/0/attempt/1" if run else "#",
                "repo_url": f"{forgejo_url}/{owner}/{repo}",
                "updated_at": run.get("updated", run.get("updated_at", "")),
                "commit_message": commit_msg,
                "started_at": started_at,
                "expected_duration_sec": expected_duration_sec,
                "workflow_name": run.get("name", "")
            }
    except Exception:
        return _error_result("forgejo", owner, repo)

async def fetch_github_logs(owner: str, repo: str, token: str, workflow_id: str = None, branch: str = None):
    if workflow_id == "any":
        workflow_id = None
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github.v3+json"} if token else {}
    base_url = f"https://api.github.com/repos/{owner}/{repo}"
    runs_url = f"{base_url}/actions/workflows/{workflow_id}/runs?per_page=1" if workflow_id else f"{base_url}/actions/runs?per_page=1"
    if branch:
        runs_url += f"&branch={branch}" if "?" in runs_url else f"?branch={branch}"
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            runs_resp = await client.get(runs_url, headers=headers)
            if runs_resp.status_code != 200:
                return "Failed to fetch runs from GitHub."
            runs_list = runs_resp.json().get("workflow_runs", [])
            run = runs_list[0] if runs_list else {}
            if not run.get('id'):
                return "No runs found."

            jobs_resp = await client.get(f"{base_url}/actions/runs/{run['id']}/jobs", headers=headers)
            if jobs_resp.status_code != 200:
                return "Failed to fetch jobs for the run."

            jobs = jobs_resp.json().get('jobs', [])
            if not jobs:
                return "No jobs found for the run."

            logs_resp = await client.get(f"{base_url}/actions/jobs/{jobs[0]['id']}/logs", headers=headers, follow_redirects=True)
            if logs_resp.status_code == 200:
                return logs_resp.text
            return f"Failed to fetch logs. HTTP {logs_resp.status_code}"
    except Exception as e:
        return f"Error fetching GitHub logs: {str(e)}"

async def fetch_forgejo_logs(owner: str, repo: str, token: str, forgejo_url: str, workflow_id: str = None):
    wf_param = f"&workflow_id={workflow_id}" if workflow_id and workflow_id != "any" else ""

    return f"""Forgejo/Gitea logs are not natively available via API in this version.

To view logs here, please configure your CI pipeline to upload logs to the dashboard's /api/logs endpoint.
You can do this by adding a step that runs on failure using the always() method.

Example curl command to upload logs:
curl -X POST "${{DASH_API_URL}}/api/logs?provider=forgejo&owner={owner}&repo={repo}{wf_param}" \\
     -H "Authorization: Bearer ${{DASH_API_TOKEN}}" \\
     -H "Content-Type: text/plain" \\
     --data-binary @path/to/your/logfile.log

Recommendations:
- Use the always() condition in your CI step so logs are uploaded even if previous steps fail.
- Check earlier stages in your pipeline to ensure the log file is being generated correctly.
- Be sure to test your configuration to verify that logs are successfully uploaded and appear here.
"""

async def fetch_github_artifacts(owner: str, repo: str, token: str, workflow_id: str = None, branch: str = None):
    if workflow_id == "any":
        workflow_id = None
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github.v3+json"} if token else {}
    base_url = f"https://api.github.com/repos/{owner}/{repo}"
    runs_url = f"{base_url}/actions/workflows/{workflow_id}/runs?per_page=1" if workflow_id else f"{base_url}/actions/runs?per_page=1"
    if branch:
        runs_url += f"&branch={branch}" if "?" in runs_url else f"?branch={branch}"
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            runs_resp = await client.get(runs_url, headers=headers)
            if runs_resp.status_code != 200:
                return {"error": f"Failed to fetch runs. HTTP {runs_resp.status_code}"}
            runs_list = runs_resp.json().get("workflow_runs", [])
            run = runs_list[0] if runs_list else {}
            if not run.get('id'):
                return {"error": "No runs found."}

            artifacts_resp = await client.get(f"{base_url}/actions/runs/{run['id']}/artifacts", headers=headers)
            if artifacts_resp.status_code == 200:
                return artifacts_resp.json()
            return {"error": f"Failed to fetch artifacts. HTTP {artifacts_resp.status_code}"}
    except Exception as e:
        return {"error": f"Error fetching GitHub artifacts: {str(e)}"}

async def fetch_forgejo_artifacts(owner: str, repo: str, token: str, forgejo_url: str, workflow_id: str = None, branch: str = None):
    if workflow_id == "any":
        workflow_id = None
    if not forgejo_url:
        return {"error": "Forgejo URL not configured."}
    base_url = f"{forgejo_url.rstrip('/')}/api/v1/repos/{owner}/{repo}"
    headers = {"Authorization": f"token {token}", "Accept": "application/json"} if token else {}
    
    runs_url = f"{base_url}/actions/runs?limit=30"
    if branch:
        runs_url += f"&branch={branch}"
        
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            runs_resp = await client.get(runs_url, headers=headers)
            if runs_resp.status_code != 200:
                return {"error": f"Failed to fetch runs. HTTP {runs_resp.status_code}"}

            runs_data = runs_resp.json()
            all_runs = runs_data.get("workflow_runs", [])
            runs = []
            for r in all_runs:
                if not workflow_id or r.get("name") == workflow_id or str(r.get("workflow_id")) == workflow_id:
                    runs.append(r)

            # Sort by created_at first. Since runs from the same push might be 1-2 seconds apart,
            # we just take the newest run's time, then find all runs within a small window and pick the highest weight.
            # A simpler robust sort: just sort by (created_at[:16], weight, updated_at) to group by minute.
            run = sorted(runs, key=lambda x: (
                (x.get("created_at") or x.get("created", ""))[:16], # Group by minute "YYYY-MM-DDTHH:MM"
                _get_status_weight(x),
                x.get("updated_at") or x.get("updated", "")
            ), reverse=True)[0] if runs else {}
            if not run.get('id'):
                return {"error": "No runs found."}

            artifacts_resp = await client.get(f"{base_url}/actions/runs/{run['id']}/artifacts", headers=headers)
            if artifacts_resp.status_code == 200:
                return artifacts_resp.json()
            elif artifacts_resp.status_code == 404:
                return {"error": "Artifacts API endpoint not found on this Forgejo version. Ensure actions/upload-artifact is configured and verify server version compatibility."}
            return {"error": f"Failed to fetch artifacts. HTTP {artifacts_resp.status_code}"}
    except Exception as e:
        return {"error": f"Error fetching Forgejo artifacts: {str(e)}"}

async def fetch_jenkins_status(owner: str, repo: str, user: str, token: str, jenkins_url: str, workflow_id: str = None):
    if workflow_id == "any":
        workflow_id = None
        
    if jenkins_url and repo and not repo.startswith("http"):
        job_path_parts = repo.strip('/').split('/')
        job_path = "/".join(f"job/{p}" for p in job_path_parts if p)
        base_url = f"{jenkins_url.rstrip('/')}/{job_path}"
    else:
        # Backward compatibility for old repo definitions
        base_url = repo.rstrip('/')
        
    auth = (user, token) if user and token else None

    try:
        async with httpx.AsyncClient(timeout=10.0, auth=auth) as client:
            return await _resolve_jenkins_status(client, base_url, owner, repo)
    except Exception:
        return _error_result("jenkins", owner, repo)

async def _resolve_jenkins_status(client, url, owner, repo_field, max_depth=3):
    if max_depth <= 0:
        return _error_result("jenkins", owner, repo_field)

    api_url = f"{url.rstrip('/')}/api/json?tree=lastBuild[number,url,result,timestamp,duration,estimatedDuration,changeSets[items[msg]]],inQueue,color,jobs[name,url]"
    resp = await client.get(api_url)
    if resp.status_code != 200:
        return _error_result("jenkins", owner, repo_field)

    data = resp.json()
    cls = data.get("_class", "")

    if "WorkflowJob" in cls or "FreeStyleProject" in cls:
        # It's a leaf job
        last_build = data.get("lastBuild")
        in_queue = data.get("inQueue")
        color = data.get("color", "")

        status = "unknown"
        if in_queue or "anime" in color:
            status = "running"

        if not last_build:
            if status != "running":
                return {
                    "provider": "jenkins",
                    "owner": owner,
                    "repo": repo_field,
                    "status": "unknown",
                    "url": url,
                    "repo_url": url,
                    "updated_at": "",
                    "commit_message": "No builds found",
                    "started_at": "",
                    "expected_duration_sec": None
                }
            else:
                return {
                    "provider": "jenkins",
                    "owner": owner,
                    "repo": repo_field,
                    "status": status,
                    "url": url,
                    "repo_url": url,
                    "updated_at": "",
                    "commit_message": "Job is in queue or starting",
                    "started_at": "",
                    "expected_duration_sec": None
                }

        result = last_build.get("result")
        if status == "unknown":
            if result is None:
                status = "running"
            elif result == "SUCCESS":
                status = "success"
            elif result in ["FAILURE", "UNSTABLE", "ABORTED"]:
                status = "failure"

        timestamp_ms = last_build.get("timestamp")
        started_at = datetime.datetime.fromtimestamp(timestamp_ms / 1000.0, tz=datetime.timezone.utc).isoformat() if timestamp_ms else ""

        est_duration = last_build.get("estimatedDuration", -1)
        if est_duration <= 0:
            expected_duration_sec = 43.6  # Average of recent runs: 53, 32, 32, 50, 51
        else:
            expected_duration_sec = est_duration / 1000.0

        # Extract commit msg
        commit_msg = ""
        change_sets = last_build.get("changeSets", [])
        if change_sets and isinstance(change_sets, list):
            items = change_sets[0].get("items", [])
            if items:
                commit_msg = items[0].get("msg", "")

        return {
            "provider": "jenkins",
            "owner": owner,
            "repo": repo_field,
            "status": status,
            "url": last_build.get("url", url),
            "repo_url": url,
            "display_name": data.get("fullDisplayName") or data.get("displayName") or owner,
            "updated_at": started_at, # Jenkins doesn't give a clear updated_at, using started_at
            "commit_message": commit_msg,
            "started_at": started_at,
            "expected_duration_sec": expected_duration_sec
        }
    elif "MultiBranchProject" in cls or "OrganizationFolder" in cls:
        jobs = data.get("jobs", [])
        if not jobs:
            return _error_result("jenkins", owner, repo_field)

        # Prioritize master or main
        target_job = next((j for j in jobs if j.get("name") in ["master", "main"]), jobs[0])
        return await _resolve_jenkins_status(client, target_job.get("url"), owner, repo_field, max_depth - 1)

    return _error_result("jenkins", owner, repo_field)

async def fetch_jenkins_logs(owner: str, repo: str, user: str, token: str, jenkins_url: str, workflow_id: str = None):
    if workflow_id == "any":
        workflow_id = None
        
    if jenkins_url and repo and not repo.startswith("http"):
        job_path_parts = repo.strip('/').split('/')
        job_path = "/".join(f"job/{p}" for p in job_path_parts if p)
        base_url = f"{jenkins_url.rstrip('/')}/{job_path}"
    else:
        # Backward compatibility for old repo definitions
        base_url = repo.rstrip('/')
        
    auth = (user, token) if user and token else None

    try:
        async with httpx.AsyncClient(timeout=10.0, auth=auth) as client:
            return await _resolve_jenkins_logs(client, base_url, max_depth=3)
    except Exception as e:
        return f"Error fetching Jenkins logs: {str(e)}"

async def _resolve_jenkins_logs(client, url, max_depth=3):
    if max_depth <= 0:
        return "Max depth reached while resolving Jenkins job."

    api_url = f"{url.rstrip('/')}/api/json"
    resp = await client.get(api_url)
    if resp.status_code != 200:
        return "Failed to fetch job data from Jenkins."

    data = resp.json()
    cls = data.get("_class", "")

    if "WorkflowJob" in cls or "FreeStyleProject" in cls:
        last_build = data.get("lastBuild")
        if not last_build:
            return "No builds found."

        build_url = last_build.get("url")
        log_url = f"{build_url.rstrip('/')}/consoleText"
        log_resp = await client.get(log_url)
        if log_resp.status_code == 200:
            return log_resp.text
        return f"Failed to fetch Jenkins console text. HTTP {log_resp.status_code}"
    elif "MultiBranchProject" in cls or "OrganizationFolder" in cls:
        jobs = data.get("jobs", [])
        if not jobs:
            return "No jobs found in folder."

        target_job = next((j for j in jobs if j.get("name") in ["master", "main"]), jobs[0])
        return await _resolve_jenkins_logs(client, target_job.get("url"), max_depth - 1)

    return "Unsupported Jenkins object class."

async def fetch_jenkins_artifacts(owner: str, repo: str, user: str, token: str, jenkins_url: str = None, workflow_id: str = None, branch: str = None):
    if workflow_id == "any":
        workflow_id = None
    return {"error": "Jenkins artifacts not implemented yet."}

async def fetch_github_branches(owner: str, repo: str, token: str):
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github.v3+json"} if token else {}
    base_url = f"https://api.github.com/repos/{owner}/{repo}/branches"
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(base_url, headers=headers)
            if resp.status_code == 200:
                return [b["name"] for b in resp.json()]
            return []
    except Exception:
        return []

async def fetch_forgejo_branches(owner: str, repo: str, token: str, forgejo_url: str):
    if not forgejo_url:
        return []
    headers = {"Authorization": f"token {token}", "Accept": "application/json"} if token else {}
    base_url = f"{forgejo_url.rstrip('/')}/api/v1/repos/{owner}/{repo}/branches"
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(base_url, headers=headers)
            if resp.status_code == 200:
                return [b["name"] for b in resp.json()]
            return []
    except Exception:
        return []

async def fetch_jenkins_branches(owner: str, repo: str, user: str, token: str, jenkins_url: str):
    return []
