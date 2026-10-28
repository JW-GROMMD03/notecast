from fastapi import Depends, HTTPException, status, Query
from app.services.entitlement_service import EntitlementService
from app.api.auth import get_current_user  # Your existing user authentication helper

entitlement_service = EntitlementService()

def verify_entitlement(action: str):
    """
    Dependency factory to enforce subscription privileges before endpoint execution.
    Usage in router:
        @router.post("/generate", dependencies=[Depends(verify_entitlement("GENERATE_AI_NOTES"))])
    """
    async def dependency(current_user: dict = Depends(get_current_user)):
        user_id = current_user["id"]
        entitlement_service.verify_action_permission(user_id=user_id, action=action)
        return current_user

    return dependency