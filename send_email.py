#!/usr/bin/env python3
"""
发送HTML美化邮件（SMTP直发，不依赖平台公邮）
"""
import smtplib, ssl, argparse
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.header import Header
import datetime

SMTP_USER = '704901171@qq.com'
SMTP_PASS = 'yoyqmwluklabbcic'
SMTP_HOST = 'smtp.qq.com'
SMTP_PORT = 465

def send(subject, html_content, plain_text=''):
    msg = MIMEMultipart('alternative')
    msg['Subject'] = Header(subject, 'utf-8')
    msg['From'] = SMTP_USER
    msg['To'] = SMTP_USER
    if plain_text:
        msg.attach(MIMEText(plain_text, 'plain', 'utf-8'))
    msg.attach(MIMEText(html_content, 'html', 'utf-8'))
    context = ssl.create_default_context()
    with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, context=context) as server:
        server.login(SMTP_USER, SMTP_PASS)
        server.sendmail(SMTP_USER, [SMTP_USER], msg.as_string())
    print(f"✅ 发送成功: {subject}")

if __name__ == '__main__':
    import sys
    subject = sys.argv[1] if len(sys.argv) > 1 else 'Stock Report'
    html_file = sys.argv[2] if len(sys.argv) > 2 else 'report.html'
    with open(html_file, 'r', encoding='utf-8') as f:
        html = f.read()
    send(subject, html)
