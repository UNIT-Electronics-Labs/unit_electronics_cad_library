const catalogUrl =
  "https://raw.githubusercontent.com/UNIT-Electronics-Labs/unit_electronics_cad_library/assets/catalog.json";

const catalogElement = document.querySelector("#catalog");
const statusElement = document.querySelector("#status");
const searchElement = document.querySelector("#search");
const openCatalogElement = document.querySelector("#open-catalog");
const copyCatalogElement = document.querySelector("#copy-catalog");
let components = [];

function link(label, url, className = "action-link") {
  const element = document.createElement("a");
  element.className = className;
  element.href = url;
  element.target = "_blank";
  element.rel = "noopener";
  element.textContent = label;
  return element;
}

async function copyValue(value) {
  try {
    await navigator.clipboard.writeText(value);
    return true;
  } catch {
    window.prompt("Copia este enlace:", value);
    return false;
  }
}

function copyButton(label, value, className = "action-copy") {
  const button = document.createElement("button");
  button.className = className;
  button.type = "button";
  button.textContent = label;
  button.addEventListener("click", async () => {
    if (await copyValue(value)) {
      button.textContent = "¡Enlace copiado!";
    }
    window.setTimeout(() => { button.textContent = label; }, 1800);
  });
  return button;
}

function actionsFor(url, sourceLabel) {
  const actions = document.createElement("div");
  actions.className = "actions";
  actions.append(link(`Abrir`, url), copyButton(`Copiar ${sourceLabel}`, url));
  return actions;
}

function assetCard(kind, asset) {
  const section = document.createElement("section");
  section.className = "asset";
  const heading = document.createElement("h3");
  heading.textContent = kind;
  const name = document.createElement("p");
  name.className = "asset-name";
  name.textContent = asset.path ?? asset.url;
  section.append(heading, name);

  if (asset.svg_url) {
    const preview = document.createElement("div");
    preview.className = "preview";
    const image = document.createElement("img");
    image.src = asset.svg_url;
    image.alt = `Vista SVG: ${asset.path}`;
    image.loading = "lazy";
    preview.append(image);
    section.append(preview, actionsFor(asset.svg_url, "SVG"));
  }
  section.append(actionsFor(asset.url, "archivo fuente"));
  return section;
}

function componentCard(component, index) {
  const article = document.createElement("article");
  article.className = "component";
  const header = document.createElement("header");
  header.className = "component-header";
  const details = document.createElement("div");
  const componentIndex = document.createElement("span");
  componentIndex.className = "component-index";
  componentIndex.textContent = `Componente ${String(index + 1).padStart(2, "0")}`;
  const title = document.createElement("h2");
  title.className = "component-title";
  title.textContent = component.source_step.path.split("/").at(-1);
  const path = document.createElement("p");
  path.className = "component-path";
  path.textContent = component.source_step.path;
  details.append(componentIndex, title, path);
  const mainActions = actionsFor(component.source_step.url, "STEP");
  mainActions.classList.add("component-main-actions");
  header.append(details, mainActions);

  const assets = document.createElement("div");
  assets.className = "assets";
  for (const symbol of component.symbols ?? []) assets.append(assetCard("Símbolo KiCad", symbol));
  for (const footprint of component.footprints ?? []) assets.append(assetCard("Huella KiCad", footprint));
  if (component.model_glb) assets.append(assetCard("Modelo 3D GLB", component.model_glb));
  article.append(header, assets);
  return article;
}

function renderCatalog() {
  const query = searchElement.value.trim().toLowerCase();
  const filtered = components.filter((component) =>
    component.source_step.path.toLowerCase().includes(query),
  );
  catalogElement.replaceChildren();
  if (!filtered.length) {
    catalogElement.append(document.querySelector("#empty-template").content.cloneNode(true));
    return;
  }
  filtered.forEach((component, index) => catalogElement.append(componentCard(component, index)));
}

async function loadCatalog() {
  try {
    const response = await fetch(catalogUrl);
    if (!response.ok) throw new Error(`No se pudo cargar el catálogo (${response.status})`);
    const catalog = await response.json();
    components = catalog.components ?? [];
    renderCatalog();
    statusElement.textContent = `${components.length} componente(s) · catálogo actualizado ${catalog.generated_at ?? ""}`;
  } catch (error) {
    const message = document.createElement("p");
    message.className = "error";
    message.textContent = `Error al cargar el catálogo: ${error.message}`;
    catalogElement.append(message);
    statusElement.textContent = "No se pudo cargar el catálogo.";
  }
}

openCatalogElement.href = catalogUrl;
openCatalogElement.target = "_blank";
openCatalogElement.rel = "noopener";
copyCatalogElement.addEventListener("click", async () => {
  const label = "Copiar catálogo JSON";
  if (await copyValue(catalogUrl)) copyCatalogElement.textContent = "¡Enlace copiado!";
  window.setTimeout(() => { copyCatalogElement.textContent = label; }, 1800);
});
searchElement.addEventListener("input", renderCatalog);
loadCatalog();
