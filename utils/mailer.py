import logging
import os
from datetime import datetime
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from config import LOGS_FOLDER

logging.basicConfig(
    filename=os.path.join(LOGS_FOLDER, "email_logs.log"),
    level=logging.INFO,
    format="%(asctime)s:%(levelname)s:%(message)s",
)
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


def send_email(
    to_email, subject, body, is_html=False, template_name=None, template_data=None
):
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
            logging.info(f"Sending HTML template email to: {to_email}")
            logging.info(f"Subject: {subject}")
            logging.info(f"Template: {template_name}")
        else:
            content_type = "html" if is_html else "plain"
            msg.attach(MIMEText(body, content_type))
            logging.info(f"Sending email to: {to_email}")
            logging.info(f"Subject: {subject}")
        try:
            with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
                server.login(sender_email, password)
                server.send_message(msg)
                logging.info(f"Email sent successfully to {to_email} via SSL")
                return True
        except Exception as ssl_error:
            logging.warning(f"SSL connection failed: {str(ssl_error)}, trying TLS...")
            try:
                with smtplib.SMTP("smtp.gmail.com", 587) as server:
                    server.ehlo()
                    server.starttls()
                    server.ehlo()
                    server.login(sender_email, password)
                    server.send_message(msg)
                    logging.info(f"Email sent successfully to {to_email} via TLS")
                    return True
            except Exception as tls_error:
                logging.error(f"TLS connection also failed: {str(tls_error)}")
                raise tls_error

    except Exception as e:
        logging.error(f"Failed to send email: {str(e)}")
        save_email_to_file(
            to_email, subject, body, is_html, template_name, template_data
        )
        return False


def save_email_to_file(
    to_email, subject, body, is_html=False, template_name=None, template_data=None
):
    """
    Сохраняет содержимое письма в файл для отладки и резервного хранения
    """
    try:
        with open("sent_emails.log", "a", encoding="utf-8") as f:
            f.write(f"\n\n--- NEW EMAIL [{datetime.now()}] ---\n")
            f.write(f"To: {to_email}\n")
            f.write(f"Subject: {subject}\n")
            if template_name and template_name in EMAIL_TEMPLATES:
                if not template_data:
                    template_data = {}
                template_data["year"] = datetime.now().year
                template_data["timestamp"] = datetime.now().strftime(
                    "%d.%m.%Y %H:%M:%S"
                )
                content = EMAIL_TEMPLATES[template_name].format(**template_data)
                f.write(f"Content: [HTML Template {template_name}]\n")
            else:
                content = body
                f.write(f"Content: {'[HTML]' if is_html else '[Plain text]'}\n")

            f.write(f"{content}\n")
            f.write(f"--- END EMAIL ---\n")

        print(f"[EMAIL SAVED] Email to {to_email} saved to sent_emails.log")
        return True
    except Exception as e:
        print(f"[ERROR SAVING EMAIL] {str(e)}")
        return False
def test_email_sending():
    """
    Тестовая функция для проверки отправки почты
    """
    recipient = "pashasob2009@gmail.com"  # Замените на реальный адрес
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
        print(f"Тестовое письмо успешно отправлено на {recipient}")
    else:
        print(f"Не удалось отправить тестовое письмо, проверьте sent_emails.log")

    return result
if __name__ == "__main__":
    test_email_sending()
