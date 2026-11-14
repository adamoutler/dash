import pytest

from api.storage import RepoStorage


@pytest.fixture
def temp_storage(tmp_path):
    storage_file = tmp_path / "repos.json"
    return RepoStorage(str(storage_file))


def test_add_and_list_repo(temp_storage):
    temp_storage.add_repo("github", "owner", "repo")
    repos = temp_storage.get_repos()
    assert len(repos) == 1
    assert repos[0] == {"provider": "github", "owner": "owner", "repo": "repo"}


def test_remove_repo(temp_storage):
    temp_storage.add_repo("github", "owner", "repo")
    temp_storage.remove_repo("github", "owner", "repo")
    assert len(temp_storage.get_repos()) == 0


def test_duplicate_repo(temp_storage):
    temp_storage.add_repo("github", "owner", "repo")
    temp_storage.add_repo("github", "owner", "repo")
    assert len(temp_storage.get_repos()) == 1


def test_edit_repo_inplace(temp_storage):
    temp_storage.add_repo(
        "forgejo", "user", "repo", workflow_id="old_wf.yml", branch="main"
    )
    repos = temp_storage.get_repos()
    assert len(repos) == 1
    assert repos[0]["workflow_id"] == "old_wf.yml"
    assert repos[0]["branch"] == "main"

    # Edit in-place changing workflow and branch
    temp_storage.add_repo(
        "forgejo",
        "user",
        "repo",
        workflow_id="new_wf.yml",
        workflow_name="New Workflow",
        branch="develop",
        orig_workflow_id="old_wf.yml",
        orig_branch="main",
    )
    repos = temp_storage.get_repos()
    assert len(repos) == 1
    assert repos[0]["workflow_id"] == "new_wf.yml"
    assert repos[0]["workflow_name"] == "New Workflow"
    assert repos[0]["branch"] == "develop"
