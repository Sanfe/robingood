#!/usr/bin/env python3
import os
import asyncio
import shutil
from telethon import TelegramClient
from telethon.errors import SessionPasswordNeededError, MessageIdInvalidError
from aiohttp import web
import sqlite3
import logging
from pathlib import Path
from guessit import guessit
from dotenv import load_dotenv

# Cargar variables de entorno
load_dotenv()

API_ID = os.getenv('API_ID')
API_HASH = os.getenv('API_HASH')
PHONE_NUMBER = os.getenv('PHONE_NUMBER')
PROXY_PORT = int(os.getenv('PROXY_PORT', 8080))
WAIT_TIME = int(os.getenv('WAIT_TIME', 120))
BASE_URL = os.getenv('BASE_URL', f'http://localhost:{PROXY_PORT}')
CHANNELS = {
    'Movies': {
        'id': int(os.getenv('MOVIES_CHANNEL_ID')),
        'folder': os.getenv('MOVIES_FOLDER')
    },
    'Series': {
        'id': int(os.getenv('SERIES_CHANNEL_ID')),
        'folder': os.getenv('SERIES_FOLDER')
    }
}

# Configuración de logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Conexión al cliente de Telegram
client = TelegramClient('streaming', API_ID, API_HASH)

# Conexión a la base de datos
DB_PATH = os.getenv('DB_PATH', 'processed_files.db')
conn = sqlite3.connect(DB_PATH)
cursor = conn.cursor()
cursor.execute('''CREATE TABLE IF NOT EXISTS files
                  (file_id TEXT PRIMARY KEY, channel TEXT, file_path TEXT)''')

async def authenticate():
    await client.connect()
    if not await client.is_user_authorized():
        await client.send_code_request(PHONE_NUMBER)
        code = input("Introduce el código de Telegram: ")
        try:
            await client.sign_in(PHONE_NUMBER, code)
        except SessionPasswordNeededError:
            password = input("Introduce tu contraseña de verificación en dos pasos: ")
            await client.sign_in(password=password)

async def handle_proxy_request(request):
    channel = request.match_info['channel']
    file_id = request.match_info['file_id']

    try:
        message = await client.get_messages(CHANNELS[channel]['id'], ids=int(file_id))
        if not message or not message.file:
            return web.Response(status=404, text="Archivo no encontrado en el canal.")

        response = web.StreamResponse()
        response.content_type = message.file.mime_type or 'application/octet-stream'
        response.headers['Content-Disposition'] = f'inline; filename="{message.file.name or file_id}"'

        range_header = request.headers.get('Range', None)
        if range_header:
            start_str, end_str = range_header.replace('bytes=', '').split('-')
            start = int(start_str)
            end = int(end_str) if end_str else None
            response.set_status(206)
            response.headers['Content-Range'] = f'bytes {start}-{end or message.file.size - 1}/{message.file.size}'
            await response.prepare(request)
            async for chunk in client.iter_download(message.media, offset=start, limit=end):
                await response.write(chunk)
        else:
            await response.prepare(request)
            async for chunk in client.iter_download(message.media):
                await response.write(chunk)

        await response.write_eof()
        logger.info(f"Archivo {file_id} del canal {channel} transmitido correctamente.")
        return response

    except MessageIdInvalidError:
        return web.Response(status=404, text="Archivo no encontrado en el canal.")
    except Exception as e:
        logger.error(f"Error al procesar {channel}/{file_id}: {str(e)}")
        return web.Response(status=500, text="Error interno del servidor.")

def parse_movie_info(filename_or_caption):
    guess = guessit(filename_or_caption)
    if 'title' in guess and 'year' in guess:
        return guess['title'], guess['year']
    return None, None

def parse_episode_info(filename_or_caption):
    guess = guessit(filename_or_caption)
    if 'title' in guess and 'season' in guess and 'episode' in guess:
        return guess['title'], guess['season'], guess['episode']
    return None

def capitalize_title(title):
    return ' '.join(word.capitalize() for word in title.split())

def create_movie_nfo(folder, title, year):
    nfo_path = folder / "movie.nfo"
    with nfo_path.open('w') as nfo_file:
        nfo_file.write(f"<movie>\n  <title>{title}</title>\n  <year>{year}</year>\n</movie>")
    logger.info(f"Archivo NFO creado: {nfo_path}")

def delete_empty_folders(folder):
    folder_path = Path(folder)
    while folder_path != folder_path.parent:
        try:
            # Verificar si la carpeta está vacía o solo contiene archivos .nfo
            if all(f.suffix == '.nfo' for f in folder_path.iterdir()) or not any(folder_path.iterdir()):
                for f in folder_path.iterdir():
                    f.unlink()
                folder_path.rmdir()
                logger.info(f"Carpeta {folder_path} eliminada por estar vacía o solo contener archivos .nfo.")
                folder_path = folder_path.parent
            else:
                break
        except OSError:
            break

async def process_channel(channel_name, channel_info):
    channel = await client.get_entity(channel_info['id'])
    folder_path = Path(channel_info['folder'])
    folder_path.mkdir(parents=True, exist_ok=True)

    # Verificar archivos en la base de datos
    cursor.execute("SELECT file_id, file_path FROM files WHERE channel=?", (channel_name,))
    processed_files = cursor.fetchall()

    for file_id, file_path in processed_files:
        try:
            message = await client.get_messages(channel, ids=int(file_id))
            if not message:
                logger.info(f"Mensaje {file_id} no encontrado en el canal {channel_name}. Eliminando archivos asociados.")
                raise MessageIdInvalidError(request=None)
        except MessageIdInvalidError:
            cursor.execute("DELETE FROM files WHERE file_id=? AND channel=?", (file_id, channel_name))
            conn.commit()
            if os.path.exists(file_path):
                os.remove(file_path)
                logger.info(f"Archivo {file_path} eliminado por no existir en el canal.")
                # Eliminar carpeta si está vacía
                delete_empty_folders(Path(file_path).parent)

    # Procesar mensajes nuevos
    async for message in client.iter_messages(channel):
        if message.file and message.file.mime_type.startswith('video/'):
            file_id = str(message.id)

            # Verificar si el archivo ya existe en la base de datos
            cursor.execute("SELECT file_id FROM files WHERE file_id=? AND channel=?", (file_id, channel_name))
            if cursor.fetchone():
                logger.info(f"Archivo {file_id} del canal {channel_name} ya procesado. Saltando.")
                continue

            filename = message.file.name or f"video_{file_id}.mp4"
            if channel_name == 'Movies':
                title, year = parse_movie_info(filename)
                if not title or not year:
                    # Intentar extraer información del caption del mensaje si el nombre del archivo no es válido
                    if message.message:
                        title, year = parse_movie_info(message.message)
                    if not title or not year:
                        logger.warning(f"No se pudo extraer información para la película: {filename}")
                        continue
                title = capitalize_title(title)
                proper_folder = folder_path / f"{title} ({year})"
                proper_folder.mkdir(parents=True, exist_ok=True)
                clean_file_name = f"{title} ({year}){Path(filename).suffix}"
                create_movie_nfo(proper_folder, title, year)
            elif channel_name == 'Series':
                episode_info = parse_episode_info(filename)
                if not episode_info:
                    # Intentar extraer información del caption del mensaje si el nombre del archivo no es válido
                    if message.message:
                        episode_info = parse_episode_info(message.message)
                    if not episode_info:
                        logger.warning(f"No se pudo extraer información para el episodio: {filename}")
                        continue
                title, season, episode = episode_info
                title = capitalize_title(title)
                proper_folder = folder_path / title / f"Season {season}"
                proper_folder.mkdir(parents=True, exist_ok=True)
                clean_file_name = f"{title} - S{season:02}E{episode:02}{Path(filename).suffix}"

            strm_path = proper_folder / f"{clean_file_name}.strm"
            with strm_path.open('w') as strm_file:
                strm_file.write(f"{BASE_URL}/{channel_name}/{file_id}")

            try:
                cursor.execute("INSERT INTO files (file_id, channel, file_path) VALUES (?, ?, ?)", (file_id, channel_name, str(strm_path)))
                conn.commit()
            except sqlite3.IntegrityError:
                logger.warning(f"Archivo {file_id} del canal {channel_name} ya existe en la base de datos.")

            logger.info(f"Archivo STRM creado: {strm_path}")

async def main():
    await authenticate()

    app = web.Application()
    app.router.add_get('/{channel}/{file_id}', handle_proxy_request)

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, 'localhost', PROXY_PORT)
    await site.start()

    logger.info("Servidor HTTP de streaming iniciado.")

    while True:
        for channel_name, channel_info in CHANNELS.items():
            await process_channel(channel_name, channel_info)
        await asyncio.sleep(WAIT_TIME)

if __name__ == '__main__':
    asyncio.run(main())
