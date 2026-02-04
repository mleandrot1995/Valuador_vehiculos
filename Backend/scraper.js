const stagehandModule = require("stagehand");
const fs = require("fs");

// Handle different export patterns (CommonJS vs ESM-like)
const Stagehand = stagehandModule.Stagehand || stagehandModule;

async function runScraper() {
  const brand = process.argv[2];
  const model = process.argv[3];
  const year = process.argv[4];
  const url = process.argv[5];
  const apiKey = process.argv[6];

  if (!apiKey || apiKey === "undefined") {
      console.error("ERROR: Gemini API Key is missing.");
      process.exit(1);
  }

  // Configuramos la API Key para el proceso de Node
  process.env.GEMINI_API_KEY = apiKey;

  console.log("Iniciando Stagehand...");
  
  const stagehand = new Stagehand({
    env: "local",
    verbose: 1,
    debugDom: false,
    headless: false, // Para que veas la navegación
    modelName: "gemini-1.5-flash",
    modelProvider: "google"
  });

  try {
    await stagehand.init();
    const page = stagehand.page;

    console.log(`Navegando a ${url}...`);
    await page.goto(url, { waitUntil: "networkidle" });

    console.log(`IA actuando para buscar: ${brand} ${model} ${year}...`);
    await stagehand.act(`Buscar autos marca ${brand}, modelo ${model}, año ${year}. Usa los filtros del sitio si existen.`);
    
    // Espera para que los resultados carguen
    console.log("Esperando resultados...");
    await new Promise(resolve => setTimeout(resolve, 10000));

    console.log("IA extrayendo datos estructurados...");
    const results = await stagehand.extract({
      instruction: "Lista de autos con: brand, model, year (number), km (number), price (number), currency, title",
      schema: {
          type: "object",
          properties: {
              autos: {
                  type: "array",
                  items: {
                      type: "object",
                      properties: {
                          brand: { type: "string" },
                          model: { type: "string" },
                          year: { type: "number" },
                          km: { type: "number" },
                          price: { type: "number" },
                          currency: { type: "string" },
                          title: { type: "string" }
                      },
                      required: ["brand", "model", "price"]
                  }
              }
          }
      }
    });

    const dataToSave = results.autos || [];
    console.log(`Extracción finalizada. Encontrados: ${dataToSave.length} vehículos.`);

    // Guardamos el resultado en un archivo temporal para que Python lo lea
    fs.writeFileSync("temp_results.json", JSON.stringify(dataToSave));
    console.log("SUCCESS_DATA_SAVED");

  } catch (error) {
    console.error("CRITICAL_ERROR:", error.message);
    process.exit(1);
  } finally {
    try {
        await stagehand.close();
    } catch (e) {}
  }
}

runScraper();
