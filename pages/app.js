const catalogUrl =
  "https://raw.githubusercontent.com/UNIT-Electronics-Labs/unit_electronics_cad_library/assets/catalog.json";

const catalogElement = document.querySelector("#catalog");
const statusElement = document.querySelector("#status");

function link(label, url) {
  const element = document.createElement("a");
  element.href = url;
  element.target = "_blank";
  element.rel = "noopener";
  element.textContent = label;
  return element;
}

function copyButton(label, value) {
  const button = document.createElement("button");
  button.type = "button";
  button.textContent = label;
  button.addEventListener("click", async () => {
    try {
      await navigator.clipboard.writeText(value);
      button.textContent = "¡Enlace copiado!";
    } catch {
      window.prompt("Copia este enlace:", value);
    }
    window.setTimeout(() => { button.textContent = label; }, 1800);
  });
  return button;
}

function actionsFor(url, sourceLabel) {
  const actions = document.createElement("div");
  actions.className = "actions";
  actions.append(link(`Abrir ${sourceLabel}`, url), copyButton(`Copiar ${sourceLabel}`, url));
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

function componentCard(component) {
  const article = document.createElement("article");
  article.className = "component";
  const header = document.createElement("header");
  const title = document.createElement("h2");
  title.textContent = component.source_step.path;
  header.append(title, actionsFor(component.source_step.url, "STEP"));

  const assets = document.createElement("div");
  assets.className = "assets";
  for (const symbol of component.symbols ?? []) assets.append(assetCard("Símbolo KiCad", symbol));
  for (const footprint of component.footprints ?? []) assets.append(assetCard("Huella KiCad", footprint));
  if (component.model_glb) assets.append(assetCard("Modelo 3D GLB", component.model_glb));
  article.append(header, assets);
  return article;
}

async function loadCatalog() {
  try {
    const response = await fetch(catalogUrl);
    if (!response.ok) throw new Error(`No se pudo cargar el catálogo (${response.status})`);
    const catalog = await response.json();
    const components = catalog.components ?? [];
    if (!components.length) {
      catalogElement.append(document.querySelector("#empty-template").content.cloneNode(true));
    } else {
      components.forEach((component) => catalogElement.append(componentCard(component)));
    }
    statusElement.textContent = `${components.length} componente(s) · catálogo actualizado ${catalog.generated_at ?? ""}`;
  } catch (error) {
    const message = document.createElement("p");
    message.className = "error";
    message.textContent = `Error al cargar el catálogo: ${error.message}`;
    catalogElement.append(message);
    statusElement.textContent = "No se pudo cargar el catálogo.";
  }
}

loadCatalog();
