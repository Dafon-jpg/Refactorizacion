import csv
import json
import os

def generar_salida(resultados, ruta_salida_base, formato='csv'):
    """ Genera el archivo de salida (CSV o JSON). """
    ruta_completa = f"{ruta_salida_base}.{formato}"
    print(f"[Salida] Generando archivo: {ruta_completa}")

    if not resultados:
        print("[Salida] No hay resultados para guardar.")
        return

    # Asegurarse de que el directorio de salida exista
    os.makedirs(os.path.dirname(ruta_salida_base), exist_ok=True)

    # Obtener todas las claves posibles de todos los diccionarios
    headers = list(resultados[0].keys())
    for res in resultados:
        for key in res.keys():
            if key not in headers:
                headers.append(key)

    if formato == 'csv':
        try:
            with open(ruta_completa, 'w', newline='', encoding='utf-8') as f:
                writer = csv.DictWriter(f, fieldnames=headers, extrasaction='ignore') # Ignora claves extras si las hubiera
                writer.writeheader()
                writer.writerows(resultados)
            print(f"[Salida] Archivo CSV generado exitosamente.")
        except IOError as e:
            print(f"[Salida] ERROR al escribir CSV: {e}")

    elif formato == 'json':
        try:
            with open(ruta_completa, 'w', encoding='utf-8') as f:
                json.dump(resultados, f, indent=4, ensure_ascii=False)
            print(f"[Salida] Archivo JSON generado exitosamente.")
        except IOError as e:
            print(f"[Salida] ERROR al escribir JSON: {e}")
    else:
        print(f"[Salida] ERROR: Formato '{formato}' no soportado.")