const { Stagehand } = require("stagehand");
const fs = require("fs");

async function runScraper() {
  const brand = process.argv[2];
  const model = process.argv[3];
  const year = process.argv[4];
  const url = process.argv[5];
  const apiKey = process.argv[6];

  // Configuramos la API Key para el proceso de Node
  process.env.GEMINI_API_KEY = apiKey;

  const stagehand = new Stagehand({
    env: "local",
    verbose: 1,
    debugDom: true,
    headless: false, // Para que veas la navegación
    modelName: "gemini-1.5-flash",
    modelProvider: "google"
  });

  try {
    await stagehand.init();
    const page = stagehand.page;

    console.log(`Navegando a ${url}...`);
    await page.goto(url);

    console.log("IA actuando...");
    await stagehand.act(`Buscar autos marca ${brand}, modelo ${model}, año ${year}. Usa los filtros si existen.`);
    
    // Espera para carga
    await new Promise(resolve => setTimeout(resolve, 8000));

    console.log("IA extrayendo datos...");
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

    // Guardamos el resultado en un archivo temporal para que Python lo lea
    fs.writeFileSync("temp_results.json", JSON.stringify(results.autos || []));
    console.log("SUCCESS");

  } catch (error) {
    console.error("ERROR:", error.message);
    process.exit(1);
  } finally {
    await stagehand.close();
  }
}

runScraper();
