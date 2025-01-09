import os
import re
import asyncio
from telethon import TelegramClient, events
from telethon.errors import SessionPasswordNeededError, MessageIdInvalidError, ChatWriteForbiddenError, FloodWaitError
from aiohttp import web
import sqlite3
import logging
from pathlib import Path
from guessit import guessit
from dotenv import load_dotenv

# Obtiene la ruta actual (donde está el .exe o donde se ejecuta el script)
current_dir = os.getcwd()

# Carga el archivo .env desde la misma carpeta
dotenv_path = os.path.join(current_dir, ".env")
load_dotenv(dotenv_path)

# Cargar variables de entorno
API_ID = os.getenv('API_ID')
API_HASH = os.getenv('API_HASH')
PHONE_NUMBER = os.getenv('PHONE_NUMBER')
PROXY_PORT = int(os.getenv('PROXY_PORT', 8080))
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
                  (file_id TEXT PRIMARY KEY, channel TEXT, file_path TEXT, status TEXT)''')

async def authenticate():
    while True:
        try:
            await client.connect()
            if not await client.is_user_authorized():
                await client.send_code_request(PHONE_NUMBER)
                code = input("Introduce el código de Telegram: ")
                try:
                    await client.sign_in(PHONE_NUMBER, code)
                except SessionPasswordNeededError:
                    password = input("Introduce tu contraseña de verificación en dos pasos: ")
                    await client.sign_in(password=password)
            logger.info("Autenticación exitosa.")
            break
        except (ConnectionError, OSError):
            logger.warning("Error de conexión. Reintentando en 5 segundos...")
            await asyncio.sleep(5)

async def handle_proxy_request(request):
    channel = request.match_info['channel']
    file_id = request.match_info['file_id']

    try:
        message = await client.get_messages(CHANNELS[channel]['id'], ids=int(file_id))
        if not message or not message.file:
            return web.Response(status=404, text="Archivo no encontrado en el canal.")

        # Obtener el tamaño del archivo
        file_size = message.file.size

        # Determinar el rango solicitado
        range_header = request.headers.get('Range', None)
        if range_header:
            range_match = re.match(r'bytes=(\d+)-(\d+)?', range_header)
            if range_match:
                start = int(range_match.group(1))
                end = int(range_match.group(2)) if range_match.group(2) else file_size - 1
            else:
                return web.Response(status=400, text="Invalid Range header")
        else:
            start = 0
            end = file_size - 1

        # Asegurarse de que los límites estén dentro del tamaño del archivo
        start = max(0, min(start, file_size - 1))
        end = max(0, min(end, file_size - 1))

        # Configurar la respuesta con el rango adecuado
        response = web.StreamResponse(
            status=206 if range_header else 200,
            headers={
                'Content-Type': message.file.mime_type or 'application/octet-stream',
                'Content-Range': f'bytes {start}-{end}/{file_size}',
                'Content-Length': str(end - start + 1),
                'Accept-Ranges': 'bytes',
            }
        )
        await response.prepare(request)

        # Descargar el archivo en partes y enviarlas
        byte_count = 0
        async for chunk in client.iter_download(message.media, offset=start):
            chunk_length = len(chunk)
            if byte_count + chunk_length > end - start + 1:
                chunk = chunk[:end - start + 1 - byte_count]
            await response.write(chunk)
            byte_count += chunk_length
            if byte_count >= end - start + 1:
                break

        await response.write_eof()
        logger.info(f"Archivo {file_id} del canal {channel} transmitido correctamente.")
        return response

    except MessageIdInvalidError:
        return web.Response(status=404, text="Archivo no encontrado en el canal.")
    except Exception as e:
        logger.error(f"Error al procesar {channel}/{file_id}: {str(e)}")
        return web.Response(status=500, text="Error interno del servidor.")

def parse_episode_info(filename_or_caption):
    """
    Parses episode information using guessit from filename or caption.
    """
    guess = guessit(filename_or_caption)
    if 'title' in guess and 'season' in guess and 'episode' in guess:
        return guess['title'], guess['season'], guess['episode']
    return None

def capitalize_title(title):
    """
    Capitalizes the first letter of each word in the title.
    """
    return ' '.join(word.capitalize() for word in title.split())

def create_tvshow_nfo(tvshow_folder, title):
    """
    Creates a tvshow.nfo file in the specified folder with the given title.
    """
    nfo_path = tvshow_folder / 'tvshow.nfo'
    if not nfo_path.exists():
        with nfo_path.open('w') as nfo_file:
            nfo_file.write(f"<tvshow>\n  <title>{title}</title>\n</tvshow>\n")
        logger.info(f"Archivo tvshow.nfo creado: {nfo_path}")

async def wait_for_response(client, chat_id, timeout=60):
    loop = asyncio.get_event_loop()
    future_response = loop.create_future()

    async def response_handler(event):
        if event.chat_id == chat_id and not future_response.done():
            future_response.set_result(event)

    client.add_event_handler(response_handler, events.NewMessage(chats=chat_id))

    try:
        return await asyncio.wait_for(future_response, timeout=timeout)
    except asyncio.TimeoutError:
        return None
    finally:
        client.remove_event_handler(response_handler)

async def ask_for_episode_info(channel, file_id, filename_or_caption):
    try:
        await client.send_message(channel, f"No se pudo determinar la información del episodio para el archivo `{filename_or_caption}`. Por favor, proporciona el nombre de la serie, la temporada y el episodio en el formato: `NombreSerie S01E01`.")
    except ChatWriteForbiddenError:
        logger.error("No se puede escribir en este chat. Verifica los permisos del bot.")
        return

    response = await wait_for_response(client, channel, timeout=60)
    if response:
        episode_info = parse_episode_info(response.message.message)
        if episode_info:
            return episode_info
        else:
            await client.send_message(channel, "No se pudo parsear la información proporcionada. Por favor, inténtalo de nuevo.")
    else:
        logger.warning("No se recibió respuesta del usuario.")
    return None

async def process_channel(channel_name, channel_info):
    channel = await client.get_entity(channel_info['id'])
    folder_path = Path(channel_info['folder'])
    folder_path.mkdir(parents=True, exist_ok=True)

    async for message in client.iter_messages(channel):
        if message.file and message.file.mime_type.startswith('video/'):
            file_id = str(message.id)

            cursor.execute("SELECT file_id FROM files WHERE file_id=? AND channel=?", (file_id, channel_name))
            if cursor.fetchone():
                logger.info(f"Archivo {file_id} del canal {channel_name} ya procesado. Saltando.")
                continue

            filename = message.file.name or f"video_{file_id}.mp4"
            caption = message.message if message.message else filename

            episode_info = parse_episode_info(caption)

            if not episode_info:
                episode_info = await ask_for_episode_info(channel_name, file_id, caption)
                if not episode_info:
                    continue

            title, season, episode = episode_info
            title = capitalize_title(title)  # Capitalizar el título correctamente

            proper_folder = folder_path / title / f"Season {season}"
            proper_folder.mkdir(parents=True, exist_ok=True)
            clean_file_name = f"{title} - S{season:02}E{episode:02}.mp4"

            strm_path = proper_folder / f"{clean_file_name}.strm"
            with strm_path.open('w') as strm_file:
                strm_file.write(f"http://localhost:{PROXY_PORT}/{channel_name}/{file_id}")

            cursor.execute("INSERT INTO files (file_id, channel, file_path, status) VALUES (?, ?, ?, 'processed')", 
                           (file_id, channel_name, str(strm_path)))
            conn.commit()

            logger.info(f"Archivo STRM creado: {strm_path}")

            # Crear el archivo tvshow.nfo si no existe
            create_tvshow_nfo(folder_path / title, title)

async def verify_files(channel_name, channel_info):
    channel = await client.get_entity(channel_info['id'])

    cursor.execute("SELECT file_id, file_path FROM files WHERE channel=?", (channel_name,))
    processed_files = cursor.fetchall()

    for file_id, file_path in processed_files:
        try:
            await client.get_messages(channel, ids=int(file_id))
        except MessageIdInvalidError:
            cursor.execute("DELETE FROM files WHERE file_id=? AND channel=?", (file_id, channel_name))
            conn.commit()
            if os.path.exists(file_path):
                os.remove(file_path)
                logger.info(f"Archivo {file_path} eliminado por no existir en el canal.")

async def handle_verify_request(request):
    channel = request.match_info['channel']
    if channel in CHANNELS:
        await verify_files(channel, CHANNELS[channel])
        return web.Response(status=200, text="Verificación completada.")
    else:
        return web.Response(status=404, text="Canal no encontrado.")

async def main():
    await authenticate()

    app = web.Application()
    app.router.add_get('/{channel}/{file_id}', handle_proxy_request)
    app.router.add_get('/verify/{channel}', handle_verify_request)

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, 'localhost', PROXY_PORT)
    await site.start()

    logger.info("Servidor HTTP de streaming iniciado.")

    while True:
        try:
            # Procesar canales en paralelo
            tasks = [process_channel(channel_name, channel_info) for channel_name, channel_info in CHANNELS.items()]
            await asyncio.gather(*tasks)

            # Esperar antes de verificar nuevamente
            await asyncio.sleep(3600)
        except (ConnectionError, OSError):
            logger.warning("Perdida de conexión. Intentando reconectar en 5 segundos...")
            await asyncio.sleep(5)
            await authenticate()

if __name__ == '__main__':
    asyncio.run(main())
