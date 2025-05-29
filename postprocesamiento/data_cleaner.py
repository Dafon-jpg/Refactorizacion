def limpiar_y_validar(datos_crudos, fallbacks, campos_requeridos):
    """ Simula la limpieza, validación y aplicación de fallbacks. """
    print(f"[Postproc] Limpiando datos: {datos_crudos}")
    datos_limpios = {}
    for campo in campos_requeridos:
        valor = datos_crudos.get(campo)
        # Lógica simple: Si no está o está vacío, usa fallback.
        if valor is None or str(valor).strip() == "":
            datos_limpios[campo] = fallbacks.get(campo)
            print(f"[Postproc] Usando fallback para '{campo}': {datos_limpios[campo]}")
        else:
            # Aquí iría la limpieza específica (quitar $, formatear fecha, etc.)
            datos_limpios[campo] = str(valor).strip()
            print(f"[Postproc] Usando valor original para '{campo}': {datos_limpios[campo]}")
            
    # Ejemplo de fusión (si nro = pv-nro)
    if datos_limpios.get("nro") and '-' in datos_limpios["nro"]:
         try:
            pv, nro_solo = datos_limpios["nro"].split('-')
            datos_limpios["pv"] = pv.zfill(4) # Asegura 4 dígitos
            datos_limpios["nro"] = nro_solo.zfill(8) # Asegura 8 dígitos
            print(f"[Postproc] 'nro' dividido en 'pv' y 'nro'.")
         except:
            print(f"[Postproc] WARNING: No se pudo dividir 'nro': {datos_limpios.get('nro')}")


    return datos_limpios