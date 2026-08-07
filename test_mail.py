# test_email_django.py
import os
import django

# Set up Django environment
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'pharma.settings')
django.setup()

from django.core.mail import send_mail
from django.conf import settings

def send_test_email():
    """Send a test email using Django's email system"""
    
    recipient = 'opioarnoldoku@gmail.com'
    
    print("=" * 60)
    print("📧 TESTING DJANGO EMAIL")
    print("=" * 60)
    print(f"From: {settings.DEFAULT_FROM_EMAIL}")
    print(f"To: {recipient}")
    print(f"Host: {settings.EMAIL_HOST}:{settings.EMAIL_PORT}")
    print(f"User: {settings.EMAIL_HOST_USER}")
    print(f"Password: {'*' * len(settings.EMAIL_HOST_PASSWORD) if settings.EMAIL_HOST_PASSWORD else 'NOT SET'}")
    print("=" * 60)
    
    try:
        send_mail(
            subject='Test Email from PharmaPro',
            message='This is a test email sent from your Django application.\n\nIf you received this, your email configuration is working correctly!',
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[recipient],
            fail_silently=False,
        )
        print("\n✅ Email sent successfully!")
        print(f"📬 Check {recipient} inbox in a few moments.")
        return True
        
    except Exception as e:
        print(f"\n❌ Error sending email: {e}")
        print(f"Error type: {type(e).__name__}")
        return False

if __name__ == '__main__':
    send_test_email()