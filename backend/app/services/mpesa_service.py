import base64
import requests
import uuid
import logging
from datetime import datetime
from ..config import settings

logger = logging.getLogger("notecast_mpesa")

# Dynamic Base URL based on environment
BASE_DARAJA_URL = "https://api.safaricom.co.ke" if settings.MPESA_ENV == "production" else "https://sandbox.safaricom.co.ke"

def get_access_token() -> str:
    """Generates M-Pesa OAuth access token."""
    url = f"{BASE_DARAJA_URL}/oauth/v1/generate?grant_type=client_credentials"
    try:
        response = requests.get(url, auth=(settings.MPESA_CONSUMER_KEY, settings.MPESA_CONSUMER_SECRET), timeout=10)
        response.raise_for_status()
        return response.json().get("access_token")
    except requests.exceptions.RequestException as e:
        logger.error(f"Failed to get M-Pesa access token: {str(e)}")
        raise Exception("M-Pesa authorization failed. Check Daraja credentials.")

def format_phone_number(phone: str) -> str:
    """Formats phone to 254XXXXXXXXX for Daraja API"""
    phone = "".join([c for c in phone if c.isdigit()])
    if phone.startswith("0"):
        return "254" + phone[1:]
    if phone.startswith("254"):
        return phone
    if len(phone) == 9 and (phone.startswith("7") or phone.startswith("1")):
        return "254" + phone
    raise ValueError("Invalid phone number format. Must be a valid Kenyan number.")

def initiate_stk_push(phone_number: str, amount: int, plan_name: str) -> tuple[dict, str]:
    """Triggers an STK push to the user's phone for Paybill (Equity Bank settlement)."""
    formatted_phone = format_phone_number(phone_number)
    if len(formatted_phone) != 12:
        raise ValueError("Phone number must contain exactly 12 digits")

    token = get_access_token()
    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
    password_str = f"{settings.MPESA_BUSINESS_SHORTCODE}{settings.MPESA_PASSKEY}{timestamp}"
    password = base64.b64encode(password_str.encode()).decode("utf-8")

    headers = {"Authorization": f"Bearer {token}"}
    payload = {
        "BusinessShortCode": settings.MPESA_BUSINESS_SHORTCODE,
        "Password": password,
        "Timestamp": timestamp,
        "TransactionType": "CustomerPayBillOnline",  # Updated for Paybill
        "Amount": amount,
        "PartyA": formatted_phone,
        "PartyB": settings.MPESA_BUSINESS_SHORTCODE, # Paybill shortcode (1392922)
        "PhoneNumber": formatted_phone,
        "CallBackURL": settings.MPESA_CALLBACK_URL,
        "AccountReference": f"NC-{plan_name[:10]}",
        "TransactionDesc": f"Payment for {plan_name}"
    }

    url = f"{BASE_DARAJA_URL}/mpesa/stkpush/v1/processrequest"
    response = requests.post(url, json=payload, headers=headers, timeout=15)
    
    return response.json(), formatted_phone

def generate_qr_code(amount: int, merchant_name: str = "Vectis unknown") -> str:
    """Generates a Safaricom Dynamic QR Code for Paybill."""
    token = get_access_token()
    headers = {"Authorization": f"Bearer {token}"}
    
    qr_payload = {
        "MerchantName": merchant_name,
        "RefNo": f"NC-{uuid.uuid4().hex[:6].upper()}",
        "Amount": amount,
        "TrxCode": "PB",  # "PB" for Paybill
        "CPI": settings.MPESA_BUSINESS_SHORTCODE, # 1392922
        "Size": "300"
    }
    
    url = f"{BASE_DARAJA_URL}/mpesa/qrcode/v1/generate"
    res = requests.post(url, json=qr_payload, headers=headers, timeout=15).json()
    
    if res.get("ResponseCode") == "00":
        return res.get("QRCode") # Returns base64 string of the QR code image
    
    raise Exception(res.get("errorMessage", "Failed to generate QR Code"))