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
import os
import shutil
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote


STEP_EXTENSIONS = {".step", ".stp"}
FOOTPRINT_EXTENSION = ".kicad_mod"


def web_path(path: Path) -> str:
    """Encode a POSIX relative path for use in an HTML URL."""
    return quote(path.as_posix(), safe="/-_.~")


def convert_to_glb(source: Path, target: Path) -> None:
    """Tessellate a STEP solid through CadQuery, preserving STEP part colours."""
    # Keep these imports here so --help and static-site-only operations do not
    # require the large CAD dependencies to be installed.
    import cadquery as cq
    import trimesh
    from OCP.Quantity import Quantity_Color, Quantity_TOC_RGB
    from OCP.STEPCAFControl import STEPCAFControl_Reader
    from OCP.TCollection import TCollection_ExtendedString
    from OCP.TDF import TDF_LabelSequence
    from OCP.TDocStd import TDocStd_Document
    from OCP.TopAbs import TopAbs_SOLID
    from OCP.TopExp import TopExp_Explorer
    from OCP.XCAFDoc import XCAFDoc_ColorType, XCAFDoc_DocumentTool, XCAFDoc_ShapeTool

    document = TDocStd_Document(TCollection_ExtendedString("step-catalog"))
    reader = STEPCAFControl_Reader()
    reader.SetColorMode(True)
    if not reader.ReadFile(str(source)) or not reader.Transfer(document):
        raise ValueError("OpenCascade no pudo leer el STEP")
    shape_tool = XCAFDoc_DocumentTool.ShapeTool_s(document.Main())
    colour_tool = XCAFDoc_DocumentTool.ColorTool_s(document.Main())
    labels = TDF_LabelSequence()
    shape_tool.GetFreeShapes(labels)
    scene = trimesh.Scene()
    with tempfile.TemporaryDirectory(prefix="step-catalog-") as temporary:
        part_number = 0
        for label_index in range(1, labels.Length() + 1):
            root = XCAFDoc_ShapeTool.GetShape_s(labels.Value(label_index))
            solids = TopExp_Explorer(root, TopAbs_SOLID)
            while solids.More():
                solid = solids.Current()
                stl = Path(temporary) / f"part-{part_number}.stl"
                cq.exporters.export(cq.Shape.cast(solid), str(stl), tolerance=0.1, angularTolerance=0.1)
                mesh = trimesh.load_mesh(stl, force="mesh")
                if not mesh.is_empty:
                    colour = Quantity_Color()
                    has_colour = colour_tool.GetColor(solid, XCAFDoc_ColorType.XCAFDoc_ColorSurf, colour)
                    rgb = colour.Values(Quantity_TOC_RGB) if has_colour else (0.70, 0.72, 0.78)
                    rgba = [round(max(0, min(1, channel)) * 255) for channel in rgb] + [255]
                    # Vertex colours avoid an optional SciPy dependency in trimesh.
                    mesh.visual.vertex_colors = [rgba] * len(mesh.vertices)
                    scene.add_geometry(mesh, geom_name=f"part-{part_number}")
                part_number += 1
                solids.Next()
        if not scene.geometry:
            raise ValueError("el archivo STEP no produjo sólidos convertibles")
        target.parent.mkdir(parents=True, exist_ok=True)
        scene.export(target, file_type="glb")


def normalised_name(path: Path) -> str:
    """Make supplier naming variants comparable (MODULE_X, module-x, etc.)."""
    return "".join(character for character in path.stem.upper() if character.isalnum()).removeprefix("MODULE")


def component_footprints(step: Path, footprints: list[Path]) -> list[Path]:
    """Associate explicit name matches first, otherwise use the closest folder."""
    step_name = normalised_name(step)
    named = [footprint for footprint in footprints if normalised_name(footprint) == step_name]
    if named:
        return named

    def shared_depth(footprint: Path) -> int:
        return len(Path(os.path.commonpath((step.parent, footprint.parent))).parts)

    best = max((shared_depth(footprint) for footprint in footprints), default=0)
    return [footprint for footprint in footprints if best and shared_depth(footprint) == best]


def page(records: list[dict[str, object]], generated_at: str) -> str:
    cards = []
    for record in records:
        source = str(record["source"])
        title = html.escape(source)
        download = web_path(Path(str(record["step"])))
        if "model" in record:
            model = web_path(Path(str(record["model"])))
            content = (
                f'<model-viewer src="{model}" alt="Modelo 3D de {title}" '
                "camera-controls touch-action=\"pan-y\" shadow-intensity=\"1\" "
                "exposure=\"0.9\" interaction-prompt=\"auto\"></model-viewer>"
            )
            status = "Listo para explorar"
        else:
            content = '<div class="failed">No se pudo convertir este modelo.</div>'
            status = html.escape(str(record.get("error", "Error de conversión")))
        footprint_links = " ".join(
            f'<a href="{web_path(Path(str(footprint)))}" download>Huella KiCad</a>'
            for footprint in record["footprints"]  # type: ignore[index]
        ) or "<span>Sin huella KiCad asociada</span>"
        cards.append(
            "<article class=\"card\">"
            f"{content}<div class=\"details\"><h2>{title}</h2>"
            f"<p>{status}</p><p class=\"links\"><a href=\"{download}\" download>Descargar STEP</a> {footprint_links}</p>"
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
    .details p {{ min-height: 2.5em; color: #b9c4da; font-size: .9rem; }} a {{ color: #9dcaff; }} .links {{ display: flex; flex-wrap: wrap; gap: .75rem; }}
    footer {{ margin-top: 2rem; color: #8e9ab2; font-size: .85rem; }}
  </style>
</head>
<body><main>
  <header><h1>Catálogo CAD</h1><p>Modelos STEP en color, con sus huellas KiCad y enlaces reutilizables.</p></header>
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
    footprint_files = sorted(
        path for path in source_root.rglob("*")
        if path.is_file() and path.suffix.lower() == FOOTPRINT_EXTENSION and output not in path.parents
    )
    if output.exists():
        shutil.rmtree(output)
    output.mkdir(parents=True)

    footprint_urls: dict[Path, str] = {}
    for footprint in footprint_files:
        relative = footprint.relative_to(source_root)
        destination = output / "footprints" / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(footprint, destination)
        footprint_urls[footprint] = (Path("footprints") / relative).as_posix()

    records: list[dict[str, object]] = []
    for source in step_files:
        relative = source.relative_to(source_root)
        raw = output / "sources" / relative
        raw.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, raw)
        identifier = hashlib.sha256(relative.as_posix().encode()).hexdigest()[:10]
        glb = Path("models") / f"{source.stem}-{identifier}.glb"
        record: dict[str, object] = {
            "source": relative.as_posix(),
            "step": (Path("sources") / relative).as_posix(),
            "footprints": [footprint_urls[footprint] for footprint in component_footprints(source, footprint_files)],
        }
        try:
            convert_to_glb(source, output / glb)
            record["model"] = glb.as_posix()
            print(f"Convertido: {relative}")
        except Exception as error:  # Continue so one bad supplier file does not hide the catalog.
            record["error"] = str(error)
            print(f"No se pudo convertir {relative}: {error}", file=sys.stderr)
        records.append(record)

    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    manifest = {"generated_at": timestamp, "components": records}
    (output / "catalog.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    (output / "models.json").write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")
    (output / "index.html").write_text(page(records, timestamp), encoding="utf-8")
    print(f"Catálogo creado en {output} ({len(records)} archivo(s) STEP)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
