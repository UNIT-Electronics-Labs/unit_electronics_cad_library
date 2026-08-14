# Biblioteca electrónica CAD

Este repositorio publica una página HTML sencilla de enlaces y no modifica los archivos CAD fuente. Al hacer push a `main`, el workflow crea dos recursos para tu API:

- Una rama `assets` con `catalog.json`, los modelos `.glb` en color y vistas `.svg` generadas de símbolos y huellas KiCad.
- Enlaces directos a los archivos originales versionados: STEP, símbolos KiCad (`.kicad_sym`), huellas KiCad (`.kicad_mod`), librerías Eagle (`.lbr`) y SVG que ya existan en el repositorio.
- Para cada `.lbr`, bibliotecas Eagle mínimas de cada símbolo y de cada `package` (huella), agrupadas según sus `devicesets`. Si un STEP tiene el mismo nombre que el componente, también queda vinculado con su GLB.

Los archivos fuente no se modifican. Cuando existe un GLB suministrado junto al STEP, el catálogo lo copia a `assets/models/` para mantener sus materiales, colores y enlace estable; de lo contrario, convierte el STEP a GLB con colores de superficie e instancia. El workflow también genera SVG de cada `.kicad_sym` y `.kicad_mod` con `kicad-cli`. Los SVG generados quedan en la rama `assets`.

## Enlace que debes guardar en tu API

Después del primer workflow exitoso, guarda una sola URL permanente:

```text
https://raw.githubusercontent.com/<USUARIO>/<REPOSITORIO>/assets/catalog.json
```

La rama `assets` es un repositorio de archivos generados. El workflow también publica una interfaz para explorar y copiar enlaces en GitHub Pages. Configura una vez **Settings → Pages → Build and deployment → Source → GitHub Actions**; el enlace de la interfaz aparece al terminar el job `deploy-pages`.

El JSON tiene esta forma (los componentes Eagle usan `source_lbr`):

```json
{
  "components": [
    {
      "name": "Nombre del deviceset Eagle",
      "source_lbr": { "url": "https://raw.githubusercontent.com/.../archivo.lbr" },
      "symbols": [{ "name": "Símbolo", "url": "https://raw.githubusercontent.com/.../assets/eagle/symbols/simbolo.lbr" }],
      "footprints": [{ "name": "Huella", "url": "https://raw.githubusercontent.com/.../assets/eagle/footprints/huella.lbr" }],
      "source_step": { "url": "https://raw.githubusercontent.com/.../archivo.step" },
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

console.log(component.source_lbr.url);        // .lbr original
console.log(component.symbols[0].url);        // biblioteca Eagle mínima del símbolo
console.log(component.footprints[0].url);     // biblioteca Eagle mínima de la huella
console.log(component.source_step?.url);      // STEP asociado si existe
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

El resultado local queda en `generated-assets/catalog.json`, `generated-assets/eagle/`, `generated-assets/models/` y `generated-assets/svg/`. Un `.lbr` contiene símbolos y huellas, pero no contiene un STEP ni un GLB: el generador solo los vincula si encuentra un STEP con el mismo nombre en el repositorio, y convierte o copia su GLB como antes.
