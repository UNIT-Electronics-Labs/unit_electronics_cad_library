const catalogUrl =
  "https://raw.githubusercontent.com/UNIT-Electronics-Labs/unit_electronics_cad_library/assets/catalog.json";

const catalogElement = document.querySelector("#catalog");
const statusElement = document.querySelector("#status");
const searchElement = document.querySelector("#search");
const openCatalogElement = document.querySelector("#open-catalog");
let components = [];

function link(label, asset) {
  const element = document.createElement("a");
  element.href = asset.url;
  element.target = "_blank";
  element.rel = "noopener";
  element.textContent = label;
  return element;
}

function appendAssets(list, label, assets) {
  for (const asset of assets ?? []) {
    const item = document.createElement("li");
    item.append(link(`${label}: ${asset.name ?? asset.path}`, asset));
    list.append(item);
  }
}

function componentCard(component) {
  const article = document.createElement("article");
  const title = document.createElement("h2");
  title.textContent = component.name ?? component.source_step?.path ?? component.source_lbr?.path;
  const assets = document.createElement("ul");

  if (component.source_lbr) {
    const item = document.createElement("li");
    item.append(link(`Biblioteca Eagle (.lbr): ${component.source_lbr.path}`, component.source_lbr));
    assets.append(item);
  }
  const assetFormat = component.source_lbr ? "Eagle" : "CAD";
  appendAssets(assets, `Símbolo ${assetFormat}`, component.symbols);
  appendAssets(assets, `Huella ${assetFormat}`, component.footprints);
  if (component.source_step) {
    const item = document.createElement("li");
    item.append(link(`Modelo STEP: ${component.source_step.path}`, component.source_step));
    assets.append(item);
  }
  if (component.model_glb) {
    const item = document.createElement("li");
    item.append(link("Modelo GLB", component.model_glb));
    assets.append(item);
  }
  if (component.model_error) {
    const item = document.createElement("li");
    item.textContent = `GLB no disponible: ${component.model_error}`;
    assets.append(item);
  }
  if (!assets.children.length) {
    const item = document.createElement("li");
    item.textContent = "No hay archivos vinculados.";
    assets.append(item);
  }
  article.append(title, assets);
  return article;
}

function matches(component, query) {
  return [component.name, component.source_lbr?.path, component.source_step?.path]
    .filter(Boolean)
    .join(" ")
    .toLowerCase()
    .includes(query);
}

function renderCatalog() {
  const query = searchElement.value.trim().toLowerCase();
  const filtered = components.filter((component) => matches(component, query));
  catalogElement.replaceChildren();
  if (!filtered.length) {
    catalogElement.append(document.querySelector("#empty-template").content.cloneNode(true));
    return;
  }
  filtered.forEach((component) => catalogElement.append(componentCard(component)));
}

async function loadCatalog() {
  try {
    const response = await fetch(catalogUrl);
    if (!response.ok) throw new Error(`No se pudo cargar el catálogo (${response.status})`);
    const catalog = await response.json();
    components = catalog.components ?? [];
    renderCatalog();
    statusElement.textContent = `${components.length} componente(s) publicados · ${catalog.generated_at ?? ""}`;
  } catch (error) {
    statusElement.textContent = "No se pudo cargar el catálogo.";
    catalogElement.textContent = `Error: ${error.message}`;
  }
}

openCatalogElement.href = catalogUrl;
openCatalogElement.target = "_blank";
openCatalogElement.rel = "noopener";
searchElement.addEventListener("input", renderCatalog);
loadCatalog();
