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
