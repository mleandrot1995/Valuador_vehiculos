#!/usr/bin/env python3
import os
import sys
from stagehand import Stagehand

# Usamos GEMINI_API_KEY o MODEL_API_KEY
api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("MODEL_API_KEY")

if not api_key:
    print("❌ Error: Configura GEMINI_API_KEY en tu entorno")
    sys.exit(1)

print("🚀 Iniciando Stagehand Local...")

try:
    client = Stagehand(
        server="local",
        model_api_key=api_key,
        local_headless=False, # Esto asegura que veas la ventana
        local_ready_timeout_s=15.0,
    )

    print("🔧 Iniciando sesión...")
    session = client.sessions.start(
        model_name="gemini-2.0-flash", # Usa este nombre que es más estable en el SEA
        browser={
            "type": "local",
            "launchOptions": {},
        },
    )
    session_id = session.data.session_id
    print(f"✅ Sesión iniciada: {session_id}")

    # CORRECCIÓN DE URL
    target_url = "https://www.mercadolibre.com.ar" 
    print(f"\n📍 Navegando a {target_url}...")
    client.sessions.navigate(id=session_id, url=target_url)
    
    # Pausa real para que el sitio termine de cargar scripts internos
    import time
    time.sleep(2) 
    
    print("ejecuto prueba...")
    response = client.sessions.act(
        id=session_id,
        input="ir a autos usados, en donde se tiene que ver todo el marketplace de autos usados y no accesorios de autos, verificar que se ingreso correctamente",
    )
    print(response.data)



    print("🖱️ Interactuando con la página...")
    try:
        # CAMBIO CLAVE: Se usa 'input' en lugar de 'instruction' para .act()
        client.sessions.act(
            id=session_id,
            input="Acepta las cookies si aparece el cartel"
        )

        time.sleep(2) # Esperamos a que la acción se ejecute
    except Exception as e:
        print(f"⚠️ Nota en act: {e}")

    print("🔍 Intentando filtrado...")
    try:
        # Para .extract() el argumento SI suele ser 'instruction'
        print("🔍 Filtrando por marca...")
        result = client.sessions.execute(
            id=session_id,
            input="Realizar el filtrado de la busqueda utilizando los filtros correspondientes de marca (puede estar como lista desplegable)" \
            " y seleccionar o completar con 'Renault', verificar que la selección haya sido aplicada correctamente" 
        )
        print("🔍 Filtrando por modelo...")
        result = client.sessions.execute(
            id=session_id,
            input="Realizar el filtrado de la busqueda utilizando los filtros correspondientes de marca (puede estar como lista desplegable)" \
            "y seleccionar o completar con 'Sandero', verificar que la selección haya sido aplicada correctamente" 
        )
        print("🔍 ejecutar busqueda...")
        result = client.sessions.execute(
            id=session_id,
            input="Verificar si es necesario pulsar algún botón para ejecutar la búsqueda " \
            "y pulsarlo si es así. En caso contrario omitir este paso" 
        )
    except Exception as e:
        print(f"❌ Error en act: {e}")

    print("🔍 Intentando extracción...")
    try:
        # Para .extract() el argumento SI suele ser 'instruction'
        result = client.sessions.extract(
            id=session_id,
            instruction="extraer los encabezados de las publicaciones de autos " \
    "junto con su url o link, y datos relevantes en un " \
    "json, como marca, modelo, año, trasmisión, combustible,precio"
        )
    except Exception as e:
        print(f"❌ Error en extracción: {e}")
    
    print("-" * 30)
    print(f"📄 DATOS EXTRAÍDOS:\n{result.data.result}")
    print("-" * 30)

except Exception as e:
    print(f"\n❌ Error: {e}")
    import traceback
    traceback.print_exc()
finally:
    if 'session_id' in locals():
        client.sessions.end(id=session_id)
    if 'client' in locals():
        client.close()
    print("\n🔌 Proceso finalizado.")