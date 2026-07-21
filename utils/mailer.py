import logging
import math
import os
import smtplib
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

logger = logging.getLogger("remind.mailer")
_DEFAULT_SMTP_TIMEOUT_SECONDS = 10.0
_MIN_SMTP_TIMEOUT_SECONDS = 1.0
_MAX_SMTP_TIMEOUT_SECONDS = 60.0


def _smtp_timeout_seconds() -> float:
    """Return a finite SMTP socket timeout constrained to a safe range."""
    raw_timeout = os.getenv("SMTP_TIMEOUT_SECONDS", str(_DEFAULT_SMTP_TIMEOUT_SECONDS))
    try:
        timeout = float(raw_timeout)
    except (TypeError, ValueError):
        return _DEFAULT_SMTP_TIMEOUT_SECONDS
    if not math.isfinite(timeout):
        return _DEFAULT_SMTP_TIMEOUT_SECONDS
    return max(_MIN_SMTP_TIMEOUT_SECONDS, min(timeout, _MAX_SMTP_TIMEOUT_SECONDS))


EMAIL_TEMPLATES = {
    "confirmation": """
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="utf-8">
    </head>
    <body style="font-family: Arial, sans-serif; line-height: 1.6; color: #333; max-width: 600px; margin: 0 auto;">
        <div style="background-color: #4361ee; color: white; padding: 20px; text-align: center; border-radius: 5px 5px 0 0;">
            <h2>Подтверждение вашего email</h2>
        </div>
        <div style="padding: 20px; background-color: #f9f9f9; border: 1px solid #ddd;">
            <p>Здравствуйте, <strong>{username}</strong>!</p>
            <p>Благодарим за регистрацию. Пожалуйста, подтвердите ваш email, нажав на кнопку ниже:</p>
            <p style="text-align: center;">
                <a href="{confirmation_link}" style="display: inline-block; background-color: #4361ee; color: white; padding: 10px 20px; text-decoration: none; border-radius: 5px;">Подтвердить Email</a>
            </p>
            <p>Или перейдите по ссылке: <a href="{confirmation_link}">{confirmation_link}</a></p>
            <p>Если вы не регистрировались на нашем сайте, пожалуйста, проигнорируйте это письмо.</p>
        </div>
        <div style="margin-top: 20px; font-size: 12px; color: #777; text-align: center;">
            <p>&copy; {year} ReMind. Все права защищены.</p>
        </div>
    </body>
    </html>
    """,
    "reset_password": """
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="utf-8">
    </head>
    <body style="font-family: Arial, sans-serif; line-height: 1.6; color: #333; max-width: 600px; margin: 0 auto;">
        <div style="background-color: #4361ee; color: white; padding: 20px; text-align: center; border-radius: 5px 5px 0 0;">
            <h2>Сброс пароля</h2>
        </div>
        <div style="padding: 20px; background-color: #f9f9f9; border: 1px solid #ddd;">
            <p>Здравствуйте, <strong>{username}</strong>!</p>
            <p>Мы получили запрос на сброс вашего пароля. Пожалуйста, нажмите на кнопку ниже для создания нового пароля:</p>
            <p style="text-align: center;">
                <a href="{reset_link}" style="display: inline-block; background-color: #4361ee; color: white; padding: 10px 20px; text-decoration: none; border-radius: 5px;">Сбросить пароль</a>
            </p>
            <p>Или перейдите по ссылке: <a href="{reset_link}">{reset_link}</a></p>
            <p style="color: #e74c3c; font-weight: bold;">Если вы не запрашивали сброс пароля, пожалуйста, проигнорируйте это письмо и свяжитесь с поддержкой.</p>
        </div>
        <div style="margin-top: 20px; font-size: 12px; color: #777; text-align: center;">
            <p>&copy; {year} ReMind. Все права защищены.</p>
        </div>
    </body>
    </html>
    """,
    "password_changed": """
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="utf-8">
    </head>
    <body style="font-family: Arial, sans-serif; line-height: 1.6; color: #333; max-width: 600px; margin: 0 auto;">
        <div style="background-color: #4361ee; color: white; padding: 20px; text-align: center; border-radius: 5px 5px 0 0;">
            <h2>Пароль успешно изменен</h2>
        </div>
        <div style="padding: 20px; background-color: #f9f9f9; border: 1px solid #ddd;">
            <p>Здравствуйте, <strong>{username}</strong>!</p>
            <p style="color: #27ae60; font-weight: bold;">Ваш пароль был успешно изменен.</p>
            <p>Если вы не делали этого изменения, пожалуйста, немедленно:</p>
            <ol>
                <li>Попробуйте войти в свой аккаунт</li>
                <li>Сбросьте пароль снова</li>
                <li>Свяжитесь с нашей службой поддержки</li>
            </ol>
            <p style="color: #e74c3c;">Безопасность вашего аккаунта очень важна для нас.</p>
        </div>
        <div style="margin-top: 20px; font-size: 12px; color: #777; text-align: center;">
            <p>&copy; {year} ReMind. Все права защищены.</p>
            <p>Время отправки: {timestamp}</p>
        </div>
    </body>
    </html>
    """,
}


def send_email(to_email, subject, body, is_html=False, template_name=None, template_data=None):
    """
    Send an email using Gmail SMTP with direct credentials

    Args:
        to_email (str): Recipient email address
        subject (str): Email subject
        body (str): Email body content (used if template_name is None)
        is_html (bool): Whether the body is HTML
        template_name (str): Name of the template to use
        template_data (dict): Data to fill in the template

    Returns:
        bool: True if successful, False otherwise
    """
    try:
        sender_email = os.getenv("EMAIL_SENDER")
        password = os.getenv("EMAIL_PASSWORD")
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = sender_email
        msg["To"] = to_email
        if template_name and template_name in EMAIL_TEMPLATES:
            if not template_data:
                template_data = {}
            template_data["year"] = datetime.now().year
            template_data["timestamp"] = datetime.now().strftime("%d.%m.%Y %H:%M:%S")

            html_content = EMAIL_TEMPLATES[template_name].format(**template_data)
            msg.attach(MIMEText(html_content, "html"))
            logger.info(
                "Sending HTML template email: recipient=[REDACTED] template=%s",
                template_name,
            )
        else:
            content_type = "html" if is_html else "plain"
            msg.attach(MIMEText(body, content_type))
            logger.info("Sending email: recipient=[REDACTED]")
        smtp_timeout = _smtp_timeout_seconds()
        try:
            with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=smtp_timeout) as server:
                server.login(sender_email, password)
                server.send_message(msg)
                logger.info("Email sent successfully via SSL: recipient=[REDACTED]")
                return True
        except Exception as ssl_error:
            logger.warning("SSL email connection failed (%s), trying TLS", type(ssl_error).__name__)
            try:
                with smtplib.SMTP("smtp.gmail.com", 587, timeout=smtp_timeout) as server:
                    server.ehlo()
                    server.starttls()
                    server.ehlo()
                    server.login(sender_email, password)
                    server.send_message(msg)
                    logger.info("Email sent successfully via TLS: recipient=[REDACTED]")
                    return True
            except Exception as tls_error:
                logger.error("TLS email connection failed (%s)", type(tls_error).__name__)
                raise tls_error

    except Exception as e:
        logger.error("Failed to send email (%s)", type(e).__name__)
        save_email_to_file(to_email, subject, body, is_html, template_name, template_data)
        return False


def save_email_to_file(
    to_email, subject, body, is_html=False, template_name=None, template_data=None
):
    """
    Сохраняет только безопасные метаданные ошибки доставки без тела письма и токенов.
    """
    try:
        logger.warning(
            "Email delivery failed; recipient and content omitted (template=%s)",
            template_name or "custom",
        )
        return True
    except Exception as e:
        logger.error("Could not record failed email metadata (%s)", type(e).__name__)
        return False


def test_email_sending():
    """
    Тестовая функция для проверки отправки почты
    """
    recipient = os.getenv("TEST_EMAIL_RECIPIENT")
    if not recipient:
        print("TEST_EMAIL_RECIPIENT is not configured")
        return False
    subject = "Тестовое письмо от ReMind"

    template_data = {
        "username": "Тестовый Пользователь",
        "confirmation_link": "https://example.com/confirm/test-token",
    }

    result = send_email(
        to_email=recipient,
        subject=subject,
        body="",
        template_name="confirmation",
        template_data=template_data,
    )

    if result:
        print("Тестовое письмо успешно отправлено")
    else:
        print("Не удалось отправить тестовое письмо, проверьте failed_email_metadata.log")

    return result


if __name__ == "__main__":
    test_email_sending()
