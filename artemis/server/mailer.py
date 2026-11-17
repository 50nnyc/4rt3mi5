"""0.21.0: envio do e-mail da tela "Contato com o administrador".

Configuração só no .env do servidor (nada disso vai para o repositório):
  ARTEMIS_SMTP_USER       conta que envia (ex.: o Gmail do administrador)
  ARTEMIS_SMTP_PASSWORD   senha de app dessa conta (Google → Segurança → Senhas de app)
  ARTEMIS_CONTACT_INBOX   para onde vai a mensagem (padrão: a própria conta que envia)
  ARTEMIS_SMTP_HOST / ARTEMIS_SMTP_PORT   padrão smtp.gmail.com / 587 (STARTTLS)
Sem usuário e senha, a mensagem fica só no painel admin.
"""
from __future__ import annotations

import os
import smtplib
import ssl
from email.message import EmailMessage
from email.utils import formatdate, make_msgid

SUBJECT_TAG = "[4rt3mi5] Contato"


def configured() -> bool:
    return bool(os.environ.get("ARTEMIS_SMTP_USER") and os.environ.get("ARTEMIS_SMTP_PASSWORD"))


def build(sender: str, inbox: str, visitor: str, subject: str, message: str, lang: str, when: str) -> EmailMessage:
    msg = EmailMessage()
    msg["From"] = f"4rt3mi5 <{sender}>"
    msg["To"] = inbox
    msg["Reply-To"] = visitor            # "Responder" no Gmail vai direto para quem escreveu
    msg["Subject"] = f"{SUBJECT_TAG}: {subject}" if subject else SUBJECT_TAG
    msg["Date"] = formatdate(localtime=False)
    msg["Message-ID"] = make_msgid(domain=sender.rsplit("@", 1)[-1] or "localhost")
    msg.set_content(f"De: {visitor}\nIdioma da tela: {lang}\nEnviado em: {when} (UTC)\n\n{message}\n\n"
                    "-- \nMensagem enviada pela tela \"Contato com o administrador\" do 4rt3mi5. "
                    "Responder este e-mail responde para quem escreveu.\n")
    return msg


def send(visitor: str, subject: str, message: str, lang: str, when: str) -> bool:
    """Entrega ao servidor de e-mail. Devolve False (sem levantar erro) se não estiver configurado ou falhar."""
    if not configured():
        return False
    user, password = os.environ["ARTEMIS_SMTP_USER"], os.environ["ARTEMIS_SMTP_PASSWORD"]
    inbox = os.environ.get("ARTEMIS_CONTACT_INBOX") or user
    host = os.environ.get("ARTEMIS_SMTP_HOST", "smtp.gmail.com")
    port = int(os.environ.get("ARTEMIS_SMTP_PORT", "587"))
    try:
        with smtplib.SMTP(host, port, timeout=20) as smtp:
            smtp.starttls(context=ssl.create_default_context())
            smtp.login(user, password)
            smtp.send_message(build(user, inbox, visitor, subject, message, lang, when))
        return True
    except (OSError, smtplib.SMTPException) as e:
        print("Contato: não consegui enviar o e-mail:", type(e).__name__)  # sem detalhes (podem ter dados da conta)
        return False
