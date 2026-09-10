from .base import Action, Policy, PolicyContext
from .guided_random import GuidedRandomPolicy
from .smart_random import SmartRandomPolicy
from .strategic import StrategicPolicy

POLICIES = {"guided_random": GuidedRandomPolicy, "smart_random": SmartRandomPolicy, "strategic": StrategicPolicy}


def make_policy(name: str, seed=None) -> Policy:
    return POLICIES[name](seed=seed)
