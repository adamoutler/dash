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

async def fetch_github_status(owner: str, repo: str, token: str, workflow_id: str = None):
    if workflow_id == "any":
        workflow_id = None
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github.v3+json"} if token else {}
    base_url = f"https://api.github.com/repos/{owner}/{repo}"

    runs_url = f"{base_url}/actions/workflows/{workflow_id}/runs?per_page=10" if workflow_id else f"{base_url}/actions/runs?per_page=10"

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            runs_resp = await client.get(runs_url, headers=headers)
            commits_resp = await client.get(f"{base_url}/commits?per_page=1", headers=headers)

            if runs_resp.status_code != 200 or commits_resp.status_code != 200:
                return _error_result("github", owner, repo)

            runs_data = runs_resp.json()
            commits_data = commits_resp.json()

            runs = runs_data.get("workflow_runs", [])
            run = sorted(runs, key=lambda x: x.get("updated_at", x.get("updated", "")), reverse=True)[0] if runs else {}
            commit_msg = commits_data[0].get("commit", {}).get("message", "No commit message").split("\n")[0] if commits_data else ""

            # Map GitHub status to common format
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
    except Exception:
        return _error_result("github", owner, repo)

async def fetch_forgejo_status(owner: str, repo: str, token: str, forgejo_url: str, workflow_id: str = None):
    if workflow_id == "any":
        workflow_id = None
    if not forgejo_url:
        return _error_result("forgejo", owner, repo)

    headers = {"Authorization": f"token {token}", "Accept": "application/json"} if token else {}
    base_url = f"{forgejo_url.rstrip('/')}/api/v1/repos/{owner}/{repo}"

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            runs_resp = await client.get(f"{base_url}/actions/runs?limit=30", headers=headers)
            commits_resp = await client.get(f"{base_url}/commits?limit=1", headers=headers)

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
            run = sorted(runs, key=lambda x: x.get("updated_at", x.get("updated", "")), reverse=True)[0] if runs else {}
            commit_msg = commits_data[0].get("commit", {}).get("message", "No commit message").split("\n")[0] if commits_data else ""

            status = run.get("status", "unknown")
            # Map Forgejo status (success, failure, running, etc)
            common_status = status.lower()
            if common_status in ["success", "failure", "running"]:
                pass # mapped correctly
            elif common_status == "waiting":
                common_status = "running"

            expected_duration_sec = None
            started_at = run.get("started") or run.get("created", "")

            successful_runs = [r for r in runs if r.get("status", "").lower() == "success"]
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

async def fetch_github_logs(owner: str, repo: str, token: str, workflow_id: str = None):
    if workflow_id == "any":
        workflow_id = None
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github.v3+json"} if token else {}
    base_url = f"https://api.github.com/repos/{owner}/{repo}"
    runs_url = f"{base_url}/actions/workflows/{workflow_id}/runs?per_page=1" if workflow_id else f"{base_url}/actions/runs?per_page=1"
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
    if workflow_id == "any":
        workflow_id = None
    if not forgejo_url:
        return "Forgejo URL not configured."
    # Forgejo/Gitea's API does not currently expose downloading logs in this version.
    # The best we can do is provide the URL for the user to visit.
    base_url = f"{forgejo_url.rstrip('/')}/api/v1/repos/{owner}/{repo}"
    headers = {"Authorization": f"token {token}", "Accept": "application/json"} if token else {}
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            runs_resp = await client.get(f"{base_url}/actions/runs?limit=30", headers=headers)
            if runs_resp.status_code != 200:
                return f"Failed to fetch runs from Forgejo. HTTP {runs_resp.status_code}\nPlease check your token or repository permissions."

            runs_data = runs_resp.json()
            all_runs = runs_data.get("workflow_runs", [])
            runs = []
            for r in all_runs:
                if not workflow_id or r.get("name") == workflow_id or str(r.get("workflow_id")) == workflow_id:
                    runs.append(r)

            run = sorted(runs, key=lambda x: x.get("updated_at", x.get("updated", "")), reverse=True)[0] if runs else {}
            if not run.get('id'):
                return "No runs found."

            run_url = run.get('html_url', forgejo_url + '/' + owner + '/' + repo + '/actions/runs/' + str(run.get('index_in_repo', run.get('id', ''))))
            return (
                "Forgejo/Gitea's API on this server does not expose an endpoint to fetch raw logs directly. "
                "However, you can view the logs in the web interface here:\n\n"
                f"{run_url}/jobs/0/attempt/1"
            )
    except Exception as e:
        return f"Error fetching Forgejo logs: {str(e)}"

async def fetch_github_artifacts(owner: str, repo: str, token: str, workflow_id: str = None):
    if workflow_id == "any":
        workflow_id = None
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github.v3+json"} if token else {}
    base_url = f"https://api.github.com/repos/{owner}/{repo}"
    runs_url = f"{base_url}/actions/workflows/{workflow_id}/runs?per_page=1" if workflow_id else f"{base_url}/actions/runs?per_page=1"
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

async def fetch_forgejo_artifacts(owner: str, repo: str, token: str, forgejo_url: str, workflow_id: str = None):
    if workflow_id == "any":
        workflow_id = None
    if not forgejo_url:
        return {"error": "Forgejo URL not configured."}
    base_url = f"{forgejo_url.rstrip('/')}/api/v1/repos/{owner}/{repo}"
    headers = {"Authorization": f"token {token}", "Accept": "application/json"} if token else {}
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            runs_resp = await client.get(f"{base_url}/actions/runs?limit=30", headers=headers)
            if runs_resp.status_code != 200:
                return {"error": f"Failed to fetch runs. HTTP {runs_resp.status_code}"}

            runs_data = runs_resp.json()
            all_runs = runs_data.get("workflow_runs", [])
            runs = []
            for r in all_runs:
                if not workflow_id or r.get("name") == workflow_id or str(r.get("workflow_id")) == workflow_id:
                    runs.append(r)

            run = sorted(runs, key=lambda x: x.get("updated_at", x.get("updated", "")), reverse=True)[0] if runs else {}
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

async def fetch_jenkins_status(owner: str, repo: str, user: str, token: str, workflow_id: str = None):
    if workflow_id == "any":
        workflow_id = None
    # repo is treated as the base URL of the Jenkins job/folder
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

async def fetch_jenkins_logs(owner: str, repo: str, user: str, token: str, workflow_id: str = None):
    if workflow_id == "any":
        workflow_id = None
    # repo is treated as the base URL of the Jenkins job/folder
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

async def fetch_jenkins_artifacts(owner: str, repo: str, user: str, token: str, workflow_id: str = None):
    if workflow_id == "any":
        workflow_id = None
    return {"error": "Jenkins artifacts not implemented yet."}
