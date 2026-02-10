#!/usr/bin/env python3
import os
import sys
from stagehand import Stagehand

# Usamos GEMINI_API_KEY o MODEL_API_KEY
api_key = model_name = os.environ.get("MODEL_API_KEY")
model_name = os.environ.get("STAGEHAND_MODEL", "google/gemini-3-flash-preview")

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
        model_name=model_name, # Usa este nombre que es más estable en el SEA
        browser={
            "type": "local",
            "launchOptions": {},
        },
    )
    session_id = session.data.session_id
    print(f"✅ Sesión iniciada: {session_id}")

    # CORRECCIÓN DE URL
    target_url = "https://www.kavak.com" 
    print(f"\n📍 Navegando a {target_url}...")
    client.sessions.navigate(id=session_id, url=target_url)
    
    # Pausa real para que el sitio termine de cargar scripts internos
    import time
    time.sleep(2) 
    
    print("ejecuto prueba...")
    #response = client.sessions.act(
    #    id=session_id,
    #    input="ir a autos usados, en donde se tiene que ver todo el marketplace de autos usados " \
    #    "y no accesorios de autos, verificar que se ingreso correctamente"
    #    )
    #print(response.data)

    response = client.sessions.execute(
            id=session_id,
            execute_options={
                "instruction": "Acepta cookies si aparecen. Asegúrate de estar en la sección de compra de autos usados (Marketplace). "
                "Si estás en la home, busca el botón 'Comprar un auto'. "
                "Una vez allí, verificar si se observan los filtros de búsqueda, en caso de que no se hallen hacer clic en la barra de búsqueda (entry point) para ver filtros si corresponde CASO CONTRARIO NO HACER NADA. "
                "Aplica los filtros: Marca 'Renault' y Modelo 'Sandero'. "
                "Confirma que los filtros se aplicaron viendo los resultados en pantalla.",
                "max_steps": 20,
            },
            agent_config={
                "model": {"model_name": model_name},
            },
        )
    print(response.data)

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