const { Stagehand } = require("stagehand");
const fs = require("fs");

async function runScraper() {
  const brand = process.argv[2];
  const model = process.argv[3];
  const year = process.argv[4];
  const url = process.argv[5];
  const apiKey = process.argv[6];

  // Configuramos la clave de Gemini para el motor de Stagehand
  process.env.GEMINI_API_KEY = apiKey;

  console.log(`🚀 Iniciando Stagehand para: ${brand} ${model}...`);
  
  const stagehand = new Stagehand({
    env: "local",
    verbose: 1,
    debugDom: false,
    headless: false, // Podrás ver la ventana del navegador
    modelName: "gemini-1.5-flash",
    modelProvider: "google"
  });

  try {
    await stagehand.init();
    const page = stagehand.page;

    console.log(`Navegando a ${url}...`);
    await page.goto(url, { waitUntil: "networkidle" });

    console.log("IA buscando el vehículo...");
    await stagehand.act(`Buscar autos marca ${brand}, modelo ${model}, año ${year}. Usa los filtros del sitio.`);
    
    // Tiempo para que los resultados carguen
    await new Promise(resolve => setTimeout(resolve, 8000));

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
                      }
                  }
              }
          }
      }
    });

    // Guardar resultados para Python
    fs.writeFileSync("temp_results.json", JSON.stringify(results.autos || []));
    console.log("SUCCESS_SCRAPING_DONE");

  } catch (error) {
    console.error("CRITICAL_ERROR:", error.message);
    process.exit(1);
  } finally {
    try { await stagehand.close(); } catch (e) {}
  }
}

runScraper();
