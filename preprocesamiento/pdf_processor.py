import os

def procesar_pdf(factura_path):
    """ Simula la conversión de PDF a imagen. """
    print(f"[Preproc] Procesando: {factura_path}")
    # En un caso real: Usaría pdf2image, poppler, etc.
    nombre_base = os.path.basename(factura_path)
    nombre_img = os.path.splitext(nombre_base)[0] + ".png"
    ruta_img_salida = os.path.join("datos", "temp_imagenes", nombre_img)
    # Simula la creación del archivo de imagen
    with open(ruta_img_salida, 'w') as f:
        f.write(f"Imagen simulada de {nombre_base}")
    print(f"[Preproc] Imagen simulada creada en: {ruta_img_salida}")
    return ruta_img_salida