from fastapi import HTTPException, status, Depends
from sqlalchemy.orm import Session
from datetime import date, datetime, timezone
import uuid
from .models import User, UserSubscription, DailyUsage, OneOffCredit, ResourceNoteUsage

TIER_LIMITS = {
    "ECONOMY": { 
        "yt_seconds": 0, "free_downloads": False, "ai_notes_daily": 0,
        "static_sims_daily": 0, "llm_sims_daily": 0, "doc_summaries_daily": 0
    },
    "STARTUP": { 
        "yt_seconds": 3600, "free_downloads": False, "ai_notes_daily": 0,
        "static_sims_daily": 0, "llm_sims_daily": 0, "doc_summaries_daily": 0
    },
    "BASIC": { 
        "yt_seconds": 7200, "free_downloads": True, "ai_notes_daily": 0, 
        "static_sims_daily": 0, "llm_sims_daily": 0, "doc_summaries_daily": 0
    },
    "STANDARD": { 
        "yt_seconds": 14400, "free_downloads": True, "ai_notes_daily": 2,
        "static_sims_daily": 2, "llm_sims_daily": 0, "doc_summaries_daily": 2
    },
    "PREMIUM": { 
        "yt_seconds": 43200, "free_downloads": True, "ai_notes_daily": 999, 
        "static_sims_daily": 5, "llm_sims_daily": 2, "doc_summaries_daily": 6
    }
}

def get_or_create_daily_usage(db: Session, user_id: str) -> DailyUsage:
    today = date.today()
    usage = db.query(DailyUsage).filter(DailyUsage.user_id == user_id, DailyUsage.usage_date == today).first()
    if not usage:
        usage = DailyUsage(id=str(uuid.uuid4()), user_id=user_id, usage_date=today)
        db.add(usage)
        db.commit()
        db.refresh(usage)
    return usage

def verify_action_entitlement(
    user_id: str, 
    action_type: str, 
    video_duration_seconds: int = 0,
    resource_id: str = None,
    db: Session = None
):
    now = datetime.now(timezone.utc)
    sub = db.query(UserSubscription).filter(UserSubscription.user_id == user_id).first()
    
    tier = "ECONOMY"
    if sub and sub.tier in TIER_LIMITS:
        exp = sub.expires_at
        if exp:
            if exp.tzinfo is None:
                exp = exp.replace(tzinfo=timezone.utc)
            if exp > now:
                tier = sub.tier
        else:
            tier = sub.tier

    limits = TIER_LIMITS[tier]
    usage = get_or_create_daily_usage(db, user_id)

    if action_type == "YOUTUBE_GENERATE":
        if tier == "ECONOMY":
            credit = db.query(OneOffCredit).filter(
                OneOffCredit.user_id == user_id,
                OneOffCredit.credit_type == "ECONOMY_NOTE",
                OneOffCredit.is_redeemed == False
            ).first()
            if not credit:
                raise HTTPException(
                    status_code=status.HTTP_402_PAYMENT_REQUIRED,
                    detail="Economy Plan requires a 50 KES token per YouTube note generation."
                )
        elif usage.youtube_seconds + video_duration_seconds > limits["yt_seconds"]:
            raise HTTPException(
                status_code=status.HTTP_402_PAYMENT_REQUIRED,
                detail=f"Daily YouTube video processing limit reached for {tier} plan."
            )

    elif action_type == "DOWNLOAD_DOCUMENT":
        user_record = db.query(User).filter(User.id == user_id).first()
        pass_until = getattr(user_record, "unlimited_downloads_until", None)
        
        has_pass = False
        if pass_until:
            if pass_until.tzinfo is None:
                pass_until = pass_until.replace(tzinfo=timezone.utc)
            has_pass = pass_until > now

        if not limits["free_downloads"] and not has_pass:
            credit = db.query(OneOffCredit).filter(
                OneOffCredit.user_id == user_id,
                OneOffCredit.credit_type.in_(["SINGLE_DOWNLOAD", "DOWNLOAD_PASS"]),
                OneOffCredit.is_redeemed == False
            ).first()
            if not credit:
                raise HTTPException(
                    status_code=status.HTTP_402_PAYMENT_REQUIRED,
                    detail="Downloads require a Basic subscription or a 20 KES weekly download pass."
                )

    elif action_type == "GENERATE_AI_NOTES":
        # 20 KES pay-per-use token or active pass check for AI notes
        user_record = db.query(User).filter(User.id == user_id).first()
        pass_until = getattr(user_record, "unlimited_downloads_until", None)
        has_pass = False
        if pass_until:
            if pass_until.tzinfo is None:
                pass_until = pass_until.replace(tzinfo=timezone.utc)
            has_pass = pass_until > now

        has_ai_credit = db.query(OneOffCredit).filter(
            OneOffCredit.user_id == user_id,
            OneOffCredit.credit_type.in_(["SINGLE_AI_NOTE", "SINGLE_DOWNLOAD", "DOWNLOAD_PASS"]),
            OneOffCredit.is_redeemed == False
        ).first() is not None

        if tier in ["STANDARD", "PREMIUM"]:
            if usage.ai_notes_count >= limits["ai_notes_daily"] and not has_ai_credit:
                raise HTTPException(
                    status_code=status.HTTP_402_PAYMENT_REQUIRED,
                    detail=f"Daily limit of {limits['ai_notes_daily']} AI notes reached for {tier} plan."
                )
        elif not has_pass and not has_ai_credit:
            raise HTTPException(
                status_code=status.HTTP_402_PAYMENT_REQUIRED,
                detail="AI Note generation requires a 20 KES pass/token or an upgraded plan."
            )

        if resource_id:
            res_usage = db.query(ResourceNoteUsage).filter(
                ResourceNoteUsage.user_id == user_id,
                ResourceNoteUsage.resource_id == resource_id
            ).first()
            if res_usage and res_usage.ai_gen_attempts >= 2:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Maximum limit of 2 AI Note generations per specific video reached."
                )

    elif action_type == "LAUNCH_STATIC_SIM":
        if usage.static_sims_count >= limits["static_sims_daily"]:
            raise HTTPException(
                status_code=status.HTTP_402_PAYMENT_REQUIRED,
                detail=f"Static simulation limit reached for {tier} plan."
            )

    elif action_type == "GENERATE_LLM_SIM":
        if tier != "PREMIUM":
            raise HTTPException(
                status_code=status.HTTP_402_PAYMENT_REQUIRED,
                detail="Live LLM Simulation synthesis requires the Premium package."
            )
        if usage.llm_sims_count >= limits["llm_sims_daily"]:
            raise HTTPException(
                status_code=status.HTTP_402_PAYMENT_REQUIRED,
                detail="Daily limit of 2 live LLM simulations reached."
            )

    elif action_type == "DOC_SUMMARIZATION":
        if tier not in ["STANDARD", "PREMIUM"]:
            raise HTTPException(
                status_code=status.HTTP_402_PAYMENT_REQUIRED,
                detail="Document summarization requires Standard (800 KES) or Premium (1199 KES)."
            )
        if usage.doc_summaries_count >= limits["doc_summaries_daily"]:
            raise HTTPException(
                status_code=status.HTTP_402_PAYMENT_REQUIRED,
                detail=f"Daily document summary limit reached ({limits['doc_summaries_daily']}/day)."
            )
        if resource_id:
            res_usage = db.query(ResourceNoteUsage).filter(
                ResourceNoteUsage.user_id == user_id,
                ResourceNoteUsage.resource_id == resource_id
            ).first()
            if res_usage and res_usage.summary_attempts >= 2:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Maximum limit of 2 summaries per document reached."
                )