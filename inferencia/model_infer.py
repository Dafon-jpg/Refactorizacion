def predecir(imagen_path):
    """ Simula la predicción del modelo LayoutLMv3. """
    print(f"[Inferencia] Prediciendo con modelo en: {imagen_path}")
    # En un caso real: Cargar modelo, tokenizador, procesador y ejecutar.
    # Devolvemos datos crudos de ejemplo
    return {
        "cuit_pre": "30-12345678-9",
        "nro": "0001-00001234",
        "importe": "1500.75",
        "fecha_cbte": "2025-05-23",
        # Faltan campos para probar fallbacks
    }