#!/usr/bin/env python3
"""Create a static, browser-viewable catalog from STEP files.

The script deliberately keeps the source files separate from the generated
site.  This makes it safe to run locally and from GitHub Actions.
"""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import shutil
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote


STEP_EXTENSIONS = {".step", ".stp"}


def web_path(path: Path) -> str:
    """Encode a POSIX relative path for use in an HTML URL."""
    return quote(path.as_posix(), safe="/-_.~")


def convert_to_glb(source: Path, target: Path) -> None:
    """Tessellate a STEP solid through CadQuery, then package it as glTF."""
    # Keep these imports here so --help and static-site-only operations do not
    # require the large CAD dependencies to be installed.
    import cadquery as cq
    import trimesh

    with tempfile.TemporaryDirectory(prefix="step-catalog-") as temporary:
        stl = Path(temporary) / "model.stl"
        model = cq.importers.importStep(str(source))
        cq.exporters.export(model, str(stl), tolerance=0.1, angularTolerance=0.1)
        mesh = trimesh.load_mesh(stl, force="mesh")
        if mesh.is_empty:
            raise ValueError("el archivo STEP no produjo una malla")
        mesh.remove_unreferenced_vertices()
        target.parent.mkdir(parents=True, exist_ok=True)
        mesh.export(target, file_type="glb")


def page(records: list[dict[str, str]], generated_at: str) -> str:
    cards = []
    for record in records:
        title = html.escape(record["source"])
        download = web_path(Path("sources") / Path(record["source"]))
        if "model" in record:
            model = web_path(Path(record["model"]))
            content = (
                f'<model-viewer src="{model}" alt="Modelo 3D de {title}" '
                "camera-controls touch-action=\"pan-y\" shadow-intensity=\"1\" "
                "exposure=\"0.9\" interaction-prompt=\"auto\"></model-viewer>"
            )
            status = "Listo para explorar"
        else:
            content = '<div class="failed">No se pudo convertir este modelo.</div>'
            status = html.escape(record.get("error", "Error de conversión"))
        cards.append(
            "<article class=\"card\">"
            f"{content}<div class=\"details\"><h2>{title}</h2>"
            f"<p>{status}</p><a href=\"{download}\" download>Descargar STEP</a>"
            "</div></article>"
        )

    empty = "<p>No se encontraron archivos .step o .stp.</p>" if not cards else ""
    return f"""<!doctype html>
<html lang="es">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Catálogo CAD</title>
  <script type="module" src="https://unpkg.com/@google/model-viewer/dist/model-viewer.min.js"></script>
  <style>
    :root {{ color-scheme: dark; font-family: Inter, system-ui, sans-serif; background: #10131a; color: #eef2ff; }}
    body {{ margin: 0; }} main {{ max-width: 1200px; margin: auto; padding: 2rem; }}
    header {{ margin-bottom: 2rem; }} h1 {{ margin-bottom: .25rem; }} header p {{ color: #aeb9d0; }}
    .grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(290px, 1fr)); gap: 1.25rem; }}
    .card {{ overflow: hidden; border: 1px solid #2c3548; border-radius: .9rem; background: #181d28; }}
    model-viewer, .failed {{ display: block; width: 100%; height: 290px; background: radial-gradient(circle at 50% 35%, #39455d, #151923 65%); }}
    .failed {{ display: grid; place-items: center; color: #ffb4ab; padding: 1rem; box-sizing: border-box; }}
    .details {{ padding: 1rem; }} h2 {{ overflow-wrap: anywhere; font-size: 1rem; margin: 0 0 .5rem; }}
    .details p {{ min-height: 2.5em; color: #b9c4da; font-size: .9rem; }} a {{ color: #9dcaff; }}
    footer {{ margin-top: 2rem; color: #8e9ab2; font-size: .85rem; }}
  </style>
</head>
<body><main>
  <header><h1>Catálogo CAD</h1><p>Modelos STEP convertidos para visualización web.</p></header>
  {empty}<section class="grid">{''.join(cards)}</section>
  <footer>Generado {html.escape(generated_at)}</footer>
</main></body></html>"""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=Path("."), help="directorio que contiene los STEP")
    parser.add_argument("--output", type=Path, default=Path("site"), help="directorio del sitio generado")
    arguments = parser.parse_args()
    source_root = arguments.input.resolve()
    output = arguments.output.resolve()
    if output == source_root:
        parser.error("--output debe ser un subdirectorio distinto de --input")

    # Avoid treating prior site output as source material when output is inside input.
    step_files = sorted(
        path for path in source_root.rglob("*")
        if path.is_file() and path.suffix.lower() in STEP_EXTENSIONS and output not in path.parents
    )
    if output.exists():
        shutil.rmtree(output)
    output.mkdir(parents=True)

    records: list[dict[str, str]] = []
    for source in step_files:
        relative = source.relative_to(source_root)
        raw = output / "sources" / relative
        raw.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, raw)
        identifier = hashlib.sha256(relative.as_posix().encode()).hexdigest()[:10]
        glb = Path("models") / f"{source.stem}-{identifier}.glb"
        record: dict[str, str] = {"source": relative.as_posix()}
        try:
            convert_to_glb(source, output / glb)
            record["model"] = glb.as_posix()
            print(f"Convertido: {relative}")
        except Exception as error:  # Continue so one bad supplier file does not hide the catalog.
            record["error"] = str(error)
            print(f"No se pudo convertir {relative}: {error}", file=sys.stderr)
        records.append(record)

    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    (output / "models.json").write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")
    (output / "index.html").write_text(page(records, timestamp), encoding="utf-8")
    print(f"Catálogo creado en {output} ({len(records)} archivo(s) STEP)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
