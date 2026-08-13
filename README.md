# Biblioteca electrónica CAD

Cada archivo `.step` o `.stp` se publica automáticamente como un modelo 3D interactivo en GitHub Pages.

## Cómo publicar un componente

1. Guarda el STEP dentro de una carpeta con el nombre del componente, por ejemplo `arduino_nano/arduino-nano.step`.
2. Haz `git add`, `git commit` y `git push` a `main`.
3. El workflow **Publicar catálogo STEP** convierte los modelos a GLB y actualiza la página.

En GitHub, configura **Settings → Pages → Build and deployment → Source** como **GitHub Actions** la primera vez. El enlace publicado aparece al terminar el job `deploy`.

Los STEP originales se conservan en el repositorio y también se ofrecen como descarga desde el catálogo. Los GLB y la carpeta `site/` son artefactos generados: no hace falta versionarlos.

## Probar el catálogo localmente

Requiere Python 3.11 o compatible y dependencias CAD:

```bash
python -m pip install --only-binary=:all: cadquery==2.5.2 trimesh==4.4.9
python tools/build_step_catalog.py --input . --output site
python -m http.server --directory site 8000
```

Después abre `http://localhost:8000`. El navegador no interpreta STEP directamente; el workflow lo tesela a GLB, que sí puede mostrarse en una web.
