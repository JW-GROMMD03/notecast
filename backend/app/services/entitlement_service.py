from datetime import datetime, date, timezone
from typing import Dict, Any, Tuple
from fastapi import HTTPException, status
from app.config import get_supabase_client

# NoteCast Subscription Rules Matrix
PLAN_LIMITS: Dict[str, Dict[str, Any]] = {
    "FREE": {
        "daily_yt_seconds": 0,       # Requires Economy Token (50 KES)
        "free_downloads": False,     # Requires Single Download Token (20 KES)
        "daily_ai_notes": 0,
        "daily_sims": 0,
        "daily_doc_summaries": 0,
    },
    "STARTUP": {
        "daily_yt_seconds": 3600,    # 1 Hour daily
        "free_downloads": False,     # 20 KES / download
        "daily_ai_notes": 0,
        "daily_sims": 0,
        "daily_doc_summaries": 0,
    },
    "BASIC": {
        "daily_yt_seconds": 7200,    # 2 Hours daily
        "free_downloads": True,      # Free downloads
        "daily_ai_notes": 0,         # Paid per note (80 KES)
        "daily_sims": 0,
        "daily_doc_summaries": 0,
    },
    "STANDARD": {
        "daily_yt_seconds": 14400,   # 4 Hours daily
        "free_downloads": True,
        "daily_ai_notes": 2,         # 2 per day
        "daily_sims": 2,             # 2 per day
        "daily_doc_summaries": 2,    # 2 per day
    },
    "PREMIUM": {
        "daily_yt_seconds": 43200,   # 12 Hours daily
        "free_downloads": True,
        "daily_ai_notes": 99999,     # Unlimited
        "daily_sims": 7,             # 5 Static + 2 Live LLM
        "daily_doc_summaries": 6,    # 6 per day
    }
}


class EntitlementService:
    def __init__(self):
        self.supabase = get_supabase_client()

    def get_active_subscription(self, user_id: str) -> Tuple[str, bool]:
        """
        Monitors subscription timeline and status.
        If subscription is expired, marks it expired in DB and falls back to FREE.
        """
        now = datetime.now(timezone.utc)
        
        # Query latest subscription record
        res = self.supabase.table("subscriptions") \
            .select("*") \
            .eq("user_id", user_id) \
            .eq("status", "active") \
            .order("created_at", desc=True) \
            .limit(1) \
            .execute()

        if not res.data or len(res.data) == 0:
            return "FREE", False

        sub = res.data[0]
        ends_at = datetime.fromisoformat(sub["ends_at"].replace("Z", "+00:00"))

        # Timeline Check: Has the subscription period passed?
        if ends_at < now:
            self.supabase.table("subscriptions") \
                .update({"status": "expired"}) \
                .eq("id", sub["id"]) \
                .execute()
            return "FREE", False

        return sub["plan_tier"], True

    def get_or_create_daily_usage(self, user_id: str) -> Dict[str, Any]:
        """Fetches or initializes the daily usage record for today."""
        today_str = date.today().isoformat()
        
        res = self.supabase.table("daily_usage") \
            .select("*") \
            .eq("user_id", user_id) \
            .eq("usage_date", today_str) \
            .execute()

        if res.data and len(res.data) > 0:
            return res.data[0]

        # Insert fresh usage record for today
        new_usage = {
            "user_id": user_id,
            "usage_date": today_str,
            "yt_notes_seconds": 0,
            "ai_notes_count": 0,
            "sims_count": 0,
            "doc_summaries_count": 0,
            "downloads_count": 0
        }
        inserted = self.supabase.table("daily_usage").insert(new_usage).execute()
        return inserted.data[0]

    def verify_action_permission(self, user_id: str, action: str, video_duration_seconds: int = 0) -> bool:
        """
        Constantly checks whether a user can access a service based on their tier,
        subscription validity timeline, and daily usage counters.
        """
        tier, is_active = self.get_active_subscription(user_id)
        limits = PLAN_LIMITS.get(tier, PLAN_LIMITS["FREE"])
        usage = self.get_or_create_daily_usage(user_id)

        if action == "GENERATE_YT_NOTES":
            max_seconds = limits["daily_yt_seconds"]
            current_seconds = usage["yt_notes_seconds"]
            if current_seconds + video_duration_seconds > max_seconds:
                raise HTTPException(
                    status_code=status.HTTP_402_PAYMENT_REQUIRED,
                    detail=f"Daily YouTube note limit reached for plan '{tier}'. Max: {max_seconds // 3600} hours/day."
                )

        elif action == "DOWNLOAD_DOCUMENT":
            if not limits["free_downloads"]:
                raise HTTPException(
                    status_code=status.HTTP_402_PAYMENT_REQUIRED,
                    detail=f"Downloads require a BASIC plan or above (or purchase a Single Download token for 20 KES)."
                )

        elif action == "GENERATE_AI_NOTES":
            max_ai = limits["daily_ai_notes"]
            if usage["ai_notes_count"] >= max_ai:
                raise HTTPException(
                    status_code=status.HTTP_402_PAYMENT_REQUIRED,
                    detail=f"Daily AI Notes limit ({max_ai}/day) reached for '{tier}' plan. Upgrade to Premium for unlimited AI Notes."
                )

        elif action == "GENERATE_SIMULATION":
            max_sims = limits["daily_sims"]
            if usage["sims_count"] >= max_sims:
                raise HTTPException(
                    status_code=status.HTTP_402_PAYMENT_REQUIRED,
                    detail=f"Daily AI Simulation limit ({max_sims}/day) reached for '{tier}' plan. Upgrade to Standard or Premium."
                )

        elif action == "DOC_SUMMARIZATION":
            max_docs = limits["daily_doc_summaries"]
            if usage["doc_summaries_count"] >= max_docs:
                raise HTTPException(
                    status_code=status.HTTP_402_PAYMENT_REQUIRED,
                    detail=f"Daily Document Summarization limit ({max_docs}/day) reached for '{tier}' plan."
                )

        else:
            raise HTTPException(status_code=400, detail=f"Unknown entitlement action: {action}")

        return True

    def record_usage(self, user_id: str, action: str, video_duration_seconds: int = 0):
        """Increments daily usage upon successful service consumption."""
        today_str = date.today().isoformat()
        usage = self.get_or_create_daily_usage(user_id)

        update_payload = {}
        if action == "GENERATE_YT_NOTES":
            update_payload["yt_notes_seconds"] = usage["yt_notes_seconds"] + video_duration_seconds
        elif action == "DOWNLOAD_DOCUMENT":
            update_payload["downloads_count"] = usage["downloads_count"] + 1
        elif action == "GENERATE_AI_NOTES":
            update_payload["ai_notes_count"] = usage["ai_notes_count"] + 1
        elif action == "GENERATE_SIMULATION":
            update_payload["sims_count"] = usage["sims_count"] + 1
        elif action == "DOC_SUMMARIZATION":
            update_payload["doc_summaries_count"] = usage["doc_summaries_count"] + 1

        if update_payload:
            self.supabase.table("daily_usage") \
                .update(update_payload) \
                .eq("id", usage["id"]) \
                .execute()