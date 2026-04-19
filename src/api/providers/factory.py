from typing import Optional
from api.models.domain import ProviderType
from api.providers.base import BaseProvider

class ProviderFactory:
    """
    Factory to instantiate the appropriate provider based on the ProviderType.
    """

    @staticmethod
    def get_provider(provider_type: ProviderType, **kwargs) -> Optional[BaseProvider]:
        if provider_type == ProviderType.github:
            from api.providers.github import GitHubProvider
            return GitHubProvider(**kwargs)
        elif provider_type == ProviderType.forgejo:
            from api.providers.forgejo import ForgejoProvider
            return ForgejoProvider(**kwargs)
        elif provider_type == ProviderType.jenkins:
            from api.providers.jenkins import JenkinsProvider
            return JenkinsProvider(**kwargs)
        
        return None