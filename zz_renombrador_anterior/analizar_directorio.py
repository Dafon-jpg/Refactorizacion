#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Script para analizar múltiples PDFs en un directorio.
Extrae información de todas las facturas PDF en un directorio y genera
un reporte CSV con los resultados.
Versión sin emojis para evitar problemas de codificación en Windows.
"""

import os
import sys
import csv
import argparse
from test_extraccion import extraer_info_pdf

def analizar_directorio(directorio, csv_salida=None):
    """Analiza todos los PDFs en un directorio y genera un reporte CSV."""
    # Verificar que el directorio existe
    if not os.path.exists(directorio):
        print(f"Error: El directorio {directorio} no existe")
        return
    
    # Obtener lista de PDFs
    pdfs = [f for f in os.listdir(directorio) if f.lower().endswith(".pdf")]
    
    if not pdfs:
        print(f"No se encontraron archivos PDF en {directorio}")
        return
    
    print(f"Se encontraron {len(pdfs)} archivos PDF en {directorio}\n")
    
    # Preparar CSV de salida
    if not csv_salida:
        csv_salida = os.path.join(directorio, "analisis_facturas.csv")
    
    # Campos para el CSV
    campos = [
        "nombre_archivo", "cuit_pre", "codigo_cbte", "pv", "nro", 
        "fecha_cbte", "tipo_emision", "nro_cae", "importe", 
        "periodo", "actividad", "cantidad", "dep", "estado"
    ]
    
    # Procesar cada PDF
    resultados = []
    
    for i, pdf in enumerate(pdfs, 1):
        print(f"[{i}/{len(pdfs)}] Procesando: {pdf}")
        ruta_completa = os.path.join(directorio, pdf)
        
        try:
            info = extraer_info_pdf(ruta_completa)
            
            # Verificar datos críticos
            campos_criticos = ["cuit_pre", "codigo_cbte", "pv", "nro", "fecha_cbte"]
            faltantes = [c for c in campos_criticos if c not in info or not info[c]]
            
            if faltantes:
                estado = f"Incompleto (faltan: {', '.join(faltantes)})"
            else:
                estado = "OK"
            
            # Agregar estado y nombre de archivo
            info["estado"] = estado
            info["nombre_archivo"] = pdf
            
            resultados.append(info)
            
        except Exception as e:
            print(f"Error al procesar {pdf}: {e}")
            # Agregar registro de error
            resultados.append({
                "nombre_archivo": pdf,
                "estado": f"Error: {str(e)}",
                "cuit_pre": "", "codigo_cbte": "", "pv": "", "nro": "", 
                "fecha_cbte": "", "tipo_emision": "", "nro_cae": "", "importe": "", 
                "periodo": "", "actividad": "", "cantidad": "", "dep": ""
            })
    
    # Guardar resultados en CSV
    with open(csv_salida, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=campos)
        writer.writeheader()
        for r in resultados:
            # Asegurar que todos los campos existen
            fila = {campo: r.get(campo, "") for campo in campos}
            writer.writerow(fila)
    
    # Resumen
    ok_count = sum(1 for r in resultados if r.get("estado") == "OK")
    print(f"\n===== RESUMEN =====")
    print(f"Total PDFs: {len(pdfs)}")
    print(f"Procesados correctamente: {ok_count}")
    print(f"Con errores o incompletos: {len(pdfs) - ok_count}")
    print(f"Reporte guardado en: {csv_salida}")

def main():
    """Función principal."""
    parser = argparse.ArgumentParser(description="Analiza PDFs de facturas en un directorio")
    parser.add_argument("directorio", help="Directorio con archivos PDF a analizar")
    parser.add_argument("-o", "--output", help="Archivo CSV de salida", default=None)
    
    args = parser.parse_args()
    
    analizar_directorio(args.directorio, args.output)

if __name__ == "__main__":
    main()