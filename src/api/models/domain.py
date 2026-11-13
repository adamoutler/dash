from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class ProviderType(str, Enum):
    github = "github"
    forgejo = "forgejo"
    gitea = "gitea"
    jenkins = "jenkins"


class RepoItem(BaseModel):
    provider: ProviderType = Field(..., description="The git provider")
    owner: str = Field(..., description="The repository owner or organization name")
    repo: str = Field(..., description="The repository name")
    branch: str | None = Field(
        None,
        description="The specific branch to track. If omitted, uses the default branch.",
    )
    custom_links: list | None = Field(
        None,
        description="An optional list of custom links (name and url) to display alongside the repository",
    )
    workflow_id: str | None = Field(
        None,
        description="The specific workflow ID or filename to track. If omitted, the dashboard tracks the most recent run of any workflow.",
    )
    workflow_name: str | None = Field(
        None, description="A friendly, human-readable name for the selected workflow"
    )
    orig_workflow_id: str | None = Field(
        None,
        description="The original workflow ID if editing an existing tracked repository",
    )
    orig_branch: str | None = Field(
        None,
        description="The original branch if editing an existing tracked repository",
    )


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
    has_children: bool = Field(
        default=False, description="Whether this node can be expanded further"
    )
    url: str | None = Field(default=None, description="External URL to view this node")
    metadata: dict[str, Any] | None = Field(
        default=None, description="Provider-specific metadata"
    )


class NodeList(BaseModel):
    provider: ProviderType = Field(..., description="The git provider")
    path: str = Field(..., description="The path that was explored")
    nodes: list[Node] = Field(
        ..., description="List of child nodes under the given path"
    )
