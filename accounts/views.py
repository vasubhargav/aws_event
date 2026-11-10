
import logging
import secrets
import uuid
from datetime import timedelta

from django.conf import settings
from django.contrib.auth import authenticate
from django.contrib.auth.hashers import make_password, check_password
from django.contrib.auth.models import User
from django.db import IntegrityError, transaction
from django.db.models.deletion import ProtectedError
from django.utils import timezone
from django.utils.text import slugify

from .permissions import IsSuperUser

import requests

from rest_framework import status
from rest_framework.authtoken.models import Token
from rest_framework.response import Response
from rest_framework.throttling import AnonRateThrottle, UserRateThrottle
from rest_framework.views import APIView

from .models import StudentProfile, EmailOTP, PendingRegistration
from .serializers import RegisterSerializer

from qr.services import send_student_qr_email

from .throttles import (
    LoginRateThrottle,
    OTPRateThrottle,
    RegisterRateThrottle,
    ResendOTPThrottle,
    DeleteRegistrationThrottle,
)
from .services import (
    send_pending_registration_otp,
    send_student_otp,
)


logger = logging.getLogger(__name__)


# --------------------------------------------------
# GOOGLE RECAPTCHA V2 VERIFICATION
# --------------------------------------------------

def verify_recaptcha(captcha_token):

    if not captcha_token:
        return False, ["missing-input-response"]

    secret = getattr(settings, "RECAPTCHA_SECRET_KEY", None)

    if not secret:
        logger.error("RECAPTCHA_SECRET_KEY is not configured")
        return False, ["missing-input-secret"]

    try:

        response = requests.post(
            "https://www.google.com/recaptcha/api/siteverify",
            data={
                "secret": secret,
                "response": captcha_token
            },
            timeout=10
        )

        response.raise_for_status()

        result = response.json()

        logger.info("Google CAPTCHA success: %s",
                    result.get("success"))

        return (
            result.get("success", False),
            result.get("error-codes", [])
        )

    except (requests.RequestException, ValueError):

        logger.exception("Google CAPTCHA verification request failed")

        return False, ["verification-request-failed"]


# --------------------------------------------------
# OTP GENERATION
# --------------------------------------------------

def generate_otp():

    return str(secrets.randbelow(900000) + 100000)


# --------------------------------------------------
# SEND QR EMAIL SAFELY
# --------------------------------------------------

def send_qr_email_safely(profile):

    try:

        send_student_qr_email(profile)

    except Exception:

        logger.exception(
            "QR email failed for student %s",
            profile.student_no
        )


# --------------------------------------------------
# REGISTER API
# --------------------------------------------------


class RegisterView(APIView):
    throttle_classes = [
        AnonRateThrottle,
        UserRateThrottle,
        RegisterRateThrottle,
    ]
    

    def post(self, request):

        # 1. Validate registration data
        serializer = RegisterSerializer(data=request.data)

        if not serializer.is_valid():
            return Response(
                {
                    "success": False,
                    "errors": serializer.errors
                },
                status=status.HTTP_400_BAD_REQUEST
            )

        data = serializer.validated_data.copy()

        # 2. Verify Google reCAPTCHA
        captcha_token = data.pop("recaptcha_token")

        captcha_valid, captcha_errors = verify_recaptcha(
            captcha_token
        )

        if not captcha_valid:
            return Response(
                {
                    "success": False,
                    "error": "CAPTCHA verification failed. Please try again.",
                    "details": captcha_errors
                },
                status=status.HTTP_400_BAD_REQUEST
            )

        email = data["email"].strip().lower()
        now = timezone.now()

        # 3. Generate OTP
        otp = generate_otp()

        try:
            with transaction.atomic():

                # Remove expired pending registrations
                PendingRegistration.objects.filter(
                    registration_expires_at__lte=now
                ).delete()

                # Recheck permanent records
                if User.objects.filter(
                    email__iexact=email
                ).exists():
                    return Response(
                        {
                            "success": False,
                            "error": "Email already registered."
                        },
                        status=status.HTTP_400_BAD_REQUEST
                    )

                if StudentProfile.objects.filter(
                    roll_no__iexact=data["roll_no"]
                ).exists():
                    return Response(
                        {
                            "success": False,
                            "error": "Roll number already registered."
                        },
                        status=status.HTTP_400_BAD_REQUEST
                    )

                if StudentProfile.objects.filter(
                    student_no__iexact=data["student_no"]
                ).exists():
                    return Response(
                        {
                            "success": False,
                            "error": "Student number already registered."
                        },
                        status=status.HTTP_400_BAD_REQUEST
                    )

                # Recheck pending registrations
                if PendingRegistration.objects.filter(
                    registration_expires_at__gt=now,
                    registration_data__email=email
                ).exists():
                    return Response(
                        {
                            "success": False,
                            "error": "Registration is already pending for this email."
                        },
                        status=status.HTTP_400_BAD_REQUEST
                    )

                # 4. Save temporary registration
                pending = PendingRegistration.objects.create(
                    registration_data=data,
                    otp_hash=make_password(otp),
                    attempts=0,
                    otp_expires_at=now + timedelta(minutes=5),
                    registration_expires_at=now + timedelta(minutes=10),
                    otp_last_sent_at=now
                )

                # 5. Send OTP
                email_sent = send_pending_registration_otp(
                    email,
                    data["name"],
                    otp
                )

                if email_sent != 1:
                    raise RuntimeError("OTP email could not be sent")

            return Response(
                {
                    "success": True,
                    "message": "Registration initiated. OTP sent to your email.",
                    "registration_id": str(pending.registration_id),
                    "name": data["name"],
                    "email": email,
                    "student_no": data["student_no"]
                },
                status=status.HTTP_201_CREATED
            )

        except Exception:
            logger.exception("Pending registration failed")

            return Response(
                {
                    "success": False,
                    "error": "Unable to initiate registration. Please try again."
                },
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


# --------------------------------------------------
# VERIFY REGISTRATION OTP API
# --------------------------------------------------


class VerifyOTPView(APIView):
    throttle_classes = [
        AnonRateThrottle,
        UserRateThrottle,
        OTPRateThrottle,
    ]

    def post(self, request):

        email = (
            request.data.get("email") or ""
        ).strip().lower()

        student_no = (
            request.data.get("student_no") or ""
        ).strip()

        otp = (
            request.data.get("otp") or ""
        ).strip()

        if not email or not student_no or not otp:
            return Response(
                {
                    "success": False,
                    "error": "Email, student number and OTP are required."
                },
                status=status.HTTP_400_BAD_REQUEST
            )

        if not otp.isdigit() or len(otp) != 6:
            return Response(
                {
                    "success": False,
                    "error": "Enter a valid 6-digit OTP."
                },
                status=status.HTTP_400_BAD_REQUEST
            )

        try:
            with transaction.atomic():

                # Lock pending registration
                pending = PendingRegistration.objects.select_for_update().filter(
                    registration_data__email=email,
                    registration_data__student_no=student_no
                ).first()

                if pending is None:
                    return Response(
                        {
                            "success": False,
                            "error": "Pending registration not found."
                        },
                        status=status.HTTP_404_NOT_FOUND
                    )

                now = timezone.now()

                # Check registration expiry
                if pending.registration_expires_at <= now:
                    pending.delete()

                    return Response(
                        {
                            "success": False,
                            "error": "Registration expired. Please register again."
                        },
                        status=status.HTTP_400_BAD_REQUEST
                    )

                # Check OTP expiry
                if pending.otp_expires_at <= now:
                    return Response(
                        {
                            "success": False,
                            "error": "OTP expired. Please request a new OTP."
                        },
                        status=status.HTTP_400_BAD_REQUEST
                    )

                # Maximum 5 attempts
                if pending.attempts >= 5:
                    return Response(
                        {
                            "success": False,
                            "error": "Maximum OTP attempts reached. Please resend OTP."
                        },
                        status=status.HTTP_429_TOO_MANY_REQUESTS
                    )

                # Verify hashed OTP
                if not check_password(otp, pending.otp_hash):

                    pending.attempts += 1

                    pending.save(update_fields=["attempts"])

                    if pending.attempts >= 5:
                        return Response(
                            {
                                "success": False,
                                "error": "Maximum OTP attempts reached. Please resend OTP."
                            },
                            status=status.HTTP_429_TOO_MANY_REQUESTS
                        )

                    return Response(
                        {
                            "success": False,
                            "error": "Incorrect OTP.",
                            "attempts_remaining": 5 - pending.attempts
                        },
                        status=status.HTTP_400_BAD_REQUEST
                    )

                # OTP verified successfully
                data = pending.registration_data

                # Final duplicate checks
                if User.objects.filter(
                    email__iexact=data["email"]
                ).exists():
                    pending.delete()

                    return Response(
                        {
                            "success": False,
                            "error": "Email is already registered."
                        },
                        status=status.HTTP_409_CONFLICT
                    )

                if StudentProfile.objects.filter(
                    roll_no__iexact=data["roll_no"]
                ).exists() or StudentProfile.objects.filter(
                    student_no__iexact=data["student_no"]
                ).exists():
                    pending.delete()

                    return Response(
                        {
                            "success": False,
                            "error": "Roll number or student number is already registered."
                        },
                        status=status.HTTP_409_CONFLICT
                    )

                # Generate unique username
                username_base = slugify(data["name"])[:140] or "student"

                username = (
                    f"{username_base}_{uuid.uuid4().hex[:8]}"
                )

                # Create permanent Django User
                user = User.objects.create_user(
                    username=username,
                    email=data["email"],
                    password=None,
                    is_active=True
                )

                # Create permanent StudentProfile
                profile = StudentProfile.objects.create(
                    user=user,
                    name=data["name"],
                    branch=data["branch"],
                    section=data["section"],
                    year=data["year"],
                    residence=data["residence"],
                    gender=data["gender"],
                    phone_no=data["phone_no"],
                    roll_no=data["roll_no"],
                    student_no=data["student_no"],
                    is_email_verified=True
                )

                # Delete temporary registration
                pending.delete()

                # Send QR email after successful DB commit
                transaction.on_commit(
                    lambda: send_qr_email_safely(profile)
                )

            return Response(
                {
                    "success": True,
                    "message": "Email verified and registration completed successfully.",
                    "name": profile.name,
                    "email": user.email,
                    "student_no": profile.student_no,
                    "qr_email": "QR email sending was attempted."
                },
                status=status.HTTP_200_OK
            )

        except IntegrityError:
            logger.exception("Duplicate registration during OTP verification")

            return Response(
                {
                    "success": False,
                    "error": "Registration details already exist. Please contact support if this continues."
                },
                status=status.HTTP_409_CONFLICT
            )

        except Exception:
            logger.exception("OTP verification failed")

            return Response(
                {
                    "success": False,
                    "error": "Unable to verify registration. Please try again."
                },
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )



# --------------------------------------------------
# RESEND OTP API
# --------------------------------------------------


class ResendOTPView(APIView):
    throttle_classes = [
        AnonRateThrottle,
        UserRateThrottle,
        ResendOTPThrottle,
    ]


    def post(self, request):

        email = (
            request.data.get("email") or ""
        ).strip().lower()

        student_no = (
            request.data.get("student_no") or ""
        ).strip()

        if not email or not student_no:
            return Response(
                {
                    "success": False,
                    "error": "Email and student number are required."
                },
                status=status.HTTP_400_BAD_REQUEST
            )

        try:
            with transaction.atomic():

                pending = PendingRegistration.objects.select_for_update().filter(
                    registration_data__email=email,
                    registration_data__student_no=student_no
                ).first()

                if pending is None:
                    return Response(
                        {
                            "success": False,
                            "error": "Pending registration not found."
                        },
                        status=status.HTTP_404_NOT_FOUND
                    )

                now = timezone.now()

                if pending.registration_expires_at <= now:
                    pending.delete()

                    return Response(
                        {
                            "success": False,
                            "error": "Registration expired. Please register again."
                        },
                        status=status.HTTP_400_BAD_REQUEST
                    )

                # 60-second resend cooldown
                elapsed = (
                    now - pending.otp_last_sent_at
                ).total_seconds()

                if elapsed < 60:
                    remaining = max(1, 60 - int(elapsed))

                    return Response(
                        {
                            "success": False,
                            "error": "Please wait before requesting another OTP.",
                            "retry_after": remaining
                        },
                        status=status.HTTP_429_TOO_MANY_REQUESTS
                    )

                # Generate new OTP
                otp = generate_otp()

                pending.otp_hash = make_password(otp)

                pending.otp_expires_at = (
                    now + timedelta(minutes=5)
                )

                pending.otp_last_sent_at = now

                pending.attempts = 0

                pending.save(
                    update_fields=[
                        "otp_hash",
                        "otp_expires_at",
                        "otp_last_sent_at",
                        "attempts"
                    ]
                )

                # Send new OTP
                email_sent = send_pending_registration_otp(
                    email,
                    pending.registration_data["name"],
                    otp
                )

                if email_sent != 1:
                    raise RuntimeError("OTP resend failed")

            return Response(
                {
                    "success": True,
                    "message": "A new OTP has been sent successfully.",
                    "student_no": student_no
                },
                status=status.HTTP_200_OK
            )

        except Exception:
            logger.exception("Registration OTP resend failed")

            return Response(
                {
                    "success": False,
                    "error": "Unable to resend OTP. Please try again later."
                },
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )



# --------------------------------------------------
# PASSWORDLESS LOGIN - SEND OTP
# --------------------------------------------------

class LoginView(APIView):
    throttle_classes = [
        AnonRateThrottle,
        UserRateThrottle,
        LoginRateThrottle,
    ]

    def post(self, request):

        student_no = (
            request.data.get("student_no") or ""
        ).strip()

        if not student_no:

            return Response(
                {
                    "error": "Student number is required."
                },
                status=status.HTTP_400_BAD_REQUEST
            )

        try:

            profile = StudentProfile.objects.select_related(
                "user"
            ).get(
                student_no=student_no
            )

        except StudentProfile.DoesNotExist:

            return Response(
                {
                    "error": "Student account not found."
                },
                status=status.HTTP_404_NOT_FOUND
            )

        user = profile.user

        if not user.is_active or not profile.is_email_verified:

            return Response(
                {
                    "error": "Please verify your email before logging in."
                },
                status=status.HTTP_403_FORBIDDEN
            )

        otp = generate_otp()

        try:

            with transaction.atomic():

                # Delete previous login OTP

                EmailOTP.objects.filter(
                    user=user
                ).delete()

                # Generate new login OTP

                EmailOTP.objects.create(
                    user=user,
                    otp=otp,
                    expires_at=(
                        timezone.now() + timedelta(minutes=5)
                    )
                )

                email_sent = send_student_otp(
                    user,
                    profile.name,
                    otp
                )

                if email_sent != 1:
                    raise RuntimeError("Login OTP email could not be sent")

        except Exception:

            logger.exception("Login OTP sending failed")

            return Response(
                {
                    "error": "Unable to send login OTP. Please try again."
                },
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

        return Response(
            {
                "success": True,
                "message": "Login OTP sent to your registered email.",
                "student_no": profile.student_no
            },
            status=status.HTTP_200_OK
        )


# --------------------------------------------------
# PASSWORDLESS LOGIN - VERIFY OTP
# --------------------------------------------------

class VerifyLoginOTPView(APIView):
    throttle_classes = [
        AnonRateThrottle,
        UserRateThrottle,
        OTPRateThrottle,
    ]

    def post(self, request):

        student_no = (
            request.data.get("student_no") or ""
        ).strip()

        email = (
            request.data.get("email") or ""
        ).strip().lower()

        otp = (
            request.data.get("otp") or ""
        ).strip()

        if not student_no or not email or not otp:

            return Response(
                {
                    "error": "Student number, email and OTP are required."
                },
                status=status.HTTP_400_BAD_REQUEST
            )

        try:

            profile = StudentProfile.objects.select_related(
                "user"
            ).get(
                student_no=student_no,
                user__email__iexact=email
            )

        except StudentProfile.DoesNotExist:

            return Response(
                {
                    "error": "Invalid student details."
                },
                status=status.HTTP_404_NOT_FOUND
            )

        user = profile.user

        if not user.is_active or not profile.is_email_verified:

            return Response(
                {
                    "error": "Please verify your email before logging in."
                },
                status=status.HTTP_403_FORBIDDEN
            )

        with transaction.atomic():

            otp_record = EmailOTP.objects.select_for_update().filter(
                user=user
            ).order_by("-created_at").first()

            if otp_record is None:

                return Response(
                    {
                        "error": "OTP not found. Please request a new OTP."
                    },
                    status=status.HTTP_400_BAD_REQUEST
                )

            if otp_record.expires_at < timezone.now():

                return Response(
                    {
                        "error": "OTP has expired. Please request a new OTP."
                    },
                    status=status.HTTP_400_BAD_REQUEST
                )

            if not secrets.compare_digest(
                str(otp_record.otp),
                otp
            ):

                return Response(
                    {
                        "error": "Incorrect OTP."
                    },
                    status=status.HTTP_400_BAD_REQUEST
                )

            # OTP is valid. Delete it to prevent reuse.

            EmailOTP.objects.filter(
                user=user
            ).delete()

            # Generate authentication token

            token, created = Token.objects.get_or_create(
                user=user
            )

        return Response(
            {
                "success": True,
                "message": "Login successful.",
                "name": profile.name,
                "email": user.email,
                "student_no": profile.student_no,
                "token": token.key
            },
            status=status.HTTP_200_OK
        )
class SuperuserLoginView(APIView):
    throttle_classes = [
        AnonRateThrottle,
        UserRateThrottle,
        LoginRateThrottle,
    ]

    def post(self, request):

        username = request.data.get("username", "").strip()
        password = request.data.get("password", "")

        if not username or not password:
            return Response(
                {"error": "Username and password are required."},
                status=status.HTTP_400_BAD_REQUEST
            )

        user = authenticate(
            username=username,
            password=password
        )

        if (
            user is None
            or not user.is_active
            or not user.is_superuser
        ):
            return Response(
                {"error": "Invalid superuser credentials."},
                status=status.HTTP_401_UNAUTHORIZED
            )

        token, _ = Token.objects.get_or_create(user=user)

        return Response(
            {
                "message": "Superuser login successful.",
                "username": user.username,
                "token": token.key
            },
            status=status.HTTP_200_OK
        )

class DeleteRegistrationView(APIView):
    throttle_classes = [
        AnonRateThrottle,
        UserRateThrottle,
        DeleteRegistrationThrottle,
    ]

    permission_classes = [IsSuperUser]

    def delete(self, request):

        student_no = request.data.get("student_no")

        # Check student number
        if not student_no:
            return Response(
                {
                    "success": False,
                    "message": "Student number is required."
                },
                status=status.HTTP_400_BAD_REQUEST
            )

        # Find student registration
        try:
            student = StudentProfile.objects.select_related(
                "user"
            ).get(student_no=student_no)

        except StudentProfile.DoesNotExist:
            return Response(
                {
                    "success": False,
                    "message": "Registration not found."
                },
                status=status.HTTP_404_NOT_FOUND
            )

        user = student.user

        # Protect admin accounts
        if user.is_superuser or user.is_staff:
            return Response(
                {
                    "success": False,
                    "message": "Admin accounts cannot be deleted."
                },
                status=status.HTTP_403_FORBIDDEN
            )

        # Save details before deletion
        student_name = student.name
        registration_id = student.student_no
        student_email = user.email

        try:
            with transaction.atomic():

                # Delete account.
                # Student profile and related QR/attendance
                # records will follow their model's FK rules.
                user.delete()

            return Response(
                {
                    "success": True,
                    "message": "Registration deleted successfully.",
                    "deleted_student": {
                        "name": student_name,
                        "student_no": registration_id,
                        "email": student_email
                    }
                },
                status=status.HTTP_200_OK
            )

        except ProtectedError:
            return Response(
                {
                    "success": False,
                    "message": (
                        "Cannot delete registration because "
                        "protected related records exist."
                    )
                },
                status=status.HTTP_409_CONFLICT
            )

        except Exception:
            return Response(
                {
                    "success": False,
                    "message": "An unexpected error occurred while deleting registration."
                },
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )