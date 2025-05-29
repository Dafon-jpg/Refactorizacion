import os
import csv
import re
import io
from datetime import datetime
from PyPDF2 import PdfReader
from pdf2image import convert_from_bytes
import pytesseract
from PIL import Image
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.http import MediaIoBaseDownload, MediaFileUpload

# ========== CONFIGURACIÓN ==========
FOLDER_ID = '1XtYWNZsPhjVDttPZmuBKkwtzg3wLuC8g'
SCOPES = ['https://www.googleapis.com/auth/drive']

TESSERACT_CMD = 'tesseract'
pytesseract.pytesseract.tesseract_cmd = TESSERACT_CMD

# Para ignorar archivos "ya renombrados" sin ceros a la izquierda
PATTERN_RENAMED = r'^[0-9]{11}_[1-9]\d*_[1-9]\d*_[1-9]\d*\.pdf$'

def autenticar():
    creds = None
    if os.path.exists('token.json'):
        creds = Credentials.from_authorized_user_file('token.json', SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file('credentials.json', SCOPES)
            creds = flow.run_local_server(port=0)
        with open('token.json', 'w') as token:
            token.write(creds.to_json())
    return build('drive', 'v3', credentials=creds)

def limpiar_numero(num_str):
    try:
        return str(int(num_str))
    except:
        return num_str

def extraer_cuit(texto):
    match = re.search(r'\b(\d{2}-?\d{8}-?\d{1})\b', texto)
    if match:
        return match.group(1).replace("-", "")
    return None

def extraer_tipo_y_letra(texto):
    # 1) Tipo
    tipo_match = re.search(r'(FACTURA|RECIBO)', texto, re.IGNORECASE)
    if not tipo_match:
        return None, None
    tipo = tipo_match.group(1).upper()

    # 2) Letra:
    # A) ([BC])COD.
    letra_cod = re.search(r'([BC])\s*COD\.?\s*\d*', texto, re.IGNORECASE)
    if letra_cod:
        return tipo, letra_cod.group(1).upper()

    # B) Letra suelta
    letra_suelta = re.search(r'(^|\n)\s*([BC])\s*(\n|$)', texto, re.IGNORECASE)
    if letra_suelta:
        return tipo, letra_suelta.group(2).upper()

    # C) "B(\d\d+)" => B006, C011, etc. => si ves "C011" interpretamos letra = C
    letra_numerica = re.search(r'\b([BC])\d{2,4}\b', texto, re.IGNORECASE)
    if letra_numerica:
        return tipo, letra_numerica.group(1).upper()

    return None, None

def tipo_y_letra_a_codigo(tipo, letra):
    if not tipo or not letra:
        return None
    mapa = {
        ('B','FACTURA'): 3,
        ('B','RECIBO'): 4,
        ('C','FACTURA'): 5,
        ('C','RECIBO'): 6
    }
    return mapa.get((letra, tipo))

def extraer_pv_nro(texto):
    """
    Varios planes (A-F) para capturar PV y Nro. 
    """
    # Plan A
    patron_a = re.search(r'Punto\s*de\s*Venta:\s*.*Comp\.?\s*Nro:\s*0*(\d+)\s+0*(\d+)', texto, re.DOTALL)
    if patron_a:
        return limpiar_numero(patron_a.group(1)), limpiar_numero(patron_a.group(2))

    # Plan B: 'Nro 00004-00003575'
    patron_b = re.search(r'Nro\s+0*(\d+)-0*(\d+)', texto)
    if patron_b:
        return limpiar_numero(patron_b.group(1)), limpiar_numero(patron_b.group(2))

    # Plan C: '0002-00027842' a secas
    patron_c = re.search(r'\b0*(\d+)-0*(\d+)\b', texto)
    if patron_c:
        return limpiar_numero(patron_c.group(1)), limpiar_numero(patron_c.group(2))

    # Plan D: (FAC-)?B-0003-00002475 con espacios
    patron_d = re.search(r'(FAC\-)?([BC])\s*-\s*0*(\d+)\s*-\s*0*(\d+)', texto, re.IGNORECASE)
    if patron_d:
        return limpiar_numero(patron_d.group(3)), limpiar_numero(patron_d.group(4))

    # Plan E: (FAC-)?B-0003-00002475 sin espacios
    #  => "B-0003-00002475", "FAC-B-0003-00002475"
    patron_e = re.search(r'(FAC\-)?([BC])\-0*(\d+)\-0*(\d+)', texto, re.IGNORECASE)
    if patron_e:
        return limpiar_numero(patron_e.group(3)), limpiar_numero(patron_e.group(4))

    # Plan F: "C-00004-00011824" con la C (o B)
    # (ya cubierto en E, pero si aparece algo distinto, se añade)

    return None, None

def extraer_datos_flexible(texto):
    # 1) CUIT
    cuit = extraer_cuit(texto)
    if not cuit:
        return None

    # 2) Tipo y Letra
    tipo, letra = extraer_tipo_y_letra(texto)
    codigo = tipo_y_letra_a_codigo(tipo, letra)

    # 3) PV y Nro
    pv, nro = extraer_pv_nro(texto)

    # 4) Fallback si la letra no salió
    if (not codigo) and letra is None:
        # Plan D/E: "B-0003-00002475"
        plan_de_letra = re.search(r'(FAC\-)?([BC])\-0*(\d+)\-0*(\d+)', texto, re.IGNORECASE)
        if plan_de_letra:
            let = plan_de_letra.group(2).upper()
            if tipo:
                codigo = tipo_y_letra_a_codigo(tipo, let)

    if not (cuit and codigo and pv and nro):
        return None

    return f"{cuit}_{codigo}_{pv}_{nro}.pdf"

def leer_pagina(pdf_bytes, pagina):
    try:
        reader = PdfReader(pdf_bytes)
        if pagina >= len(reader.pages):
            return ""
        return reader.pages[pagina].extract_text() or ""
    except:
        return ""

def leer_pagina_ocr(pdf_bytes, pagina):
    try:
        images = convert_from_bytes(pdf_bytes.getvalue(), first_page=pagina+1, last_page=pagina+1)
        return pytesseract.image_to_string(images[0])
    except:
        return ""

def extraer_desde_dos_paginas(fh):
    texto_1 = leer_pagina(fh, 0)
    texto_2 = leer_pagina(fh, 1)

    print("\n--- TEXTO PÁGINA 1 ---\n", texto_1[:1000])
    print("\n--- TEXTO PÁGINA 2 ---\n", texto_2[:1000])

    # OCR si ambas casi vacías
    if len((texto_1 + texto_2).strip()) < 20:
        texto_1 = leer_pagina_ocr(fh, 0)
        texto_2 = leer_pagina_ocr(fh, 1)
        print("\n--- TEXTO PÁGINA 1 (OCR) ---\n", texto_1[:1000])
        print("\n--- TEXTO PÁGINA 2 (OCR) ---\n", texto_2[:1000])

    fh.seek(0)

    datos1 = extraer_datos_flexible(texto_1)
    datos2 = extraer_datos_flexible(texto_2)

    if datos1 and datos2:
        if datos1 == datos2:
            return datos1, None
        else:
            return None, '❌ Inconsistencia entre página 1 y 2'
    elif datos1:
        return datos1, None
    elif datos2:
        return datos2, None
    else:
        return None, '❌ No se pudo extraer información de ninguna página'

def extraer_desde_imagen(image_bytes):
    try:
        image = Image.open(io.BytesIO(image_bytes))
        texto = pytesseract.image_to_string(image)
        nuevo_nombre = extraer_datos_flexible(texto)
        if nuevo_nombre:
            return nuevo_nombre, None
        return None, '❌ No se pudo extraer información desde imagen'
    except Exception as e:
        return None, f'OCR Error en imagen: {e}'

def subir_log(service, filepath, folder_id):
    file_metadata = {'name': os.path.basename(filepath), 'parents': [folder_id]}
    media = MediaFileUpload(filepath, mimetype='text/csv')
    service.files().create(body=file_metadata, media_body=media, fields='id').execute()

def descargar_y_renombrar(service):
    resultados = []
    archivos = service.files().list(
        q=f"'{FOLDER_ID}' in parents and (mimeType='application/pdf' or mimeType contains 'image/')",
        fields="files(id, name, mimeType)",
        pageSize=1000
    ).execute().get('files', [])

    if not archivos:
        print("No se encontraron archivos.")
        return

    renombrados = 0
    errores = 0

    print(f"Se encontraron {len(archivos)} archivos en la carpeta.")

    for archivo in archivos:
        file_id = archivo['id']
        nombre_original = archivo['name']
        tipo = archivo['mimeType']

        # Ignorar si ya está en formato final
        matched = re.match(PATTERN_RENAMED, nombre_original)
        if matched:
            print(f"⚠️ Ignorando {nombre_original} porque ya cumple la pattern.")
            continue

        print(f"\n==============================")
        print(f"Procesando: {nombre_original}")

        request = service.files().get_media(fileId=file_id)
        fh = io.BytesIO()
        downloader = MediaIoBaseDownload(fh, request)
        done = False
        while not done:
            status, done = downloader.next_chunk()
        fh.seek(0)

        if tipo == 'application/pdf':
            nuevo_nombre, error = extraer_desde_dos_paginas(fh)
        elif tipo.startswith('image/'):
            nuevo_nombre, error = extraer_desde_imagen(fh.getvalue())
        else:
            resultados.append([nombre_original, '', '⚠️ Ignorado', 'Tipo no admitido'])
            continue

        if error:
            errores += 1
            resultados.append([nombre_original, '', '❌ ERROR', error])
            print(f"  ❌ {error}")
            continue

        # Renombrar
        try:
            service.files().update(fileId=file_id, body={'name': nuevo_nombre}).execute()
            renombrados += 1
            resultados.append([nombre_original, nuevo_nombre, '✅ OK', ''])
            print(f"  ✅ Renombrado a: {nuevo_nombre}")
        except Exception as e:
            errores += 1
            resultados.append([nombre_original, '', '❌ ERROR', f'Error al renombrar: {e}'])
            print(f"  ❌ Error al renombrar: {e}")

    # Generar log
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    log_filename = f'log_renombrado_{timestamp}.csv'
    with open(log_filename, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow(['Nombre original', 'Nombre nuevo', 'Estado', 'Observación'])
        writer.writerows(resultados)

    # Subir log
    subir_log(service, log_filename, FOLDER_ID)

    print(f"\n✅ Log guardado y subido como '{log_filename}'")
    print(f"\n📄 Total de archivos revisados: {len(archivos)}")
    print(f"✅ Renombrados correctamente: {renombrados}")
    print(f"❌ Con errores: {errores}")


# ========== EJECUCIÓN ==========
if __name__ == '__main__':
    servicio = autenticar()
    descargar_y_renombrar(servicio)