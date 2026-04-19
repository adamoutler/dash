from enum import Enum
from pydantic import BaseModel, Field
from typing import Optional, Dict, Any, List

class ProviderType(str, Enum):
    github = "github"
    forgejo = "forgejo"
    gitea = "gitea"
    jenkins = "jenkins"

class RepoItem(BaseModel):
    provider: ProviderType = Field(..., description="The git provider")
    owner: str = Field(..., description="The repository owner or organization name")
    repo: str = Field(..., description="The repository name")
    branch: Optional[str] = Field(None, description="The specific branch to track. If omitted, uses the default branch.")
    custom_links: Optional[list] = Field(None, description="An optional list of custom links (name and url) to display alongside the repository")
    workflow_id: Optional[str] = Field(None, description="The specific workflow ID or filename to track. If omitted, the dashboard tracks the most recent run of any workflow.")
    workflow_name: Optional[str] = Field(None, description="A friendly, human-readable name for the selected workflow")

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
