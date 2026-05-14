import sqlite3
import hashlib
import requests
from datetime import datetime, timedelta
from bs4 import BeautifulSoup
from dotenv import load_dotenv
import logging
import os
import sys

from telegram_client import TelegramClient

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger(__name__)

# --- CONFIGURACIÓN ---

USERNAME = os.getenv("ETIG_USERNAME")
PASSWORD = os.getenv("ETIG_PASSWORD")
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
DB_PATH = "data/notificaciones.db"
TELEGRAM_CLIENT = TelegramClient(TOKEN, CHAT_ID, log)


def scraping_unlz():
    LOGIN_URL = "https://etig.ingenieria.unlz.edu.ar/index.php?r=site%2Flogin"
    session = requests.Session()
    response = session.get(LOGIN_URL)
    soup = BeautifulSoup(response.text, 'html.parser')
    csrf_token = soup.find('meta', attrs={'name': 'csrf-token'})['content']
    response = session.post(LOGIN_URL, data={"_csrf-frontend": csrf_token,
                                 "LoginForm[userType]": "familiar",
                                 "LoginForm[username]": USERNAME,
                                 "LoginForm[password]": PASSWORD,
                                 "LoginForm[rememberMe]": "1"})
    URL_NOTIFICATIONS = "https://etig.ingenieria.unlz.edu.ar/index.php?r=notificaciones%2Fmisnotificaciones"
    return session.get(URL_NOTIFICATIONS).text


def enviar_telegram(notificacion):
    # Formateamos el mensaje con Markdown
    texto = (
        f"🔔 *ETIG*\n\n"
        f"*Título:* {notificacion['titulo']}\n"
        f"*De:* {notificacion['emisor']}\n"
        f"*Fecha:* {notificacion['fecha']}\n\n"
        f"{notificacion['contenido']}"
    )
    message_id = TELEGRAM_CLIENT.send_text(texto, parse_mode="Markdown")
    if message_id is None:
        log.error("Error enviando a Telegram desde ETIG")

def procesar_y_notificar(html_content):
    # Inicializar DB y limpiar registros > 4 días
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute(
        'CREATE TABLE IF NOT EXISTS notificaciones '
        '(id TEXT PRIMARY KEY, fecha_registro DATE)'
    )
    limite_db = (datetime.now() - timedelta(days=5)).date()
    cursor.execute(
        "DELETE FROM notificaciones WHERE fecha_registro < ?",
        (limite_db.isoformat(),)
        )
    # Parseo
    soup = BeautifulSoup(html_content, 'html.parser')
    paneles = soup.find_all('div', class_='panel-info')
    hoy = datetime.now()
    limite_busqueda = hoy - timedelta(days=4)
    for panel in paneles:
        titulo = panel.find('div', class_='panel-heading').get_text(strip=True)
        ps = panel.find('div', class_='panel-body').find_all('p', recursive=False)
        fecha_str = ps[1].get_text(strip=True).replace('Fecha:', '').strip()
        contenido = ps[2].get_text(strip=True)
        try:
            fecha_dt = datetime.strptime(fecha_str, "%d-%m-%Y")
        except ValueError:
            continue

        # Filtro de 4 días
        if fecha_dt < limite_busqueda:
            continue

        # Generar hash y verificar unicidad
        seed = f"{fecha_str}|{titulo.lower()}|{contenido[:50]}"
        n_id = hashlib.sha256(seed.encode()).hexdigest()
        cursor.execute("SELECT 1 FROM notificaciones WHERE id = ?", (n_id,))
        if cursor.fetchone() is None:
            # Es nueva: Guardar y Enviar
            notif_data = {
                "titulo": titulo,
                "emisor": ps[0].get_text(strip=True).replace('De:', '').strip(),
                "fecha": fecha_str,
                "contenido": contenido
            }
            enviar_telegram(notif_data)
            cursor.execute(
                "INSERT INTO notificaciones VALUES (?, ?)",
                (n_id, hoy.date().isoformat())
            )
            conn.commit()

    conn.close()


if __name__ == "__main__":
    try:
        # Aquí iría tu lógica de login y obtención del HTML
        html = scraping_unlz() 
        procesar_y_notificar(html)
        log.info("Check finalizado: %s", datetime.now())
    except Exception as e:
        log.error("Error en el loop: %s", e, exc_info=True)
    
