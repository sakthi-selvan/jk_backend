from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session
from app.core.dependencies import get_db, get_current_user, get_current_driver_allow_inactive
from app.core.security import get_password_hash, verify_password, create_access_token, create_refresh_token, decode_token
from app.core.config import settings
from app.schemas.auth import (
    SendOTP, VerifyOTP, CompleteProfile,
    UserRegister, UserLogin, DriverRegister, DriverLogin,
    DriverCompleteRegistration,
    AdminLogin, Token
)
from app.models.user import User
from app.models.driver import Driver
from app.models.admin import Admin
from app.services import otp_store
import secrets
import uuid as uuid_mod

router = APIRouter()


def _otp_unusable_password_hash() -> str:
    """Placeholder hash for OTP-only drivers (password login will fail)."""
    return get_password_hash(secrets.token_urlsafe(32))


def _driver_needs_registration(driver: Driver) -> bool:
    return not driver.license_document or not driver.aadhar_document


def _driver_account_status(driver: Driver) -> str:
    if _driver_needs_registration(driver):
        return "incomplete"
    if not driver.is_active:
        return "pending"
    return "active"


def _send_otp_sms(phone: str, otp: str) -> bool:
    """Send OTP via TeleSign SMS when credentials are configured."""
    if not settings.TELESIGN_CUSTOMER_ID or not settings.TELESIGN_API_KEY:
        return False
    try:
        from telesignenterprise.verify import VerifyClient
        verify = VerifyClient(settings.TELESIGN_CUSTOMER_ID, settings.TELESIGN_API_KEY)
        phone_e164 = phone if phone.startswith('91') else f'91{phone}'
        response = verify.sms(phone_e164, verify_code=otp)
        if response.status_code == 200:
            return True
        print(f"[OTP] TeleSign error: {response.status_code} {response.body}")
        return False
    except Exception as e:
        print(f"[OTP] TeleSign exception: {e}")
        return False


@router.post("/send-otp")
async def send_otp(data: SendOTP, db: Session = Depends(get_db)):
    """Send OTP to phone number for login/registration"""
    phone = data.phone.strip()

    allowed, reason = otp_store.check_send_allowed(phone)
    if not allowed:
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail=reason)

    if settings.ALLOW_STATIC_OTP:
        otp = settings.STATIC_OTP[:settings.OTP_LENGTH].ljust(settings.OTP_LENGTH, "0")[:settings.OTP_LENGTH]
        # Prefer a clean static code of correct length
        if settings.OTP_LENGTH == 4:
            otp = settings.STATIC_OTP[-4:] if len(settings.STATIC_OTP) >= 4 else "1234"
        elif settings.OTP_LENGTH == 6:
            otp = settings.STATIC_OTP if len(settings.STATIC_OTP) == 6 else "123456"
    else:
        otp = otp_store.generate_otp()

    otp_store.store_otp(phone, otp)
    otp_store.record_send(phone)

    sms_sent = False
    if not settings.ALLOW_STATIC_OTP:
        sms_sent = _send_otp_sms(phone, otp)
        if not sms_sent:
            # Do not leak OTP; fail closed when SMS provider is unavailable
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Unable to send OTP right now. Please try again.",
            )

    return {
        "message": "OTP sent successfully",
        "otp_length": settings.OTP_LENGTH,
        "dev_mode": settings.ALLOW_STATIC_OTP,
    }


@router.post("/verify-otp")
async def verify_otp_endpoint(data: VerifyOTP, db: Session = Depends(get_db)):
    """Verify OTP and return tokens. Creates user if new."""
    phone = data.phone.strip()
    otp = data.otp.strip()

    ok, reason = otp_store.verify_and_consume(phone, otp)
    if not ok:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=reason,
        )

    user = db.query(User).filter(User.phone == phone).first()
    is_new_user = False

    if not user:
        user = User(
            phone=phone,
            name=phone,
            is_verified=True,
            is_active=True,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        is_new_user = True
    else:
        user.is_verified = True
        db.commit()

    access_token = create_access_token(data={"sub": str(user.id), "role": "user"})
    refresh_token = create_refresh_token(data={"sub": str(user.id), "role": "user"})

    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": "bearer",
        "is_new_user": is_new_user,
    }


@router.put("/complete-profile")
async def complete_profile_endpoint(
    data: CompleteProfile,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Complete user profile after OTP verification (for new users)"""
    current_user.name = data.name
    if data.email:
        existing = db.query(User).filter(User.email == data.email, User.id != current_user.id).first()
        if existing:
            raise HTTPException(status_code=400, detail="Email already in use")
        current_user.email = data.email
    if data.age is not None:
        current_user.age = data.age
    if data.gender:
        current_user.gender = data.gender
    if data.emergency_contact_name:
        current_user.emergency_contact_name = data.emergency_contact_name
    if data.emergency_contact_phone:
        current_user.emergency_contact_phone = data.emergency_contact_phone
    db.commit()

    return {"message": "Profile updated successfully"}


# === Driver OTP auth ===

@router.post("/driver/send-otp")
async def send_driver_otp(data: SendOTP, db: Session = Depends(get_db)):
    """Send OTP for driver login / registration (same store as customer OTP)."""
    return await send_otp(data, db)


@router.post("/driver/verify-otp")
async def verify_driver_otp(data: VerifyOTP, db: Session = Depends(get_db)):
    """Verify OTP for drivers. Creates an incomplete driver stub for new phones."""
    phone = data.phone.strip()
    otp = data.otp.strip()

    ok, reason = otp_store.verify_and_consume(phone, otp)
    if not ok:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=reason)

    driver = db.query(Driver).filter(Driver.phone == phone).first()
    is_new_driver = False

    if not driver:
        driver = Driver(
            id=uuid_mod.uuid4(),
            phone=phone,
            name=phone,
            password_hash=_otp_unusable_password_hash(),
            is_verified=False,
            is_active=False,
        )
        db.add(driver)
        db.commit()
        db.refresh(driver)
        is_new_driver = True
    else:
        # Returning incomplete signup still counts as "new" for the app wizard
        is_new_driver = _driver_needs_registration(driver)

    account_status = _driver_account_status(driver)
    access_token = create_access_token(data={"sub": str(driver.id), "role": "driver"})
    refresh_token = create_refresh_token(data={"sub": str(driver.id), "role": "driver"})

    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": "bearer",
        "is_new_driver": is_new_driver,
        "is_active": bool(driver.is_active),
        "account_status": account_status,
    }


@router.put("/driver/complete-registration")
async def complete_driver_registration(
    data: DriverCompleteRegistration,
    driver: Driver = Depends(get_current_driver_allow_inactive),
    db: Session = Depends(get_db),
):
    """Finish OTP signup: profile + vehicle + KYC docs. Stays pending until admin approval."""
    from app.services.document_storage import save_driver_document_data_uri

    if data.email:
        existing = db.query(Driver).filter(Driver.email == data.email, Driver.id != driver.id).first()
        if existing:
            raise HTTPException(status_code=400, detail="Email already in use")

    if not data.license_document or not data.aadhar_document:
        raise HTTPException(status_code=400, detail="License and Aadhar documents are required")

    license_url = save_driver_document_data_uri(driver.id, "license", data.license_document)
    aadhar_url = save_driver_document_data_uri(driver.id, "aadhar", data.aadhar_document)
    vehicle_url = None
    if data.vehicle_image:
        vehicle_url = save_driver_document_data_uri(driver.id, "vehicle", data.vehicle_image)

    driver.name = data.name
    driver.email = data.email
    driver.vehicle_number = data.vehicle_number
    driver.vehicle_type = data.vehicle_type
    if data.gender:
        driver.gender = data.gender
    driver.license_document = license_url
    driver.aadhar_document = aadhar_url
    if vehicle_url:
        driver.vehicle_image = vehicle_url
    driver.is_verified = False
    driver.is_active = False
    db.commit()
    db.refresh(driver)

    return {
        "message": "Registration submitted. Waiting for admin approval.",
        "account_status": "pending",
    }


# === Legacy password-based endpoints (kept for driver/admin) ===

@router.post("/register", response_model=Token, status_code=status.HTTP_201_CREATED)
async def register_user(user_data: UserRegister, db: Session = Depends(get_db)):
    """Register new user (legacy)"""
    existing_user = db.query(User).filter(User.phone == user_data.phone).first()
    if existing_user:
        raise HTTPException(status_code=400, detail="Phone number already registered")

    if user_data.email:
        existing_email = db.query(User).filter(User.email == user_data.email).first()
        if existing_email:
            raise HTTPException(status_code=400, detail="Email already registered")

    new_user = User(
        phone=user_data.phone,
        name=user_data.name,
        email=user_data.email,
        password_hash=get_password_hash(user_data.password),
        is_verified=False
    )
    db.add(new_user)
    db.commit()
    db.refresh(new_user)

    access_token = create_access_token(data={"sub": str(new_user.id), "role": "user"})
    refresh_token = create_refresh_token(data={"sub": str(new_user.id), "role": "user"})

    return {"access_token": access_token, "refresh_token": refresh_token, "token_type": "bearer"}


@router.post("/login", response_model=Token)
async def login_user(user_data: UserLogin, db: Session = Depends(get_db)):
    """User login (legacy)"""
    user = db.query(User).filter(User.phone == user_data.phone).first()
    if not user:
        raise HTTPException(status_code=401, detail="Incorrect phone or password")

    if not user.password_hash or not verify_password(user_data.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Incorrect phone or password")

    if not user.is_active:
        raise HTTPException(status_code=400, detail="User account is inactive")

    access_token = create_access_token(data={"sub": str(user.id), "role": "user"})
    refresh_token = create_refresh_token(data={"sub": str(user.id), "role": "user"})

    return {"access_token": access_token, "refresh_token": refresh_token, "token_type": "bearer"}


@router.post("/driver/register", response_model=Token, status_code=status.HTTP_201_CREATED)
async def register_driver(driver_data: DriverRegister, db: Session = Depends(get_db)):
    """Register new driver — KYC images are saved to disk; DB stores short URL paths."""
    from app.services.document_storage import save_driver_document_data_uri

    existing_driver = db.query(Driver).filter(Driver.phone == driver_data.phone).first()
    if existing_driver:
        raise HTTPException(status_code=400, detail="Phone number already registered")

    if driver_data.email:
        existing_email = db.query(Driver).filter(Driver.email == driver_data.email).first()
        if existing_email:
            raise HTTPException(status_code=400, detail="Email already registered")

    if not driver_data.license_document or not driver_data.aadhar_document:
        raise HTTPException(
            status_code=400,
            detail="License and Aadhar documents are required",
        )

    driver_id = uuid_mod.uuid4()
    license_url = save_driver_document_data_uri(driver_id, "license", driver_data.license_document)
    aadhar_url = save_driver_document_data_uri(driver_id, "aadhar", driver_data.aadhar_document)

    new_driver = Driver(
        id=driver_id,
        phone=driver_data.phone,
        name=driver_data.name,
        email=driver_data.email,
        password_hash=get_password_hash(driver_data.password),
        vehicle_number=driver_data.vehicle_number,
        vehicle_type=driver_data.vehicle_type,
        license_document=license_url,
        aadhar_document=aadhar_url,
        is_verified=False,
        is_active=False,
    )
    db.add(new_driver)
    db.commit()
    db.refresh(new_driver)

    access_token = create_access_token(data={"sub": str(new_driver.id), "role": "driver"})
    refresh_token = create_refresh_token(data={"sub": str(new_driver.id), "role": "driver"})

    return {"access_token": access_token, "refresh_token": refresh_token, "token_type": "bearer"}


@router.post("/driver/login", response_model=Token)
async def login_driver(driver_data: DriverLogin, db: Session = Depends(get_db)):
    """Driver login"""
    driver = db.query(Driver).filter(Driver.phone == driver_data.phone).first()
    if not driver:
        raise HTTPException(status_code=401, detail="Incorrect phone or password")

    if not verify_password(driver_data.password, driver.password_hash):
        raise HTTPException(status_code=401, detail="Incorrect phone or password")

    if not driver.is_active:
        raise HTTPException(status_code=403, detail="ACCOUNT_PENDING_APPROVAL")

    access_token = create_access_token(data={"sub": str(driver.id), "role": "driver"})
    refresh_token = create_refresh_token(data={"sub": str(driver.id), "role": "driver"})

    return {"access_token": access_token, "refresh_token": refresh_token, "token_type": "bearer"}


@router.post("/admin/login", response_model=Token)
async def login_admin(admin_data: AdminLogin, db: Session = Depends(get_db)):
    """Admin login"""
    admin = db.query(Admin).filter(Admin.username == admin_data.username).first()
    if not admin:
        raise HTTPException(status_code=401, detail="Incorrect username or password")

    if not verify_password(admin_data.password, admin.password_hash):
        raise HTTPException(status_code=401, detail="Incorrect username or password")

    if not admin.is_active:
        raise HTTPException(status_code=400, detail="Admin account is inactive")

    access_token = create_access_token(data={"sub": str(admin.id), "role": "admin"})
    refresh_token = create_refresh_token(data={"sub": str(admin.id), "role": "admin"})

    return {"access_token": access_token, "refresh_token": refresh_token, "token_type": "bearer"}


class RefreshTokenRequest(BaseModel):
    refresh_token: str


@router.post("/refresh", response_model=Token)
async def refresh_access_token(request: RefreshTokenRequest, db: Session = Depends(get_db)):
    """Refresh access token using refresh token"""
    payload = decode_token(request.refresh_token)

    if not payload or payload.get("type") != "refresh":
        raise HTTPException(status_code=401, detail="Invalid refresh token")

    user_id = payload.get("sub")
    role = payload.get("role", "user")

    if not user_id:
        raise HTTPException(status_code=401, detail="Invalid token payload")

    # Validate subject still exists and is active
    if role == "user":
        entity = db.query(User).filter(User.id == user_id).first()
        if not entity or not entity.is_active:
            raise HTTPException(status_code=401, detail="Account invalid")
    elif role == "driver":
        entity = db.query(Driver).filter(Driver.id == user_id).first()
        if not entity or not entity.is_active:
            raise HTTPException(status_code=401, detail="Account invalid")
    elif role == "admin":
        entity = db.query(Admin).filter(Admin.id == user_id).first()
        if not entity or not entity.is_active:
            raise HTTPException(status_code=401, detail="Account invalid")
    else:
        raise HTTPException(status_code=401, detail="Invalid token role")

    access_token = create_access_token(data={"sub": user_id, "role": role})
    new_refresh_token = create_refresh_token(data={"sub": user_id, "role": role})

    return {"access_token": access_token, "refresh_token": new_refresh_token, "token_type": "bearer"}
