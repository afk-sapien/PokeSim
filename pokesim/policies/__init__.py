from .base import Action, Policy, PolicyContext
from .guided_random import GuidedRandomPolicy
from .smart_random import SmartRandomPolicy
from .strategic import StrategicPolicy

POLICIES = {"guided_random": GuidedRandomPolicy, "smart_random": SmartRandomPolicy, "strategic": StrategicPolicy}
__all__ = ["Action", "Policy", "PolicyContext", "POLICIES", "make_policy"]


def make_policy(name: str, seed=None) -> Policy:
    return POLICIES[name](seed=seed)
