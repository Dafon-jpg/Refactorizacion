#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Script para generar archivos TXT con datos de facturas para obras sociales.
Versión sin emojis para evitar problemas de codificación en Windows.
"""

import os
import io
import re
import csv
import logging
from datetime import datetime

import pandas as pd
from PyPDF2 import PdfReader
from pdf2image import convert_from_bytes
import pytesseract
from PIL import Image

from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload, MediaFileUpload

# Configurar logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("genera_txt.log", encoding='utf-8')
    ]
)
logger = logging.getLogger(__name__)

# Google Drive
SCOPES = ["https://www.googleapis.com/auth/drive"]

# Personaliza estos valores
PDF_FOLDER_ID = "1-pMVR5Nh4k_Jlenygaju0R1nH0YcGTFP"  # carpeta de Drive con los PDF
EXCEL_NAME = "Excel base de datos OSPIDA 2-2025.xlsx"  # nombre exacto del .xlsx dentro de esa carpeta

# OCR – ajusta si tu tesseract.exe está en otra ruta
TESSERACT_CMD = "tesseract"
pytesseract.pytesseract.tesseract_cmd = TESSERACT_CMD

# Mapping de (tipo, letra) → código AFIP
CODIGO_CBTE = {
    ("FACTURA", "B"): "03",
    ("RECIBO", "B"): "04",
    ("FACTURA", "C"): "05",
    ("RECIBO", "C"): "06",
}

# Actividades válidas con DEPENDENCIA (para el flag final N / S)
ACTIVIDADES_DEP = {
    "001", "002", "003", "004", "005", "006", "007", "008", "009", "010",
    "011", "012", "037", "038", "039", "040", "041", "042", "043", "044",
    "045", "046", "047", "048", "058", "059", "060", "061", "062", "063",
    "064", "065", "066", "067", "068", "069", "070", "071", "072", "076",
    "077", "078", "096",
}

# ===== FUNCIONES DE EXTRACCIÓN =====
def limpiar_numero(num_str: str) -> str:
    """Elimina ceros a la izquierda de un número."""
    try:
        return str(int(num_str)) if num_str.isdigit() else num_str
    except:
        return num_str


def extraer_cuits(texto: str) -> list:
    """Extrae todos los CUITs presentes en el texto."""
    cuits = []
    # Buscar patrones comunes de CUIT/CUIL (con o sin guiones)
    patrones = [
        r"\bCUIT:?\s*(\d{2}-\d{8}-\d)\b",  # CUIT: XX-XXXXXXXX-X
        r"\bCUIT:?\s*(\d{11})\b",          # CUIT: XXXXXXXXXXX
        r"\b(\d{2}-\d{8}-\d)\b",           # XX-XXXXXXXX-X
        r"\b(\d{11})\b"                   # XXXXXXXXXXX (11 dígitos juntos)
    ]
    
    for patron in patrones:
        matches = re.finditer(patron, texto, re.I)
        for match in matches:
            cuit = match.group(1).replace("-", "")
            if cuit not in cuits and len(cuit) == 11:
                cuits.append(cuit)
    
    return cuits


def extraer_tipo_letra(texto: str) -> tuple:
    """Extrae el tipo de comprobante y la letra (B/C)."""
    tipo, letra = None, None
    
    # Buscar tipo
    if re.search(r"\bFACTURA\b", texto, re.I):
        tipo = "FACTURA"
    elif re.search(r"\bRECIBO\b", texto, re.I):
        tipo = "RECIBO"
    
    # Buscar letra
    patrones_letra = [
        r"([BC])\s+FACTURA",               # C FACTURA
        r"FACTURA\s+([BC])",               # FACTURA C
        r"([BC])\s+COD",                   # B COD.
        r"COD\.?\s*(\d+)",                 # COD. 011 (011=C Factura)
        r"(^|\n)\s*([BC])\s*(\n|$)",       # letra suelta
        r"\b([BC])\d{2,4}\b",              # C011
    ]
    
    for patron in patrones_letra:
        m = re.search(patron, texto, re.I)
        if m:
            grupo = m.group(1)
            if grupo in ["B", "C", "b", "c"]:
                letra = grupo.upper()
                break
            
            # Si es un código, inferir letra
            if patron == r"COD\.?\s*(\d+)" and grupo:
                codigo = grupo
                if codigo == "011":  # Código específico para Factura C
                    letra = "C"
                elif codigo == "006":  # Código específico para Recibo C
                    letra = "C"
                elif codigo == "008":  # Código específico para Factura B
                    letra = "B"
                elif codigo == "009":  # Código específico para Recibo B
                    letra = "B"
                break
    
    # Si seguimos sin letra pero tenemos tipo, buscar letra en el contexto
    if tipo and not letra:
        # Si dice FACTURA C o C FACTURA en alguna parte
        if tipo == "FACTURA" and ("C FACTURA" in texto or "FACTURA C" in texto):
            letra = "C"
        elif tipo == "FACTURA" and ("B FACTURA" in texto or "FACTURA B" in texto):
            letra = "B"
        elif tipo == "RECIBO" and ("C RECIBO" in texto or "RECIBO C" in texto):
            letra = "C"
        elif tipo == "RECIBO" and ("B RECIBO" in texto or "RECIBO B" in texto):
            letra = "B"
    
    return tipo, letra


def extraer_pv_nro(texto: str) -> tuple:
    """Extrae el punto de venta y número de comprobante."""
    patrones = [
        # "Punto de Venta: 00002    Comp. Nro: 00000924"
        r"Punto\s*de\s*Venta:?\s*0*(\d+)\s+Comp\.?\s*Nro:?\s*0*(\d+)",
        r"Punto\s*de\s*Venta:?\s*0*(\d+).*?Comp\.?\s*Nro:?\s*0*(\d+)",
        
        # Patrones alternativos
        r"\b0*(\d+)\s*[-–]\s*0*(\d{1,9})\b",  # 00004-00003575
        r"Nro\s+0*(\d+)\s*-\s*0*(\d+)",       # Nro 00004-00003575
        r"(FAC\-)?([BC])\s*-\s*0*(\d+)\s*-\s*0*(\d+)",  # Con espacios
        r"(FAC\-)?([BC])\-0*(\d+)\-0*(\d+)",  # Sin espacios
    ]
    
    for patron in patrones:
        m = re.search(patron, texto, re.I)
        if m:
            # Los patrones 0-3 tienen PV en grupo 1 y nro en grupo 2
            if "FAC" in patron:
                return limpiar_numero(m.group(3)), limpiar_numero(m.group(4))
            else:
                return limpiar_numero(m.group(1)), limpiar_numero(m.group(2))
    
    return None, None


def extraer_fecha(texto: str) -> str:
    """Extrae la fecha de emisión del documento."""
    # Buscar fecha explícita de emisión
    fecha_match = re.search(r"Fecha\s+de\s+Emisión:?\s*(\d{2}/\d{2}/\d{4})", texto, re.I)
    if fecha_match:
        return fecha_match.group(1)
    
    # Si no hay fecha explícita, buscar todas las fechas
    fechas = re.findall(r"\d{2}/\d{2}/\d{4}", texto)
    if len(fechas) >= 4:
        # En muchas facturas, la 4ª fecha es la fecha de emisión
        return fechas[3]
    elif fechas:
        # Si no hay 4 fechas, usar la primera
        return fechas[0]
    
    # Si no hay fechas con formato estándar, intentar otros formatos
    alt_fechas = re.findall(r"\d{2}-\d{2}-\d{4}", texto)
    if alt_fechas:
        return alt_fechas[0].replace("-", "/")
    
    # Si no hay fechas, usar la fecha actual
    return datetime.now().strftime("%d/%m/%Y")


def extraer_cae(texto: str) -> tuple:
    """Extrae el CAE/CAI y el tipo de emisión (E/I)."""
    # Buscar CAE explícito
    cae_match = re.search(r"CAE\s*N°:?\s*(\d{14})", texto, re.I)
    if cae_match:
        return cae_match.group(1), "E"
    
    # Buscar al final del documento (común en muchas facturas)
    cae_final = re.search(r"Pág\.\s*1/1\s+(\d{14})", texto)
    if cae_final:
        return cae_final.group(1), "E"
    
    # Buscar cualquier número de 14 dígitos cerca de "CAE"
    cae_cercano = re.search(r"CAE.*?(\d{14})", texto, re.DOTALL | re.I)
    if cae_cercano:
        return cae_cercano.group(1), "E"
    
    # Buscar CAI (Código de Autorización de Impresión)
    cai_match = re.search(r"CAI\s*N°:?\s*(\d{14})", texto, re.I)
    if cai_match:
        return cai_match.group(1), "I"
    
    # Última opción: cualquier número de 14 dígitos en el documento
    cualquier_14 = re.search(r"\b(\d{14})\b", texto)
    if cualquier_14:
        return cualquier_14.group(1), "E"  # Asumimos E por ser más común
    
    return None, None


def extraer_importe(texto: str) -> str:
    """Extrae el importe total del documento."""
    # Patrones de búsqueda del importe
    patrones = [
        r"Importe Total:?\s*\$?\s*([\d.,]+)",
        r"TOTAL:?\s*\$?\s*([\d.,]+)",
        r"Total:?\s*\$?\s*([\d.,]+)",
        r"IMPORTE TOTAL:?\s*\$?\s*([\d.,]+)",
    ]
    
    # Buscar importe con etiqueta
    for patron in patrones:
        m = re.search(patron, texto, re.I)
        if m:
            # Limpiar formato de números
            importe = m.group(1).replace(".", "").replace(",", "")
            return importe
    
    # Si no hay etiqueta, buscar importes numéricos con formato
    importes = re.findall(r"(\d{3,6}(?:\.\d{3})*(?:,\d{2}))", texto)
    if importes:
        # El último importe suele ser el total
        ultimo_importe = importes[-1]
        return ultimo_importe.replace(".", "").replace(",", "")
    
    return None


def extraer_periodo(texto: str) -> str:
    """Extrae el período facturado en formato MMAAAA."""
    # Buscar "Período Facturado Desde: dd/mm/yyyy Hasta: dd/mm/yyyy"
    periodo_match = re.search(r"Período\s*Facturado\s*Desde:?\s*\d{2}/(\d{2})/(\d{4})", texto, re.I)
    if periodo_match:
        return f"{periodo_match.group(1)}{periodo_match.group(2)}"
    
    # Buscar menciones al "mes de XXX de YYYY"
    mes_match = re.search(r"mes\s+de\s+(\w+)\s+de\s+(\d{4})", texto, re.I)
    if mes_match:
        mes_texto = mes_match.group(1).lower()
        año = mes_match.group(2)
        meses = {
            "enero": "01", "febrero": "02", "marzo": "03", "abril": "04",
            "mayo": "05", "junio": "06", "julio": "07", "agosto": "08",
            "septiembre": "09", "octubre": "10", "noviembre": "11", "diciembre": "12"
        }
        if mes_texto in meses:
            return f"{meses[mes_texto]}{año}"
    
    # Si no encontramos nada, usar el mes actual
    ahora = datetime.now()
    return f"{ahora.month:02d}{ahora.year}"


def map_actividad(texto: str) -> tuple:
    """Determina el código de actividad y la bandera de dependencia."""
    texto_lower = texto.lower()
    
    # Transporte
    if "transporte" in texto_lower or "traslado" in texto_lower or re.search(r"\bkm\b", texto_lower):
        dep_flag = "S" if any(term in texto_lower for term in ["dependencia", "discapacidad", "discapac"]) else "N"
        return "096", dep_flag
    
    # Prestaciones profesionales (psicología, etc.)
    if any(term in texto_lower for term in [
        "psicología", "psicologia", "psicólogo", "psicologo",
        "musicoterapia", "musicoterapeuta",
        "kinesiología", "kinesiologia", "kinesiólogo", "kinesiologo",
        "fonoaudiología", "fonoaudiologia", "fonoaudiólogo", "fonoaudiologo",
        "psicopedagogía", "psicopedagogia", "psicopedagogo"
    ]):
        return "091", "N"
    
    # Estimulación temprana
    if "estimulación temprana" in texto_lower or "estimulacion temprana" in texto_lower:
        return "085", "N"
    
    # Apoyo a la integración escolar
    if any(term in texto_lower for term in [
        "módulo de apoyo", "modulo de apoyo", 
        "apoyo a la integración", "apoyo a la integracion",
        "maestra integradora", "maestro integrador"
    ]):
        return "089", "N"
    
    # Actividades terapéuticas
    if "honorarios profesionales" in texto_lower or "sesiones" in texto_lower or "terapia" in texto_lower:
        return "090", "N"
    
    # Por defecto, usar código genérico
    dep_flag = "S" if any(term in texto_lower for term in ["dependencia", "discapacidad", "discapac"]) else "N"
    return "090", dep_flag


def cantidad_por_actividad(cod: str) -> str:
    """Devuelve la cantidad predeterminada según el código de actividad."""
    if cod == "096":  # Transporte
        return "001500"
    if cod in {"090", "091"}:  # Terapias y profesionales
        return "000004"
    # Actividades mensuales
    return "000001"


def leer_pagina_text(pdf_bytes: io.BytesIO, idx: int) -> str:
    """Extrae texto de una página PDF usando PyPDF2."""
    try:
        reader = PdfReader(pdf_bytes)
        if idx < len(reader.pages):
            texto = reader.pages[idx].extract_text() or ""
            return texto
    except Exception as e:
        logger.error(f"Error al leer texto de PDF: {e}")
    return ""


def leer_pagina_ocr(pdf_bytes: io.BytesIO, idx: int) -> str:
    """Extrae texto de una página PDF usando OCR."""
    try:
        images = convert_from_bytes(pdf_bytes.getvalue(), first_page=idx + 1, last_page=idx + 1)
        return pytesseract.image_to_string(images[0])
    except Exception as e:
        logger.error(f"Error en OCR: {e}")
    return ""


def extraer_info_pdf(fh: io.BytesIO, nombre_archivo: str) -> dict:
    """
    Extrae toda la información relevante de un PDF de factura.
    Devuelve un diccionario con los datos necesarios para el archivo TXT.
    """
    # Reiniciar el stream
    fh.seek(0)
    
    # Leer texto de las primeras dos páginas
    texto1 = leer_pagina_text(fh, 0)
    texto2 = leer_pagina_text(fh, 1)
    
    # Debug
    logger.info(f"\n--- ARCHIVO: {nombre_archivo} ---")
    logger.info(f"--- TEXTO PÁGINA 1 ---\n{texto1[:500]}")
    logger.info(f"--- TEXTO PÁGINA 2 ---\n{texto2[:500]}")
    
    # Si el texto es insuficiente, intentar con OCR
    if len(texto1) < 200 or len(texto2) < 200:
        logger.info("Texto insuficiente, intentando OCR...")
        try:
            fh.seek(0)
            texto1_ocr = leer_pagina_ocr(fh, 0)
            texto2_ocr = leer_pagina_ocr(fh, 1)
            
            # Si OCR da más texto, usarlo
            if len(texto1_ocr) > len(texto1):
                texto1 = texto1_ocr
            if len(texto2_ocr) > len(texto2):
                texto2 = texto2_ocr
                
            logger.info(f"--- TEXTO PÁGINA 1 (OCR) ---\n{texto1[:500]}")
            logger.info(f"--- TEXTO PÁGINA 2 (OCR) ---\n{texto2[:500]}")
        except Exception as e:
            logger.error(f"Error en OCR: {e}")
    
    # Reiniciar el stream
    fh.seek(0)
    
    # Texto completo
    texto_completo = texto1 + "\n" + texto2
    
    # 1. Extraer CUITs
    cuits = extraer_cuits(texto_completo)
    if not cuits:
        logger.warning(f"No se encontraron CUITs en {nombre_archivo}")
        return {}
    
    # El primer CUIT generalmente es el emisor (prestador)
    cuit_emisor = cuits[0]
    logger.info(f"CUIT emisor encontrado: {cuit_emisor}")
    
    # 2. Extraer tipo y letra
    tipo, letra = extraer_tipo_letra(texto_completo)
    if not tipo or not letra:
        logger.warning(f"No se pudo determinar tipo y letra en {nombre_archivo}")
        # Intentar inferir
        if "FACTURA" in texto_completo.upper():
            tipo = "FACTURA"
            if "C" in texto_completo:
                letra = "C"
            elif "B" in texto_completo:
                letra = "B"
    
    # 3. Determinar código de comprobante
    codigo_cbte = None
    if tipo and letra:
        codigo_cbte = CODIGO_CBTE.get((tipo, letra))
        
    if not codigo_cbte:
        logger.warning(f"No se pudo determinar código de comprobante para {tipo} {letra}")
        return {}
    
    logger.info(f"Tipo: {tipo}, Letra: {letra}, Código: {codigo_cbte}")
    
    # 4. Extraer punto de venta y número
    pv, nro = extraer_pv_nro(texto_completo)
    if not pv or not nro:
        logger.warning(f"No se pudo extraer PV y número en {nombre_archivo}")
        return {}
    
    logger.info(f"PV: {pv}, Número: {nro}")
    
    # 5. Extraer fecha
    fecha_cbte = extraer_fecha(texto_completo)
    logger.info(f"Fecha: {fecha_cbte}")
    
    # 6. Extraer CAE
    nro_cae, tipo_emision = extraer_cae(texto_completo)
    logger.info(f"CAE: {nro_cae}, Tipo: {tipo_emision}")
    
    # 7. Extraer importe
    importe = extraer_importe(texto_completo)
    logger.info(f"Importe: {importe}")
    
    # 8. Extraer período
    periodo = extraer_periodo(texto_completo)
    logger.info(f"Período: {periodo}")
    
    # 9. Determinar actividad
    actividad, dep_flag = map_actividad(texto_completo)
    logger.info(f"Actividad: {actividad}, Dependencia: {dep_flag}")
    
    # 10. Determinar cantidad
    cantidad = cantidad_por_actividad(actividad)
    
    # Crear y devolver el resultado
    resultado = {
        "cuit_pre": cuit_emisor,
        "codigo_cbte": codigo_cbte,
        "pv": pv,
        "nro": nro,
        "fecha_cbte": fecha_cbte,
        "tipo_emision": tipo_emision or "E",  # E por defecto
        "nro_cae": nro_cae or "",
        "importe": importe or "0",
        "periodo": periodo,
        "actividad": actividad,
        "cantidad": cantidad,
        "dep": dep_flag,
    }
    
    return resultado


# ===== GOOGLE DRIVE =====
def autenticar():
    """Autenticación con Google Drive API."""
    creds = None
    if os.path.exists("token.json"):
        creds = Credentials.from_authorized_user_file("token.json", SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(
                "credentials.json", SCOPES
            )
            creds = flow.run_local_server(port=0)
        with open("token.json", "w") as tkn:
            tkn.write(creds.to_json())
    return build("drive", "v3", credentials=creds)


def listar_pdfs(service):
    """Lista todos los archivos PDF en la carpeta especificada."""
    q = (
        f"'{PDF_FOLDER_ID}' in parents and mimeType='application/pdf' "
        "and trashed = false"
    )
    files = []
    page_token = None
    while True:
        resp = (
            service.files()
            .list(
                q=q,
                spaces="drive",
                fields="nextPageToken, files(id, name)",
                pageSize=1000,
                pageToken=page_token,
            )
            .execute()
        )
        files.extend(resp.get("files", []))
        page_token = resp.get("nextPageToken", None)
        if page_token is None:
            break
    return files


def subir_txt(service, ruta, nombre):
    """Sube el archivo TXT generado a Google Drive."""
    meta = {"name": nombre, "parents": [PDF_FOLDER_ID]}
    media = MediaFileUpload(ruta, mimetype="text/plain")
    service.files().create(body=meta, media_body=media, fields="id").execute()
    logger.info(f"TXT subido a Drive como {nombre}")


def construir_linea(rnos, fila_excel, info_pdf):
    """Construye una línea del archivo TXT con el formato específico."""
    # Validar que tenemos todos los datos necesarios
    if not all(k in info_pdf for k in ["cuit_pre", "codigo_cbte", "pv", "nro", 
                                      "fecha_cbte", "tipo_emision", "nro_cae", 
                                      "importe", "periodo", "actividad", 
                                      "cantidad", "dep"]):
        return None
    
    # Asegurar formato correcto de los datos
    pv_limpio = info_pdf["pv"].zfill(5)  # 5 dígitos
    nro_limpio = info_pdf["nro"].zfill(8)  # 8 dígitos
    importe_limpio = info_pdf["importe"].zfill(14)  # 14 dígitos
    
    # Verificar longitud del código de certificado
    codigo_cert = fila_excel["codigo_certificado"]
    if len(codigo_cert) > 38:
        codigo_cert = codigo_cert[:38]
    else:
        codigo_cert = codigo_cert.ljust(38, "0")
    
    # Construir línea
    linea = [
        "DS",                           # Constante
        rnos,                           # RNOS de la obra social
        fila_excel["cuil"],             # CUIL del beneficiario
        codigo_cert,                    # Código de certificado (38 caracteres)
        fila_excel["vencimiento_certificado"],  # Vencimiento del certificado
        info_pdf["periodo"],            # Período facturado (MMAAAA)
        info_pdf["cuit_pre"],           # CUIT del prestador
        info_pdf["codigo_cbte"],        # Código de comprobante
        info_pdf["tipo_emision"],       # Tipo de emisión (E o I)
        info_pdf["fecha_cbte"],         # Fecha del comprobante
        info_pdf["nro_cae"],            # Número de CAE/CAI
        pv_limpio,                      # Punto de venta (5 dígitos)
        nro_limpio,                     # Número de comprobante (8 dígitos)
        importe_limpio,                 # Importe total (14 dígitos)
        importe_limpio,                 # Importe total [duplicado] (14 dígitos)
        info_pdf["actividad"],          # Código de actividad (3 dígitos)
        info_pdf["cantidad"],           # Cantidad (6 dígitos)
        fila_excel["provincia"],        # Código de provincia (2 dígitos)
        info_pdf["dep"],                # Indicador de dependencia (S/N)
    ]
    
    return "|".join(linea)


# ===== FUNCIÓN PRINCIPAL =====
def main():
    """Función principal del script."""
    try:
        # Input RNOS
        rnos = input("Ingrese el RNOS de la obra social (6 dígitos): ").strip()
        
        # Validar formato del RNOS
        if not rnos.isdigit():
            logger.warning("El RNOS debe ser un número")
            rnos = ''.join(c for c in rnos if c.isdigit())
        
        # Asegurar longitud correcta
        rnos = rnos.zfill(6)[:6]
        logger.info(f"RNOS: {rnos}")

        # Autenticación
        logger.info("Autenticando con Google Drive...")
        service = autenticar()
        logger.info("Autenticación exitosa")

        # 1. Obtener Excel
        logger.info(f"Buscando Excel '{EXCEL_NAME}' en la carpeta de Drive...")
        q_excel = (
            f"'{PDF_FOLDER_ID}' in parents and "
            f"name = '{EXCEL_NAME}' and mimeType contains 'spreadsheet'"
        )
        excel_files = (
            service.files()
            .list(q=q_excel, fields="files(id, name)", pageSize=1)
            .execute()
            .get("files", [])
        )

        if not excel_files:
            logger.error("No se encontró el Excel en la carpeta especificada.")
            return

        excel_id = excel_files[0]["id"]
        logger.info(f"Excel encontrado: {excel_files[0]['name']} (id={excel_id})")

        # 2. Descargar Excel
        logger.info("Descargando Excel...")
        fh = io.BytesIO()
        request = service.files().get_media(fileId=excel_id)
        downloader = MediaIoBaseDownload(fh, request)
        done = False
        while not done:
            status, done = downloader.next_chunk()
            logger.info(f"Descargando Excel: {int(status.progress() * 100)}%")
        fh.seek(0)

        # 3. Leer Excel
        logger.info("Procesando datos del Excel...")
        try:
            df = pd.read_excel(fh, dtype=str)
            # Normalizar nombres de columnas
            df.columns = df.columns.str.strip().str.lower().str.replace(" ", "_")
        except Exception as e:
            logger.error(f"Error al procesar el Excel: {e}")
            return

        # Verificar columnas requeridas
        columnas_requeridas = {"cuil", "codigo_certificado", "vencimiento_certificado", "provincia"}
        columnas_faltantes = columnas_requeridas - set(df.columns)
        if columnas_faltantes:
            logger.error(f"Faltan columnas en el Excel: {columnas_faltantes}")
            return

        # Limpiar datos
        for col in ["cuil", "codigo_certificado", "vencimiento_certificado", "provincia"]:
            df[col] = df[col].astype(str).str.strip()
        
        logger.info(f"Excel cargado con {len(df)} registros")

        # 4. Listar PDFs
        logger.info("Listando archivos PDF en la carpeta...")
        pdfs = listar_pdfs(service)
        if not pdfs:
            logger.error("No se encontraron archivos PDF en la carpeta.")
            return
        
        logger.info(f"Se encontraron {len(pdfs)} archivos PDF")

        # 5. Procesar PDFs
        logger.info("Procesando archivos PDF...")
        pdf_cache = {}  # Guarda información de PDFs por CUIT
        
        for i, pdf in enumerate(pdfs, 1):
            logger.info(f"\n[{i}/{len(pdfs)}] Procesando: {pdf['name']}")
            
            # Descargar PDF
            fh_pdf = io.BytesIO()
            request = service.files().get_media(fileId=pdf["id"])
            downloader = MediaIoBaseDownload(fh_pdf, request)
            
            done = False
            while not done:
                status, done = downloader.next_chunk()
                logger.info(f"Descargando PDF: {int(status.progress() * 100)}%")
            
            fh_pdf.seek(0)
            
            # Extraer información
            try:
                info = extraer_info_pdf(fh_pdf, pdf["name"])
                
                if info and "cuit_pre" in info and info["cuit_pre"]:
                    cuit = info["cuit_pre"]
                    pdf_cache[cuit] = {
                        "info": info,
                        "nombre": pdf["name"]
                    }
                    logger.info(f"Información extraída para CUIT: {cuit}")
                else:
                    logger.warning(f"No se pudo extraer información del PDF: {pdf['name']}")
            except Exception as e:
                logger.error(f"Error al procesar el PDF {pdf['name']}: {e}")
                continue

        # 6. Generar TXT
        logger.info("\nGenerando archivo TXT...")
        lineas_txt = []
        registros_procesados = 0
        registros_con_error = 0
        
        for idx, fila in df.iterrows():
            cuil = fila["cuil"].strip()
            
            # Buscar PDF correspondiente por CUIT
            if cuil in pdf_cache:
                info_pdf = pdf_cache[cuil]["info"]
                linea = construir_linea(rnos, fila, info_pdf)
                
                if linea:
                    lineas_txt.append(linea)
                    registros_procesados += 1
                    logger.info(f"Registro procesado: CUIL {cuil} con {pdf_cache[cuil]['nombre']}")
                else:
                    registros_con_error += 1
                    logger.warning(f"No se pudo construir línea para CUIL {cuil}")
            else:
                registros_con_error += 1
                logger.warning(f"No se encontró PDF para CUIL {cuil}")

        # Verificar si se generaron líneas
        if not lineas_txt:
            logger.error("No se generó ninguna línea para el archivo TXT.")
            return

        # 7. Escribir TXT
        # Obtener período del primer registro (o usar el actual)
        periodo_txt = lineas_txt[0].split("|")[5] if lineas_txt else datetime.now().strftime("%m%Y")
        nombre_txt = f"{rnos}_ds.txt"
        
        with open(nombre_txt, "w", encoding="utf-8", newline="") as f:
            f.write("\n".join(lineas_txt))
        
        logger.info(f"Archivo TXT generado: {nombre_txt} ({len(lineas_txt)} líneas)")

        # 8. Subir TXT a Drive
        logger.info("Subiendo archivo TXT a Google Drive...")
        subir_txt(service, nombre_txt, nombre_txt)
        
        # 9. Resumen
        logger.info("\n" + "="*50)
        logger.info(f"RESUMEN DEL PROCESO:")
        logger.info(f"- Total de registros en Excel: {len(df)}")
        logger.info(f"- PDFs encontrados: {len(pdfs)}")
        logger.info(f"- PDFs procesados correctamente: {len(pdf_cache)}")
        logger.info(f"- Registros procesados en TXT: {registros_procesados}")
        logger.info(f"- Registros con error: {registros_con_error}")
        logger.info("="*50)

    except Exception as e:
        logger.error(f"Error general en la ejecución: {e}", exc_info=True)


# ===== EJECUCIÓN =====
if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        logger.info("\nProceso interrumpido por el usuario")
    except Exception as e:
        logger.error(f"Error inesperado: {e}", exc_info=True)
    finally:
        logger.info("\nFin del proceso")