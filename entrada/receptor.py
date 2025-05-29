import os
import glob

def buscar_facturas(ruta_entrada):
    """ Busca archivos PDF en la ruta de entrada. """
    print(f"[Entrada] Buscando PDFs en: {ruta_entrada}")
    patron_busqueda = os.path.join(ruta_entrada, "*.pdf")
    facturas = glob.glob(patron_busqueda)
    print(f"[Entrada] Encontrados: {facturas}")
    return facturas