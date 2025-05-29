#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Script para probar la extracción de datos de facturas.
Este programa te permite probar la extracción de datos de una factura PDF
específica sin necesidad de ejecutar todo el proceso.
Versión sin emojis para evitar problemas de codificación en Windows.
"""

import io
import os
import sys
import re
from datetime import datetime

from PyPDF2 import PdfReader
from pdf2image import convert_from_bytes
import pytesseract

# Configurar Tesseract
TESSERACT_CMD = "tesseract"
pytesseract.pytesseract.tesseract_cmd = TESSERACT_CMD

# Mapping de (tipo, letra) → código AFIP
CODIGO_CBTE = {
    ("FACTURA", "B"): "03",
    ("RECIBO", "B"): "04",
    ("FACTURA", "C"): "05",
    ("RECIBO", "C"): "06",
}

# ===== FUNCIONES DE EXTRACCIÓN =====
def limpiar_numero(num_str):
    """Elimina ceros a la izquierda de un número."""
    try:
        return str(int(num_str)) if num_str.isdigit() else num_str
    except:
        return num_str


def extraer_cuits(texto):
    """Extrae todos los CUITs presentes en el texto."""
    cuits = []
    # Buscar patrones comunes de CUIT/CUIL (con o sin guiones)
    patrones = [
        r"\bCUIT:?\s*(\d{2}-\d{8}-\d)\b",  # CUIT: XX-XXXXXXXX-X
        r"\bCUIT:?\s*(\d{11})\b",          # CUIT: XXXXXXXXXXX
        r"\b(\d{2}-\d{8}-\d)\b",           # XX-XXXXXXXX-X
        r"\b(\d{11})\b"                    # XXXXXXXXXXX (11 dígitos juntos)
    ]
    
    for patron in patrones:
        matches = re.finditer(patron, texto, re.I)
        for match in matches:
            cuit = match.group(1).replace("-", "")
            if cuit not in cuits and len(cuit) == 11:
                cuits.append(cuit)
    
    return cuits


def extraer_tipo_letra(texto):
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


def extraer_pv_nro(texto):
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


def extraer_fecha(texto):
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


def extraer_cae(texto):
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


def extraer_importe(texto):
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


def extraer_periodo(texto):
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


def map_actividad(texto):
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


def cantidad_por_actividad(cod):
    """Devuelve la cantidad predeterminada según el código de actividad."""
    if cod == "096":  # Transporte
        return "001500"
    if cod in {"090", "091"}:  # Terapias y profesionales
        return "000004"
    # Actividades mensuales
    return "000001"


def leer_pagina_text(pdf_bytes, idx):
    """Extrae texto de una página PDF usando PyPDF2."""
    try:
        reader = PdfReader(pdf_bytes)
        if idx < len(reader.pages):
            texto = reader.pages[idx].extract_text() or ""
            return texto
    except Exception as e:
        print(f"Error al leer texto de PDF: {e}")
    return ""


def leer_pagina_ocr(pdf_bytes, idx):
    """Extrae texto de una página PDF usando OCR."""
    try:
        images = convert_from_bytes(pdf_bytes.getvalue(), first_page=idx + 1, last_page=idx + 1)
        return pytesseract.image_to_string(images[0])
    except Exception as e:
        print(f"Error en OCR: {e}")
    return ""


def extraer_info_pdf(ruta_pdf):
    """
    Extrae toda la información relevante de un PDF de factura.
    Devuelve un diccionario con los datos necesarios para el archivo TXT.
    """
    print(f"\n===== ANALIZANDO: {os.path.basename(ruta_pdf)} =====")
    
    # Leer el archivo PDF
    with open(ruta_pdf, 'rb') as f:
        pdf_bytes = io.BytesIO(f.read())
    
    # Leer texto de las primeras dos páginas
    texto1 = leer_pagina_text(pdf_bytes, 0)
    texto2 = leer_pagina_text(pdf_bytes, 1)
    
    # Imprimir primeros caracteres para depuración
    print(f"\n--- TEXTO PÁGINA 1 (primeros 500 caracteres) ---")
    print(texto1[:500])
    print(f"\n--- TEXTO PÁGINA 2 (primeros 500 caracteres) ---")
    print(texto2[:500])
    
    # Si el texto es insuficiente, intentar con OCR
    if len(texto1) < 200 or len(texto2) < 200:
        print("\nTexto insuficiente, intentando OCR...")
        try:
            texto1_ocr = leer_pagina_ocr(pdf_bytes, 0)
            texto2_ocr = leer_pagina_ocr(pdf_bytes, 1)
            
            # Si OCR da más texto, usarlo
            if len(texto1_ocr) > len(texto1):
                texto1 = texto1_ocr
                print(f"\n--- TEXTO PÁGINA 1 (OCR, primeros 500 caracteres) ---")
                print(texto1[:500])
            
            if len(texto2_ocr) > len(texto2):
                texto2 = texto2_ocr
                print(f"\n--- TEXTO PÁGINA 2 (OCR, primeros 500 caracteres) ---")
                print(texto2[:500])
        except Exception as e:
            print(f"Error en OCR: {e}")
    
    # Texto completo
    texto_completo = texto1 + "\n" + texto2
    
    # 1. Extraer CUITs
    cuits = extraer_cuits(texto_completo)
    if not cuits:
        print("No se encontraron CUITs en el documento")
        return {}
    
    print(f"\nCUITs encontrados: {cuits}")
    
    # El primer CUIT generalmente es el emisor (prestador)
    cuit_emisor = cuits[0]
    print(f"CUIT emisor: {cuit_emisor}")
    
    # 2. Extraer tipo y letra
    tipo, letra = extraer_tipo_letra(texto_completo)
    if not tipo or not letra:
        print("No se pudo determinar tipo y letra")
        # Intentar inferir
        if "FACTURA" in texto_completo.upper():
            tipo = "FACTURA"
            if "C" in texto_completo:
                letra = "C"
            elif "B" in texto_completo:
                letra = "B"
            print(f"Tipo y letra inferidos: {tipo} {letra}")
    else:
        print(f"Tipo y letra: {tipo} {letra}")
    
    # 3. Determinar código de comprobante
    codigo_cbte = None
    if tipo and letra:
        codigo_cbte = CODIGO_CBTE.get((tipo, letra))
        
    if not codigo_cbte:
        print(f"No se pudo determinar código de comprobante para {tipo} {letra}")
        return {}
    
    print(f"Código de comprobante: {codigo_cbte}")
    
    # 4. Extraer punto de venta y número
    pv, nro = extraer_pv_nro(texto_completo)
    if not pv or not nro:
        print("No se pudo extraer punto de venta y número")
        return {}
    
    print(f"PV: {pv}, Número: {nro}")
    
    # 5. Extraer fecha
    fecha_cbte = extraer_fecha(texto_completo)
    print(f"Fecha de emisión: {fecha_cbte}")
    
    # 6. Extraer CAE
    nro_cae, tipo_emision = extraer_cae(texto_completo)
    print(f"CAE: {nro_cae}, Tipo emisión: {tipo_emision}")
    
    # 7. Extraer importe
    importe = extraer_importe(texto_completo)
    print(f"Importe: {importe}")
    
    # 8. Extraer período
    periodo = extraer_periodo(texto_completo)
    print(f"Período: {periodo}")
    
    # 9. Determinar actividad
    actividad, dep_flag = map_actividad(texto_completo)
    print(f"Actividad: {actividad}, Dependencia: {dep_flag}")
    
    # 10. Determinar cantidad
    cantidad = cantidad_por_actividad(actividad)
    print(f"Cantidad: {cantidad}")
    
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


def simular_linea_txt(info_pdf, rnos="000000"):
    """Simula la generación de una línea del archivo TXT."""
    # Datos del Excel (simulados)
    excel_data = {
        "cuil": info_pdf["cuit_pre"],  # Usamos el mismo CUIT como CUIL para el ejemplo
        "codigo_certificado": "ARG0100020545780489000000000000000000000",
        "vencimiento_certificado": "30/03/2026",
        "provincia": "00"
    }
    
    # Asegurar formato correcto
    pv_limpio = info_pdf["pv"].zfill(5)  # 5 dígitos
    nro_limpio = info_pdf["nro"].zfill(8)  # 8 dígitos
    importe_limpio = info_pdf["importe"].zfill(14)  # 14 dígitos
    
    # Construir línea
    linea = [
        "DS",                           # Constante
        rnos,                           # RNOS de la obra social
        excel_data["cuil"],             # CUIL del beneficiario
        excel_data["codigo_certificado"].ljust(38, "0")[:38],  # Código certificado
        excel_data["vencimiento_certificado"],  # Vencimiento
        info_pdf["periodo"],            # Período
        info_pdf["cuit_pre"],           # CUIT del prestador
        info_pdf["codigo_cbte"],        # Código de comprobante
        info_pdf["tipo_emision"],       # Tipo de emisión
        info_pdf["fecha_cbte"],         # Fecha del comprobante
        info_pdf["nro_cae"],            # CAE/CAI
        pv_limpio,                      # Punto de venta
        nro_limpio,                     # Número de comprobante
        importe_limpio,                 # Importe total
        importe_limpio,                 # Importe total [duplicado]
        info_pdf["actividad"],          # Código de actividad
        info_pdf["cantidad"],           # Cantidad
        excel_data["provincia"],        # Código de provincia
        info_pdf["dep"],                # Indicador de dependencia
    ]
    
    return "|".join(linea)


def main():
    """Función principal."""
    # Verificar argumentos
    if len(sys.argv) < 2:
        print("Uso: python test_extraccion.py <ruta_al_pdf>")
        return
    
    ruta_pdf = sys.argv[1]
    
    # Verificar que el archivo existe
    if not os.path.exists(ruta_pdf):
        print(f"Error: El archivo {ruta_pdf} no existe")
        return
    
    # Verificar que es un PDF
    if not ruta_pdf.lower().endswith(".pdf"):
        print(f"Error: {ruta_pdf} no es un archivo PDF")
        return
    
    # Extraer información
    try:
        info = extraer_info_pdf(ruta_pdf)
        
        if not info:
            print("\nNo se pudo extraer información del PDF")
            return
        
        # Verificar datos críticos
        campos_criticos = ["cuit_pre", "codigo_cbte", "pv", "nro", "fecha_cbte"]
        faltantes = [c for c in campos_criticos if c not in info or not info[c]]
        
        if faltantes:
            print(f"\nFaltan campos críticos: {', '.join(faltantes)}")
        else:
            print("\nSe extrajeron todos los campos críticos")
        
        # Simular línea TXT
        print("\n===== LÍNEA PARA EL ARCHIVO TXT =====")
        linea = simular_linea_txt(info)
        print(linea)
        
        # Guardar resultados en archivo de texto para referencia
        nombre_salida = os.path.splitext(os.path.basename(ruta_pdf))[0] + "_info.txt"
        with open(nombre_salida, "w", encoding="utf-8") as f:
            f.write("===== INFORMACIÓN EXTRAÍDA =====\n\n")
            for k, v in info.items():
                f.write(f"{k}: {v}\n")
            f.write("\n===== LÍNEA PARA EL ARCHIVO TXT =====\n")
            f.write(linea)
        
        print(f"\nInformación guardada en {nombre_salida}")
        
    except Exception as e:
        print(f"Error al procesar el PDF: {e}")


if __name__ == "__main__":
    main()