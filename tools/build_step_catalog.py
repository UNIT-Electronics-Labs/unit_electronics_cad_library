#!/usr/bin/env python3
"""Build a machine-readable component manifest and high-quality GLB assets.

Source CAD files are never changed. The manifest links directly to each
versioned source; STEP files are tessellated to GLB, KiCad assets are rendered
to SVG, and Eagle symbols and footprints are rendered to PNG previews.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

from PIL import Image, ImageDraw, ImageFont


STEP_EXTENSIONS = {".step", ".stp"}
SOURCE_EXTENSIONS = {".kicad_sym", ".kicad_mod", ".lbr", ".svg", ".glb", ".f3d", ".f3z"}


def raw_url(repository: str, ref: str, relative_path: Path) -> str:
    """Create a raw GitHub URL without altering the source file or its path."""
    encoded_path = quote(relative_path.as_posix(), safe="/-_.~")
    return f"https://raw.githubusercontent.com/{repository}/{ref}/{encoded_path}"


def normalised_name(path: Path | str) -> str:
    """Make supplier naming variants comparable (MODULE_X, module-x, etc.)."""
    name = path.stem if isinstance(path, Path) else path
    return "".join(character for character in name.upper() if character.isalnum()).removeprefix("MODULE")


def associated_assets(step: Path, assets: list[Path], source_root: Path) -> list[Path]:
    """Associate matching names first; otherwise use the STEP's own folder."""
    named = [asset for asset in assets if normalised_name(asset) == normalised_name(step)]
    if named:
        return named
    return [asset for asset in assets if asset.parent == step.parent]


def run_kicad(command: list[str]) -> Path:
    """Run KiCad's SVG exporter and return its generated SVG file."""
    if not shutil.which("kicad-cli"):
        raise RuntimeError("kicad-cli no está instalado")
    result = subprocess.run(command, text=True, capture_output=True)
    if result.returncode:
        message = result.stderr.strip() or result.stdout.strip() or "KiCad no pudo crear el SVG"
        raise RuntimeError(message)
    output = Path(command[command.index("--output") + 1])
    svg_files = sorted(output.rglob("*.svg"))
    if not svg_files:
        raise RuntimeError("KiCad terminó sin generar un SVG")
    return svg_files[0]


def render_symbol_svg(source: Path, target: Path) -> None:
    """Generate an SVG alongside the original .kicad_sym, without modifying it."""
    with tempfile.TemporaryDirectory(prefix="symbol-svg-") as temporary:
        generated = Path(temporary) / "generated"
        generated.mkdir()
        svg = run_kicad(["kicad-cli", "sym", "export", "svg", "--output", str(generated), str(source)])
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(svg, target)


def render_footprint_svg(source: Path, target: Path) -> None:
    """Generate an SVG alongside the original .kicad_mod, without modifying it."""
    with tempfile.TemporaryDirectory(prefix="footprint-svg-") as temporary:
        library = Path(temporary) / "component.pretty"
        generated = Path(temporary) / "generated"
        library.mkdir()
        generated.mkdir()
        shutil.copy2(source, library / source.name)
        svg = run_kicad(["kicad-cli", "fp", "export", "svg", "--output", str(generated), str(library)])
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(svg, target)


def convert_to_glb(source: Path, target: Path, linear_tolerance: float, angular_tolerance: float) -> None:
    """Tessellate a coloured STEP assembly into GLB at the requested quality."""
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

    document = TDocStd_Document(TCollection_ExtendedString("component-assets"))
    reader = STEPCAFControl_Reader()
    reader.SetColorMode(True)
    if not reader.ReadFile(str(source)) or not reader.Transfer(document):
        raise ValueError("OpenCascade no pudo leer el STEP")

    shape_tool = XCAFDoc_DocumentTool.ShapeTool_s(document.Main())
    colour_tool = XCAFDoc_DocumentTool.ColorTool_s(document.Main())
    labels = TDF_LabelSequence()
    shape_tool.GetFreeShapes(labels)
    scene = trimesh.Scene()

    def surface_colour(solid: object) -> tuple[int, int, int, int]:
        """Resolve STEP/XDE surface styles, including per-instance overrides."""
        for lookup in (colour_tool.GetInstanceColor, colour_tool.GetColor):
            for colour_type in (
                XCAFDoc_ColorType.XCAFDoc_ColorSurf,
                XCAFDoc_ColorType.XCAFDoc_ColorGen,
                XCAFDoc_ColorType.XCAFDoc_ColorCurv,
            ):
                colour = Quantity_Color()
                if lookup(solid, colour_type, colour):
                    rgb = colour.Values(Quantity_TOC_RGB)
                    return tuple(round(max(0, min(1, channel)) * 255) for channel in rgb) + (255,)
        return (179, 184, 199, 255)

    with tempfile.TemporaryDirectory(prefix="component-assets-") as temporary:
        part_number = 0
        for label_index in range(1, labels.Length() + 1):
            root = XCAFDoc_ShapeTool.GetShape_s(labels.Value(label_index))
            solids = TopExp_Explorer(root, TopAbs_SOLID)
            while solids.More():
                solid = solids.Current()
                stl = Path(temporary) / f"part-{part_number}.stl"
                cq.exporters.export(
                    cq.Shape.cast(solid),
                    str(stl),
                    tolerance=linear_tolerance,
                    angularTolerance=angular_tolerance,
                )
                mesh = trimesh.load_mesh(stl, force="mesh")
                if not mesh.is_empty:
                    rgba = surface_colour(solid)
                    mesh.visual.material = trimesh.visual.material.PBRMaterial(
                        baseColorFactor=rgba,
                        metallicFactor=0.0,
                        roughnessFactor=0.72,
                    )
                    scene.add_geometry(mesh, geom_name=f"part-{part_number}")
                part_number += 1
                solids.Next()

    if not scene.geometry:
        raise ValueError("el archivo STEP no produjo sólidos convertibles")
    target.parent.mkdir(parents=True, exist_ok=True)
    scene.export(target, file_type="glb")


def asset_link(path: Path, source_root: Path, repository: str, source_ref: str) -> dict[str, str]:
    relative = path.relative_to(source_root)
    return {"path": relative.as_posix(), "url": raw_url(repository, source_ref, relative)}


def generated_link(path: Path, repository: str, assets_ref: str, **metadata: object) -> dict[str, object]:
    """Build a link to a file written to the generated-assets branch."""
    result = {"path": path.as_posix(), "url": raw_url(repository, assets_ref, path)}
    result.update(metadata)
    return result


def safe_file_stem(value: str) -> str:
    """Return a portable, readable filename fragment for an Eagle object name."""
    cleaned = "".join(character if character.isalnum() else "-" for character in value).strip("-")
    return cleaned or "unnamed"


def write_eagle_fragment(root: ET.Element, section_name: str, element: ET.Element, target: Path) -> None:
    """Write one package or symbol as a small, valid Eagle library file."""
    source_drawing = root.find("./drawing")
    if source_drawing is None:
        raise ValueError("la biblioteca Eagle no contiene drawing")
    fragment_root = ET.Element("eagle", root.attrib)
    drawing = ET.SubElement(fragment_root, "drawing")
    for section in ("settings", "grid", "layers"):
        source_section = source_drawing.find(section)
        if source_section is not None:
            drawing.append(copy.deepcopy(source_section))
    library = ET.SubElement(drawing, "library")
    container = ET.SubElement(library, section_name)
    container.append(copy.deepcopy(element))
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(b'<?xml version="1.0" encoding="utf-8"?>\n' + ET.tostring(fragment_root, encoding="utf-8"))


def eagle_number(element: ET.Element, attribute: str, default: float = 0.0) -> float:
    """Read an Eagle numeric attribute, accepting absent optional values."""
    try:
        return float(element.get(attribute, default))
    except ValueError:
        return default


def eagle_bounds(element: ET.Element) -> tuple[float, float, float, float]:
    """Estimate the drawing bounds of an Eagle package or symbol in millimetres."""
    points: list[tuple[float, float]] = []

    def add(x: float, y: float, radius: float = 0) -> None:
        points.extend(((x - radius, y - radius), (x + radius, y + radius)))

    for item in element.iter():
        tag = item.tag
        if tag == "wire":
            add(eagle_number(item, "x1"), eagle_number(item, "y1"), eagle_number(item, "width") / 2)
            add(eagle_number(item, "x2"), eagle_number(item, "y2"), eagle_number(item, "width") / 2)
        elif tag in {"circle", "pad", "hole"}:
            radius = eagle_number(item, "radius")
            if tag == "pad":
                radius = max(radius, eagle_number(item, "diameter", eagle_number(item, "drill") * 1.8) / 2)
            if tag == "hole":
                radius = eagle_number(item, "drill") / 2
            add(eagle_number(item, "x"), eagle_number(item, "y"), radius)
        elif tag == "smd":
            add(eagle_number(item, "x"), eagle_number(item, "y"), max(eagle_number(item, "dx"), eagle_number(item, "dy")) / 2)
        elif tag == "rectangle":
            add(eagle_number(item, "x1"), eagle_number(item, "y1"))
            add(eagle_number(item, "x2"), eagle_number(item, "y2"))
        elif tag in {"vertex", "text"}:
            add(eagle_number(item, "x"), eagle_number(item, "y"))
        elif tag == "pin":
            x, y = eagle_number(item, "x"), eagle_number(item, "y")
            length = {"point": 0, "short": 2.54, "middle": 5.08, "long": 7.62}.get(item.get("length", "middle"), 5.08)
            direction = item.get("rot", "R0")[1:]
            dx, dy = {"0": (length, 0), "90": (0, length), "180": (-length, 0), "270": (0, -length)}.get(direction, (length, 0))
            add(x, y)
            add(x + dx, y + dy)
    if not points:
        return (-5, -5, 5, 5)
    xs, ys = zip(*points)
    return min(xs), min(ys), max(xs), max(ys)


def render_eagle_png(element: ET.Element, target: Path) -> None:
    """Render an Eagle preview in a schematic/PCB style similar to SnapEDA."""
    min_x, min_y, max_x, max_y = eagle_bounds(element)
    margin_mm = 1.5
    width_mm = max(max_x - min_x + margin_mm * 2, 4)
    height_mm = max(max_y - min_y + margin_mm * 2, 4)
    scale = min(36, 960 / max(width_mm, height_mm))
    width = max(160, round(width_mm * scale))
    height = max(160, round(height_mm * scale))
    is_symbol = element.tag == "symbol"
    background = "#ffffff" if is_symbol else "#050505"
    foreground = "#1f2937" if is_symbol else "#d6d6ae"
    text_colour = "#374151" if is_symbol else "#ececcf"
    hole_colour = "#ffffff" if is_symbol else "#f3f4f6"
    pad_colour = "#ff6b00"
    image = Image.new("RGB", (width, height), background)
    draw = ImageDraw.Draw(image)
    font_size = max(11, min(17, round(scale * 0.38)))
    try:
        font = ImageFont.truetype("DejaVuSans-Bold.ttf", font_size)
    except OSError:
        try:
            font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", font_size)
        except OSError:
            font = ImageFont.load_default()

    def point(x: float, y: float) -> tuple[float, float]:
        return ((x - min_x + margin_mm) * scale, (max_y - y + margin_mm) * scale)

    def box(first: tuple[float, float], second: tuple[float, float]) -> tuple[float, float, float, float]:
        return min(first[0], second[0]), min(first[1], second[1]), max(first[0], second[0]), max(first[1], second[1])

    def line_width(item: ET.Element, fallback: float = 0.15) -> int:
        return max(1, round(eagle_number(item, "width", fallback) * scale * 0.35))

    def pin_length(item: ET.Element) -> float:
        return {"point": 0, "short": 2.54, "middle": 5.08, "long": 7.62}.get(item.get("length", "middle"), 5.08)

    for item in element.iter():
        tag = item.tag
        if tag == "wire":
            draw.line((point(eagle_number(item, "x1"), eagle_number(item, "y1")),
                       point(eagle_number(item, "x2"), eagle_number(item, "y2"))), fill=foreground, width=line_width(item))
        elif tag == "circle":
            x, y, radius = eagle_number(item, "x"), eagle_number(item, "y"), eagle_number(item, "radius")
            left_top = point(x - radius, y + radius)
            right_bottom = point(x + radius, y - radius)
            draw.ellipse((left_top, right_bottom), outline=foreground, width=line_width(item))
        elif tag == "rectangle":
            draw.rectangle(box(point(eagle_number(item, "x1"), eagle_number(item, "y1")),
                               point(eagle_number(item, "x2"), eagle_number(item, "y2"))), outline=foreground, width=1)
        elif tag == "polygon":
            vertices = [point(eagle_number(vertex, "x"), eagle_number(vertex, "y")) for vertex in item.findall("vertex")]
            if len(vertices) > 2:
                draw.polygon(vertices, fill="#d1d5db" if is_symbol else "#394151", outline=foreground)
        elif tag == "smd":
            x, y = eagle_number(item, "x"), eagle_number(item, "y")
            dx, dy = eagle_number(item, "dx"), eagle_number(item, "dy")
            draw.rectangle(box(point(x - dx / 2, y + dy / 2), point(x + dx / 2, y - dy / 2)), fill=pad_colour)
        elif tag == "pad":
            x, y = eagle_number(item, "x"), eagle_number(item, "y")
            drill = eagle_number(item, "drill")
            diameter = eagle_number(item, "diameter", drill * 1.8)
            radius = max(diameter / 2, 0.4)
            if item.get("shape") == "square":
                draw.rectangle(box(point(x - radius, y + radius), point(x + radius, y - radius)), fill=pad_colour)
            else:
                draw.ellipse((point(x - radius, y + radius), point(x + radius, y - radius)), fill=pad_colour)
            if drill:
                drill_radius = drill / 2
                draw.ellipse((point(x - drill_radius, y + drill_radius), point(x + drill_radius, y - drill_radius)), fill=hole_colour)
        elif tag == "hole":
            x, y, radius = eagle_number(item, "x"), eagle_number(item, "y"), eagle_number(item, "drill") / 2
            draw.ellipse((point(x - radius, y + radius), point(x + radius, y - radius)), outline=foreground, width=1)
        elif tag == "pin":
            x, y = eagle_number(item, "x"), eagle_number(item, "y")
            length = pin_length(item)
            rotation = item.get("rot", "R0")
            direction = rotation[1:]
            dx, dy = {"0": (length, 0), "90": (0, length), "180": (-length, 0), "270": (0, -length)}.get(direction, (length, 0))
            draw.line((point(x, y), point(x + dx, y + dy)), fill=foreground, width=1)
            px, py = point(x, y)
            if direction in {"0", "180"}:
                draw.rectangle((px - 4, py - 2, px + 4, py + 2), fill=pad_colour)
            else:
                draw.rectangle((px - 2, py - 4, px + 2, py + 4), fill=pad_colour)
            label = item.get("name", "")
            label_x, label_y = point(x + dx * 0.92, y + dy * 0.92)
            label_anchor = {"0": "rs", "180": "ls", "90": "ms", "270": "ma"}.get(direction, "rs")
            draw.text((label_x, label_y), label, fill=text_colour, font=font, anchor=label_anchor)
        elif tag == "text":
            x, y = point(eagle_number(item, "x"), eagle_number(item, "y"))
            label = item.text or ""
            if not label.startswith(">"):
                draw.text((x, y), label, fill=text_colour, font=font, anchor="ls")

    target.parent.mkdir(parents=True, exist_ok=True)
    image.save(target, "PNG", optimize=True)


def extract_lbr_components(
    source: Path,
    source_root: Path,
    output: Path,
    repository: str,
    source_ref: str,
    assets_ref: str,
) -> list[dict[str, object]]:
    """Extract Eagle symbols and footprints, grouped by their device definitions.

    Eagle stores a footprint in ``packages`` and a schematic symbol in
    ``symbols``.  A ``deviceset`` maps one or more symbols to one or more
    package variants.  The extracted XML fragments are intentionally exact
    copies of those elements so consumers can inspect or import them without
    downloading and searching the complete library.
    """
    try:
        root = ET.parse(source).getroot()
    except (ET.ParseError, OSError) as error:
        print(f"No se pudo leer {source.relative_to(source_root)}: {error}", file=sys.stderr)
        return []

    library = root.find("./drawing/library")
    if library is None:
        print(f"{source.relative_to(source_root)} no contiene una biblioteca Eagle", file=sys.stderr)
        return []

    packages = {element.get("name", ""): element for element in library.findall("./packages/package")}
    symbols = {element.get("name", ""): element for element in library.findall("./symbols/symbol")}
    source_relative = source.relative_to(source_root)
    source_asset = asset_link(source, source_root, repository, source_ref)
    fragment_cache: dict[tuple[str, str], dict[str, object]] = {}

    def fragment(kind: str, name: str, element: ET.Element) -> dict[str, object]:
        key = (kind, name)
        if key not in fragment_cache:
            identifier = hashlib.sha256(f"{source_relative}:{kind}:{name}".encode()).hexdigest()[:12]
            path = Path("eagle") / kind / f"{safe_file_stem(name)}-{identifier}.lbr"
            section_name = "symbols" if kind == "symbols" else "packages"
            write_eagle_fragment(root, section_name, element, output / path)
            png_path = Path("png") / kind / f"{safe_file_stem(name)}-{identifier}.png"
            render_eagle_png(element, output / png_path)
            preview_2d = {
                "path": png_path.as_posix(),
                "url": raw_url(repository, assets_ref, png_path),
                "mime_type": "image/png",
            }
            fragment_cache[key] = generated_link(
                path, repository, assets_ref, name=name, source_lbr=source_asset["path"],
                preview_2d=preview_2d,
                # These two fields remain for clients that already consume the first PNG release.
                png_path=preview_2d["path"], png_url=preview_2d["url"],
            )
        return fragment_cache[key]

    components: list[dict[str, object]] = []
    for deviceset in library.findall("./devicesets/deviceset"):
        deviceset_name = deviceset.get("name", "Sin nombre")
        symbol_names = [gate.get("symbol", "") for gate in deviceset.findall("./gates/gate")]
        component_symbols = [fragment("symbols", name, symbols[name]) for name in dict.fromkeys(symbol_names) if name in symbols]
        devices = deviceset.findall("./devices/device") or [None]
        for device in devices:
            device_name = "" if device is None else device.get("name", "")
            package_name = "" if device is None else device.get("package", "")
            component_name = deviceset_name if not device_name else f"{deviceset_name} {device_name}"
            identifier = hashlib.sha256(
                f"{source_relative}:{deviceset_name}:{device_name}:{package_name}".encode(),
            ).hexdigest()[:12]
            component: dict[str, object] = {
                "id": identifier,
                "name": component_name,
                "source_lbr": source_asset,
                "eagle_deviceset": deviceset_name,
                "eagle_device": device_name,
                "symbols": component_symbols,
                "footprints": [fragment("footprints", package_name, packages[package_name])]
                if package_name in packages else [],
            }
            component["views_2d"] = {
                "symbols": [asset["preview_2d"] for asset in component_symbols],
                "footprints": [asset["preview_2d"] for asset in component["footprints"]],
            }
            if package_name and package_name not in packages:
                component["footprint_error"] = f"No se encontró el package Eagle {package_name!r}"
            components.append(component)

    # Libraries with packages/symbols but no devicesets remain discoverable.
    if not components:
        for package_name, package in packages.items():
            identifier = hashlib.sha256(f"{source_relative}:package:{package_name}".encode()).hexdigest()[:12]
            footprint = fragment("footprints", package_name, package)
            components.append({
                "id": identifier,
                "name": package_name,
                "source_lbr": source_asset,
                "symbols": [],
                "footprints": [footprint],
                "views_2d": {"symbols": [], "footprints": [footprint["preview_2d"]]},
            })
    return components


def render_link(
    kind: str,
    source: Path,
    source_root: Path,
    output: Path,
    repository: str,
    source_ref: str,
    assets_ref: str,
) -> dict[str, str]:
    """Create an SVG asset and return both the original-file and SVG URLs."""
    relative = source.relative_to(source_root)
    identifier = hashlib.sha256(relative.as_posix().encode()).hexdigest()[:12]
    render_path = Path("svg") / kind / f"{source.stem}-{identifier}.svg"
    asset = asset_link(source, source_root, repository, source_ref)
    try:
        if kind == "symbols":
            render_symbol_svg(source, output / render_path)
        else:
            render_footprint_svg(source, output / render_path)
        asset["svg_url"] = raw_url(repository, assets_ref, render_path)
        asset["svg_path"] = render_path.as_posix()
        print(f"SVG generado: {relative}")
    except Exception as error:
        asset["svg_error"] = str(error)
        print(f"No se pudo generar SVG para {relative}: {error}", file=sys.stderr)
    return asset


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=Path("."), help="directorio de los componentes")
    parser.add_argument("--output", type=Path, default=Path("assets"), help="salida: catalog.json y modelos GLB")
    parser.add_argument("--repository", default=os.environ.get("GITHUB_REPOSITORY", ""), help="owner/repository de GitHub")
    parser.add_argument("--source-ref", default=os.environ.get("GITHUB_SHA", "main"), help="commit/ref de los archivos fuente")
    parser.add_argument("--assets-ref", default="assets", help="rama que alojará catalog.json y los GLB")
    parser.add_argument("--linear-tolerance", type=float, default=0.025, help="tolerancia lineal en mm (por defecto: 0.025)")
    parser.add_argument("--angular-tolerance", type=float, default=0.025, help="tolerancia angular en radianes (por defecto: 0.025)")
    arguments = parser.parse_args()

    if not arguments.repository:
        parser.error("--repository es obligatorio fuera de GitHub Actions")
    if arguments.linear_tolerance <= 0 or arguments.angular_tolerance <= 0:
        parser.error("las tolerancias deben ser mayores que cero")

    source_root = arguments.input.resolve()
    output = arguments.output.resolve()
    if output == source_root:
        parser.error("--output debe ser un subdirectorio distinto de --input")
    if output.exists():
        shutil.rmtree(output)
    output.mkdir(parents=True)

    source_files: dict[str, list[Path]] = {extension: [] for extension in SOURCE_EXTENSIONS}
    step_files: list[Path] = []
    for path in sorted(source_root.rglob("*")):
        if not path.is_file() or output in path.parents:
            continue
        extension = path.suffix.lower()
        if extension in STEP_EXTENSIONS:
            step_files.append(path)
        elif extension in source_files:
            source_files[extension].append(path)

    symbol_assets = {
        asset: render_link(
            "symbols", asset, source_root, output, arguments.repository,
            arguments.source_ref, arguments.assets_ref,
        )
        for asset in source_files[".kicad_sym"]
    }
    footprint_assets = {
        asset: render_link(
            "footprints", asset, source_root, output, arguments.repository,
            arguments.source_ref, arguments.assets_ref,
        )
        for asset in source_files[".kicad_mod"]
    }

    step_records: list[dict[str, object]] = []
    for step in step_files:
        relative = step.relative_to(source_root)
        identifier = hashlib.sha256(relative.as_posix().encode()).hexdigest()[:12]
        model_path = Path("models") / f"{step.stem}-{identifier}.glb"
        record: dict[str, object] = {"step": step, "source_step": asset_link(step, source_root, arguments.repository, arguments.source_ref)}
        source_glb = associated_assets(step, source_files[".glb"], source_root)
        if source_glb:
            (output / model_path).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source_glb[0], output / model_path)
            record["model_glb"] = {
                "path": model_path.as_posix(),
                "url": raw_url(arguments.repository, arguments.assets_ref, model_path),
                "source": "supplier_glb",
                "source_url": asset_link(
                    source_glb[0], source_root, arguments.repository, arguments.source_ref,
                )["url"],
            }
            print(f"GLB original publicado: {source_glb[0].relative_to(source_root)}")
        else:
            try:
                convert_to_glb(step, output / model_path, arguments.linear_tolerance, arguments.angular_tolerance)
                record["model_glb"] = {
                    "path": model_path.as_posix(),
                    "url": raw_url(arguments.repository, arguments.assets_ref, model_path),
                    "source": "generated_from_step",
                    "linear_tolerance_mm": arguments.linear_tolerance,
                    "angular_tolerance_rad": arguments.angular_tolerance,
                }
                print(f"GLB generado: {relative}")
            except Exception as error:
                record["model_error"] = str(error)
                print(f"No se pudo convertir {relative}: {error}", file=sys.stderr)
        step_records.append(record)

    components: list[dict[str, object]] = []
    for library in source_files[".lbr"]:
        components.extend(extract_lbr_components(
            library, source_root, output, arguments.repository,
            arguments.source_ref, arguments.assets_ref,
        ))

    for record in step_records:
        step = record["step"]
        component: dict[str, object] = {
            "id": hashlib.sha256(step.relative_to(source_root).as_posix().encode()).hexdigest()[:12],
            "name": step.name,
            "source_step": record["source_step"],
            "symbols": [symbol_assets[asset]
                        for asset in associated_assets(step, source_files[".kicad_sym"], source_root)],
            "footprints": [footprint_assets[asset]
                           for asset in associated_assets(step, source_files[".kicad_mod"], source_root)],
            "eagle_libraries": [asset_link(asset, source_root, arguments.repository, arguments.source_ref)
                                for asset in associated_assets(step, source_files[".lbr"], source_root)],
            "svg": [asset_link(asset, source_root, arguments.repository, arguments.source_ref)
                    for asset in associated_assets(step, source_files[".svg"], source_root)],
        }
        if "model_glb" in record:
            component["model_glb"] = record["model_glb"]
        if "model_error" in record:
            component["model_error"] = record["model_error"]
        components.append(component)

    manifest = {
        "schema_version": 2,
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "repository": arguments.repository,
        "source_ref": arguments.source_ref,
        "assets_ref": arguments.assets_ref,
        "catalog_url": raw_url(arguments.repository, arguments.assets_ref, Path("catalog.json")),
        "components": components,
        "unassociated": {
            "eagle_libraries": [asset_link(asset, source_root, arguments.repository, arguments.source_ref)
                                for asset in source_files[".lbr"] if not any(
                                    component.get("source_lbr", {}).get("path") == asset.relative_to(source_root).as_posix()
                                    for component in components
                                )],
            "svg": [asset_link(asset, source_root, arguments.repository, arguments.source_ref)
                    for asset in source_files[".svg"]],
        },
    }
    (output / "catalog.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Manifest creado en {output / 'catalog.json'} ({len(components)} componente(s))")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
