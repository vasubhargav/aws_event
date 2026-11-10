
from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.utils.html import escape


# ==================================================
# CLOUD CLASH OTP EMAIL SERVICE
# ==================================================

def send_otp_email(email, name, otp, purpose="registration"):

    safe_name = escape(name)
    safe_otp = escape(otp)

    subject = (
        "Verify Your Email | Cloud Clash"
        if purpose == "registration"
        else "Login Verification | Cloud Clash"
    )

    text_content = f"""
AWS BUILDER GROUP PRESENTS

CLOUD CLASH

Hello {name},

Your email verification OTP is:

{otp}

This OTP is valid for 5 minutes.

Do not share this code with anyone.

Team AWS Builder Group
"""

    html_content = f"""
<!DOCTYPE html>
<html>
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Cloud Clash OTP Verification</title>
</head>

<body style="
    margin:0;
    padding:25px 10px;
    background:#eeeeee;
    font-family:Arial,Helvetica,sans-serif;
">

<table width="100%" cellpadding="0" cellspacing="0"
style="
    max-width:600px;
    margin:auto;
    background:#202124;
    border-radius:18px;
    overflow:hidden;
">

<!-- HEADER -->

<tr>
<td align="center" style="
    background:#493807;
    padding:38px 20px;
">

<p style="
    color:#FFCC00;
    font-size:15px;
    font-weight:bold;
    letter-spacing:2px;
">
AWS BUILDER GROUP PRESENTS
</p>

<h1 style="
    color:#FFCC00;
    font-size:38px;
    margin:10px 0;
">
CLOUD CLASH
</h1>

<p style="color:white;font-size:16px;">
EMAIL VERIFICATION
</p>

</td>
</tr>

<!-- MAIN CONTENT -->

<tr>
<td style="padding:35px 25px;color:white;">

<h1 style="
    font-size:29px;
    margin:0 0 20px;
">
Verify Your Email
</h1>

<p style="
    color:#dddddd;
    font-size:17px;
    line-height:1.7;
">
Hey, {safe_name}!
</p>

<p style="
    color:#cccccc;
    font-size:16px;
    line-height:1.7;
">
You're one step away from joining Cloud Clash.
Use the verification code below to complete your
{"registration" if purpose == "registration" else "login"}.
</p>

<!-- OTP BOX -->

<table width="100%" cellpadding="0" cellspacing="0"
style="
    background:#f2f2f2;
    border-radius:16px;
    margin:30px 0;
">

<tr>
<td align="center" style="padding:30px 15px;">

<p style="
    color:#72550a;
    font-size:14px;
    font-weight:bold;
    letter-spacing:2px;
">
YOUR VERIFICATION CODE
</p>

<h1 style="
    color:#493807;
    font-size:40px;
    letter-spacing:9px;
    margin:20px 0;
">
{safe_otp}
</h1>

<p style="
    color:#444444;
    font-size:15px;
    margin:0;
">
Valid for 5 minutes
</p>

</td>
</tr>
</table>

<!-- SECURITY NOTICE -->

<table width="100%" cellpadding="0" cellspacing="0"
style="
    background:#493807;
    border-radius:12px;
">

<tr>
<td style="padding:20px;">

<h2 style="
    color:#FFCC00;
    font-size:20px;
    margin:0 0 12px;
">
IMPORTANT
</h2>

<p style="
    color:#eeeeee;
    font-size:15px;
    line-height:1.7;
    margin:0;
">
Never share your OTP with anyone.
Our team will never ask you for this code.
If you did not request this verification,
please ignore this email.
</p>

</td>
</tr>
</table>

<h2 style="
    color:white;
    margin-top:35px;
    font-size:26px;
">
LET THE CLASH BEGIN!
</h2>

<p style="color:#cccccc;font-size:16px;">
Team AWS Builder Group
</p>

</td>
</tr>

<!-- FOOTER -->

<tr>
<td align="center" style="
    background:#eeeeee;
    padding:28px 15px;
">

<h1 style="
    color:#72550a;
    font-size:27px;
    margin:0 0 10px;
">
CLOUD CLASH
</h1>

<p style="
    color:#222222;
    font-size:14px;
">
POWERED BY AWS BUILDER GROUP
</p>

<p style="
    color:#777777;
    font-size:12px;
    margin-top:20px;
">
This is an automated email. Please do not reply.
</p>

</td>
</tr>

</table>
</body>
</html>
"""

    email_message = EmailMultiAlternatives(
        subject=subject,
        body=text_content,
        from_email=settings.DEFAULT_FROM_EMAIL,
        to=[email],
    )

    email_message.attach_alternative(
        html_content,
        "text/html"
    )

    return email_message.send(fail_silently=False)


# ==================================================
# REGISTRATION OTP
# ==================================================

def send_pending_registration_otp(email, name, otp):

    return send_otp_email(
        email=email,
        name=name,
        otp=otp,
        purpose="registration"
    )


# ==================================================
# LOGIN OTP
# ==================================================

def send_student_otp(user, name, otp):

    return send_otp_email(
        email=user.email,
        name=name,
        otp=otp,
        purpose="login"
    )
