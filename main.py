import os
import datetime

# --- Importamos nuestros Módulos ---
# (Asumimos que están en el PYTHONPATH o en la misma estructura)
# from config import settings
# from logging_module import logger
from entrada import receptor
from preprocesamiento import pdf_processor
from extraccion import layout_extractor
from inferencia import model_infer
from postprocesamiento import data_cleaner
from salida import output_generator

# --- Campos Esperados y Fallbacks ---
CAMPOS_REQUERIDOS = [
    "cuit_pre", "codigo_cpte", "pv", "nro", "fecha_cbte",
    "tipo_emision", "nro_cae", "importe", "periodo", "actividad",
    "dep", "cuil_afiliado_final", "nombre_afiliado_final", "dni_afiliado"
]

def obtener_fallbacks():
    """ Devuelve los valores por defecto para los campos. """
    now = datetime.datetime.now()
    return {
        "fecha_cbte": now.strftime("%Y-%m-%d"),
        "tipo_emision": "E",
        "periodo": now.strftime("%Y%m"),
        "actividad": "090",
        "dep": "N",
        # Otros campos podrían necesitar 'None' o un valor específico
        "cuit_pre": None,
        "codigo_cpte": None,
        "pv": None,
        "nro": None,
        "nro_cae": None,
        "importe": None,
        "cuil_afiliado_final": None,
        "nombre_afiliado_final": None,
        "dni_afiliado": None,
    }

def ejecutar_proceso_facturas(ruta_entrada, ruta_salida, formato_salida="csv"):
    """
    Orquesta el flujo completo de procesamiento de facturas.
    """
    print("--- Inicio del procesamiento de facturas ---")
    # logger.info("Inicio del procesamiento de facturas.") # Descomentar con Logging

    # Módulo 1: Entrada
    print("[Orquestador] Buscando facturas...")
    lista_facturas = receptor.buscar_facturas(ruta_entrada)
    print(f"[Orquestador] Se encontraron {len(lista_facturas)} facturas.")
    # logger.info(f"Se encontraron {len(lista_facturas)} facturas para procesar.")

    resultados_finales = []
    fallbacks = obtener_fallbacks()

    for factura_path in lista_facturas:
        print(f"\n--- Procesando factura: {factura_path} ---")
        # logger.info(f"Procesando factura: {factura_path}")

        try:
            # Módulo 2: Preprocesamiento
            print(f"[Orquestador] Preprocesando: {factura_path}...")
            imagen_procesada_path = pdf_processor.procesar_pdf(factura_path)
            print(f"[Orquestador] Preprocesamiento OK -> {imagen_procesada_path}")

            # Módulo 3: Extracción Base (Si es necesario, si no, se salta)
            # print(f"[Orquestador] Extrayendo base (OCR): {imagen_procesada_path}...")
            # datos_ocr = layout_extractor.extraer_base(imagen_procesada_path)
            # print(f"[Orquestador] Extracción Base OK.")

            # Módulo 4: Inferencia del Modelo
            print(f"[Orquestador] Ejecutando inferencia: {imagen_procesada_path}...")
            datos_crudos = model_infer.predecir(imagen_procesada_path)
            print(f"[Orquestador] Inferencia OK. Datos: {datos_crudos}")

            # Módulo 5: Post-procesamiento
            print(f"[Orquestador] Post-procesando datos...")
            datos_limpios = data_cleaner.limpiar_y_validar(datos_crudos, fallbacks, CAMPOS_REQUERIDOS)
            print(f"[Orquestador] Post-procesamiento OK. Datos limpios: {datos_limpios}")

            resultados_finales.append(datos_limpios)
            print(f"--- Factura {factura_path} procesada exitosamente. ---")
            # logger.info(f"Factura {factura_path} procesada exitosamente.")

        except Exception as e:
            print(f"!!! ERROR procesando la factura {factura_path}: {e} !!!")
            # logger.error(f"Error procesando la factura {factura_path}: {e}", exc_info=True)
            # Aquí podríamos añadir el manejo de errores (mover a otra carpeta, etc.)
            resultados_finales.append({"error": str(e), "archivo": factura_path, **obtener_fallbacks()})


    # Módulo 6: Salida
    print("\n--- Generando salida ---")
    output_generator.generar_salida(resultados_finales, ruta_salida, formato_salida)
    print(f"--- Proceso completado. Resultados guardados en: {ruta_salida}.{formato_salida} ---")
    # logger.info(f"Proceso completado. Resultados guardados en: {ruta_salida}")

# Punto de Entrada Principal
if __name__ == "__main__":
    # --- Configuración Básica (Idealmente vendría de config/settings.py) ---
    RUTA_BASE = os.getcwd() # O define una ruta base específica
    RUTA_ENTRADA = os.path.join(RUTA_BASE, "datos", "entrada")
    RUTA_SALIDA = os.path.join(RUTA_BASE, "datos", "salida", "resultados")
    FORMATO_SALIDA = "csv" # Puede ser "csv" o "json"

    # --- Crear Directorios (Si no existen) ---
    os.makedirs(os.path.join(RUTA_BASE, "datos", "entrada"), exist_ok=True)
    os.makedirs(os.path.join(RUTA_BASE, "datos", "salida"), exist_ok=True)
    os.makedirs(os.path.join(RUTA_BASE, "datos", "temp_imagenes"), exist_ok=True) # Para preprocesamiento

    print("**********************************************")
    print("*** INICIANDO BOT DE PROCESAMIENTO V2      ***")
    print("**********************************************")

    # --- Añadir archivos de ejemplo (para probar el flujo) ---
    # En un caso real, los archivos ya existirían o vendrían de otro proceso.
    # Creamos un PDF falso para que `buscar_facturas` encuentre algo.
    try:
        from fpdf import FPDF
        pdf_path_1 = os.path.join(RUTA_ENTRADA, "factura_ejemplo_1.pdf")
        pdf_path_2 = os.path.join(RUTA_ENTRADA, "factura_ejemplo_2.pdf")
        if not os.path.exists(pdf_path_1):
            pdf = FPDF()
            pdf.add_page()
            pdf.set_font("Arial", size = 12)
            pdf.cell(200, 10, txt = "Factura de Prueba 1", ln = True, align = 'C')
            pdf.output(pdf_path_1)
            print(f"Creado PDF de ejemplo: {pdf_path_1}")
        if not os.path.exists(pdf_path_2):
            pdf = FPDF()
            pdf.add_page()
            pdf.set_font("Arial", size = 12)
            pdf.cell(200, 10, txt = "Factura de Prueba 2", ln = True, align = 'C')
            pdf.output(pdf_path_2)
            print(f"Creado PDF de ejemplo: {pdf_path_2}")
    except ImportError:
        print("ADVERTENCIA: fpdf no instalado. No se crearán PDFs de ejemplo.")
        print("             Asegúrate de tener PDFs en 'datos/entrada/' para probar.")


    # --- Ejecutar el Orquestador ---
    ejecutar_proceso_facturas(RUTA_ENTRADA, RUTA_SALIDA, FORMATO_SALIDA)

    print("\n**********************************************")
    print("*** BOT FINALIZADO                         ***")
    print("**********************************************")