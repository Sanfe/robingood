
# Robingood


What make the difference?

- Use Telethon to monitor 2 channels (Movies and Series) each 1 min
- If you download 7z , zip or rar in a joined message, it extract for you
- for let your gallery ready to use in Kodi or other media center, it execute tiny Media Manager (TMM), You have to configure TMM in gui first, adding the paths and your setup.
- If you send a joined message, it questions you about a name folder, useful for TV shows, TMM needs a folder manually to make their work with TV Shows.

# Robingood_streaming

- Suitable for files max 4 gb allowed by telegram, it allows to streaming video message or video files in one part (no seeking avaliable yet, only play)
- It creates a web internal proxy in localhost, linked with a sqlite database that monitor the path of files.
- If you delete the file in the chat, it would be delete in the system.


How to configure?

- Go to https://my.telegram.org/auth for discover your API_ID and API_HASH
- Fill this configuration variables in top of the example  .env file. rename to .env
- pip install -r requirements.txt

# Variables comunes a ambos scripts
- API_ID=''  # Reemplaza con tu API ID de Telegram
- API_HASH=''  # Reemplaza con tu API Hash de Telegram
- PHONE_NUMBER=''  # Reemplaza con tu número de teléfono
- DOWNLOAD_SESSION_FILE='download'  # Nombre del archivo de sesión de Telegram
- STREAMING_SESSION_FILE='streaming'
- WAIT_TIME=60  # Tiempo de espera en segundos

# Variables específicas para robingood.py
- MOVIES_DOWNLOAD_CHANNEL_ID=''
- SERIES_DOWNLOAD_CHANNEL_ID='-'
- CONTROL_DOWNLOAD_CHANNEL_ID=''
- MOVIES_DOWNLOAD_TEMP_FOLDER=''
- SERIES_DOWNLOAD_TEMP_FOLDER=''
- MOVIES_DOWNLOAD_FOLDER=''
- SERIES_DOWNLOAD_FOLDER=''
 
- USE_TMM=True  # Usar TinyMediaManager (True/False)
- STATE_FILE=download_state.json  # Archivo para guardar el estado de las descargas

# Variables específicas para robingood_streaming.py
- PROXY_PORT=8080  # Puerto para el servidor de streaming
- MOVIES_CHANNEL_ID= # ID del canal de películas
- SERIES_CHANNEL_ID= # ID del canal de series
- MOVIES_FOLDER=  # Carpeta para películas
- SERIES_FOLDER=  # Carpeta para series
- DB_PATH=streaming_index.db  # Ruta de la base de datos para archivos procesados
- VALIDATE_DUPLICATES=true

# configurable language messages inside robingood.py

- MESSAGE_PROMPT_FOLDER = "Se detectó un grupo con ID `{grouped_id}`. ¿Quieres guardar los archivos en una carpeta nueva? Responde con `Y` o `N`."
- MESSAGE_ENTER_FOLDER_NAME = "Por favor, introduce el nombre de la carpeta:"
- MESSAGE_TIMEOUT_FOLDER = "No se recibió respuesta. Procediendo con la descarga y extracción."
- MESSAGE_FOLDER_CREATED = "Carpeta `{folder_name}` creada exitosamente."
- MESSAGE_PROCESS_COMPLETE = "Archivos del grupo `{grouped_id}` procesados y guardados en `{folder_path}`."
- MESSAGE_NO_FILES_FOUND = "No se encontraron archivos en el grupo."


# TODO

- robingood_streaming needs some improvement with guessit and some strange file names.
- Replace TMM in robingood.py with guessit.
- Windows .exe precompiled, too much round for deploy all the dependencies in python. 

