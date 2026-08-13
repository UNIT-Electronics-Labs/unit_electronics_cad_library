# Biblioteca electrónica CAD

Cada archivo `.step` o `.stp` se publica automáticamente como un modelo 3D interactivo **en color** en GitHub Pages. Cada tarjeta contiene además una vista SVG del **símbolo** `.kicad_sym` y de la **huella PCB** `.kicad_mod`, junto con sus archivos descargables.

## Cómo publicar un componente

1. Guarda el STEP dentro de una carpeta con el nombre del componente, por ejemplo `arduino_nano/arduino-nano.step`.
2. Haz `git add`, `git commit` y `git push` a `main`.
3. El workflow **Publicar catálogo STEP** convierte los modelos a GLB y actualiza la página.

En GitHub, configura **Settings → Pages → Build and deployment → Source** como **GitHub Actions** la primera vez. El enlace publicado aparece al terminar el job `deploy`.

Los STEP originales se conservan en el repositorio y también se ofrecen como descarga desde el catálogo. Los GLB y la carpeta `site/` son artefactos generados: no hace falta versionarlos.

## Usarlo desde otra página web

El catálogo publica `catalog.json`, un manifiesto de enlaces relativos. Cada elemento de `components` contiene:

- `model`: GLB con los colores presentes en el STEP, para un visor 3D como `<model-viewer>` o Three.js.
- `step`: enlace descargable al archivo STEP fuente.
- `symbols`: lista de símbolos con `file` (fuente `.kicad_sym`) y `render` (vista SVG).
- `footprints`: lista de huellas con `file` (fuente `.kicad_mod`) y `render` (vista SVG).

Por ejemplo, desde otra web puedes solicitar `https://<usuario>.github.io/<repositorio>/catalog.json`. Para formar una URL correcta incluso con espacios en el nombre, usa `new URL(component.model, baseUrl)` y `new URL(component.footprints[0], baseUrl)`, donde `baseUrl` es `https://<usuario>.github.io/<repositorio>/`. Las rutas se mantienen estables mientras no cambie el nombre ni la carpeta del archivo fuente.

## Probar el catálogo localmente

Requiere Python 3.11 o compatible y dependencias CAD:

```bash
python -m pip install --only-binary=:all: -r requirements.txt
python tools/build_step_catalog.py --input . --output site
python -m http.server --directory site 8000
```

Después abre `http://localhost:8000`. El navegador no interpreta STEP directamente; el workflow lo tesela a GLB, que sí puede mostrarse en una web.
