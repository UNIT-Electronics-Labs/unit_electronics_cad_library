# Biblioteca electrónica CAD

Este repositorio no publica una web ni modifica los archivos CAD fuente. Al hacer push a `main`, el workflow crea dos recursos para tu API:

- Una rama `assets` con `catalog.json`, los modelos `.glb` en color y vistas `.svg` generadas de símbolos y huellas KiCad.
- Enlaces directos a los archivos originales versionados: STEP, símbolos KiCad (`.kicad_sym`), huellas KiCad (`.kicad_mod`), librerías Eagle (`.lbr`) y SVG que ya existan en el repositorio.

Los archivos fuente no se modifican. Cuando existe un GLB suministrado junto al STEP, el catálogo lo copia a `assets/models/` para mantener sus materiales, colores y enlace estable; de lo contrario, convierte el STEP a GLB con colores de superficie e instancia. El workflow también genera SVG de cada `.kicad_sym` y `.kicad_mod` con `kicad-cli`. Los SVG generados quedan en la rama `assets`.

## Enlace que debes guardar en tu API

Después del primer workflow exitoso, guarda una sola URL permanente:

```text
https://raw.githubusercontent.com/<USUARIO>/<REPOSITORIO>/assets/catalog.json
```

La rama `assets` es un repositorio de archivos generados. El workflow también publica una interfaz para explorar y copiar enlaces en GitHub Pages. Configura una vez **Settings → Pages → Build and deployment → Source → GitHub Actions**; el enlace de la interfaz aparece al terminar el job `deploy-pages`.

El JSON tiene esta forma:

```json
{
  "components": [
    {
      "source_step": { "url": "https://raw.githubusercontent.com/.../archivo.step" },
      "symbols": [{ "url": "https://raw.githubusercontent.com/.../archivo.kicad_sym", "svg_url": "https://raw.githubusercontent.com/.../assets/svg/symbols/archivo.svg" }],
      "footprints": [{ "url": "https://raw.githubusercontent.com/.../archivo.kicad_mod", "svg_url": "https://raw.githubusercontent.com/.../assets/svg/footprints/archivo.svg" }],
      "eagle_libraries": [{ "url": "https://raw.githubusercontent.com/.../archivo.lbr" }],
      "model_glb": { "url": "https://raw.githubusercontent.com/.../assets/models/archivo.glb" }
    }
  ]
}
```

Tu API puede consultar ese JSON y guardar los valores `url`, sin construir ni codificar rutas.

## Publicar cambios

1. Agrega o actualiza los archivos CAD originales dentro de este repositorio.
2. Haz `git add`, `git commit` y `git push` a `main`.
3. El workflow **Publish component assets** actualiza la rama `assets`.

La configuración de Actions del repositorio debe permitir que `GITHUB_TOKEN` tenga permiso de escritura: **Settings → Actions → General → Workflow permissions → Read and write permissions**.

## Uso desde otra aplicación

```js
const manifestUrl =
  "https://raw.githubusercontent.com/<USUARIO>/<REPOSITORIO>/assets/catalog.json";

const catalog = await fetch(manifestUrl).then((response) => response.json());
const component = catalog.components[0];

console.log(component.symbols[0].url);       // .kicad_sym original
console.log(component.footprints[0].url);    // .kicad_mod original
console.log(component.symbols[0].svg_url);   // SVG generado del símbolo
console.log(component.footprints[0].svg_url); // SVG generado de la huella
console.log(component.eagle_libraries[0].url); // .lbr original
console.log(component.model_glb.url);        // GLB de alta calidad
```

## Generación local

```bash
python -m pip install --only-binary=:all: -r requirements.txt
# Instala KiCad 7 o posterior para generar las vistas SVG.
python tools/build_step_catalog.py \
  --input . --output generated-assets \
  --repository <USUARIO>/<REPOSITORIO> --source-ref main
```

El resultado local queda en `generated-assets/catalog.json`, `generated-assets/models/` y `generated-assets/svg/`. Si KiCad no está instalado o un archivo no puede exportarse, el catálogo conserva el archivo fuente y añade `svg_error` en lugar de `svg_url`.
