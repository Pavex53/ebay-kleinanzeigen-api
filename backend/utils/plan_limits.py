from backend.models import PlanTier

PLAN_SEARCH_LIMITS: dict[PlanTier, int] = {
    PlanTier.BASIC: 1,
    PlanTier.PRO: 3,
    PlanTier.EXPERT: 5,
}


def get_search_limit(plan_tier: PlanTier) -> int:
    return PLAN_SEARCH_LIMITS[plan_tier]
