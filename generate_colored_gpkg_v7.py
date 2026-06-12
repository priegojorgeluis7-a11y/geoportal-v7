#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
V7 - Genera GPKG coloreado desde Google Sheets.
SOLO actualiza columnas existentes (COLOR, COLOR_RGBA, COLOR_RGB, ESTATUS 1).
NO crea nuevas columnas.

Reglas de formato condicional (mismo orden que la tabla de Google Sheets):
  - Verde  (#00FF00) → L (Liberado):     C.O.P, A.O.P, Firmado COP/AOT
  - Rojo   (#FF0000) → NL (No Liberado):  Levantamiento, Sin info, etc. (default)
  - Amarillo (#FFFF00) → NG (Negociación): Citado, Federal, Municipal, En negociación, Firma COP
  - Café   (#A0522D) → R (Revisión):      Posible D.O.T, En revisión para posible DOT

USO:
  python3 generate_colored_gpkg_v7.py
"""

import requests
import csv
import io
import sqlite3
import shutil
import os
import re
import sys

# ============================================================
# CONFIGURACION
# ============================================================
SHEET_ID = '1WY24BYmehH2pjcYyjwNfkdwgKD-4eV41fiDfUyAXyL4'
GID = '1831931870'
GPKG_PATH = 'poligonos finales 16 y 17.gpkg'
OUTPUT_GPKG = 'poligonos_finales_coloreados_v7.gpkg'
QML_OUTPUT = 'poligonos_finales_coloreados_v7.qml'

# ============================================================
# COLORES POR CATEGORIA
# ============================================================
COLORES = {
    "L":  "#00FF00",    # Verde - Liberado
    "NL": "#FF0000",    # Rojo - No Liberado
    "NG": "#FFFF00",    # Amarillo - Negociación
    "R":  "#A0522D",    # Café - Revisión (Sienna/Brown)
}

COLORES_RGBA = {
    "L":  "#00FF00FF",
    "NL": "#FF0000FF",
    "NG": "#FFFF00FF",
    "R":  "#A0522DFF",
}

COLORES_RGB = {
    "L":  "0,255,0",
    "NL": "255,0,0",
    "NG": "255,255,0",
    "R":  "160,82,45",
}

ETIQUETAS = {
    "L":  "L - Liberado",
    "NL": "NL - No Liberado",
    "NG": "NG - Negociación",
    "R":  "R - Revisión",
}


def determinar_estatus(estatus, cop, tipo, id_val):
    """
    Determina la categoría (L, NL, NG, R) según las reglas
    del formato condicional de la tabla de Google Sheets,
    en el mismo orden de prioridad.

    Verde  (L)  = Liberado     → C.O.P, A.O.P, Firmado COP/AOT
    Amarillo(NG)= Negociación  → Citado, Federal, Municipal, En negociación, Firma COP
    Café   (R)  = Revisión     → Posible D.O.T, En revisión para posible DOT
    Rojo   (NL) = No Liberado  → Todo lo demás (Levantamiento, Sin info, etc.)
    """
    e = str(estatus or '').upper().strip()
    c = str(cop or '').upper().strip()
    t = str(tipo or '').upper().strip()
    idv = str(id_val or '').strip()

    # --- REGLAS EN ORDEN DE PRIORIDAD (como en la tabla de Google Sheets) ---

    # 1. C.O.P en columna G → VERDE (L)
    if 'C.O.P' in c:
        return 'L'

    # 2. A.O.P en columna G → VERDE (L)
    if 'A.O.P' in c:
        return 'L'

    # 3. Citado a Negociación en columna E → AMARILLO (NG)
    if 'CITADO A NEGOCIACIÓN' in e or 'CITADO A NEGOCIACION' in e:
        return 'NG'

    # 4. Sin información de propietario en columna G → ROJO (NL)
    if 'SIN INFORMACIÓN DE PROPIETARIO' in c or 'SIN INFORMACION DE PROPIETARIO' in c:
        return 'NL'

    # 5. En Levantamiento en columna E → ROJO (NL)
    if 'EN LEVANTAMIENTO' in e:
        return 'NL'

    # 6. En Levantamiento en columna G → ROJO (NL)
    if 'EN LEVANTAMIENTO' in c:
        return 'NL'

    # 7. POSIBLE D.O.T en columna G → CAFÉ (R)
    if 'POSIBLE D.O.T' in c or 'POSIBLE DOT' in c:
        return 'R'

    # 8. Levantamiento completo en columna E → ROJO (NL)
    if 'LEVANTAMIENTO COMPLETO' in e:
        return 'NL'

    # 9. Federal en columna J → AMARILLO (NG)
    if 'FEDERAL' in t:
        return 'NG'

    # 10. Municipal en columna J → AMARILLO (NG)
    if 'MUNICIPAL' in t:
        return 'NG'

    # 11. En negociación/PU Pactado en columna E → AMARILLO (NG)
    if 'EN NEGOCIACIÓN' in e or 'EN NEGOCIACION' in e or 'PU PACTADO' in e:
        return 'NG'

    # 12. En proceso de Acercamiento en columna E → ROJO (NL)
    if 'EN PROCESO DE ACERCAMIENTO' in e:
        return 'NL'

    # 13. Sin información de propietario en columna E → ROJO (NL)
    if 'SIN INFORMACIÓN DE PROPIETARIO' in e or 'SIN INFORMACION DE PROPIETARIO' in e:
        return 'NL'

    # 14. En proceso de firma COP en columna E → AMARILLO (NG)
    if 'EN PROCESO DE FIRMA COP' in e:
        return 'NG'

    # 15. Firmado COP/AOT en columna E → VERDE (L)
    if 'FIRMADO COP' in e or 'FIRMADO AOT' in e:
        return 'L'

    # 16. En revisión para posible DOT en columna E → CAFÉ (R)
    if 'EN REVISION PARA POSIBLE DOT' in e or 'EN REVISIÓN PARA POSIBLE DOT' in e:
        return 'R'

    # 17. ID en blanco → AMARILLO (NG)
    if not idv or idv == '' or idv.upper() == 'N/A' or idv == 'None':
        return 'NG'

    # Default: No Liberado (Rojo)
    return 'NL'


def normalize_nom(nom):
    """Normaliza nomenclatura para comparación."""
    if nom is None:
        return None
    nom = str(nom).strip().upper()
    nom = nom.replace('\n', ' ').replace('\r', ' ')
    nom = re.sub(r'\s+', ' ', nom)
    nom = nom.strip()
    return nom


def download_gsheet_data():
    """Descarga datos de Google Sheets."""
    url = f'https://docs.google.com/spreadsheets/d/{SHEET_ID}/export?format=csv&gid={GID}'
    print(f"  URL: {url}")
    resp = requests.get(url, timeout=30)
    resp.raise_for_status()

    reader = csv.reader(io.StringIO(resp.text))
    header = next(reader)
    print(f"  Header: {header}")

    rows = []
    for row in reader:
        if len(row) >= 10:
            rows.append({
                'PK': row[0].strip() if row[0] else '',
                'ID': row[1].strip() if row[1] else '',
                'NOMENCLATURA': row[2].strip() if row[2] else '',
                'PROPIETARIO': row[3].strip() if row[3] else '',
                'ESTATUS_ACTUAL': row[4].strip() if row[4] else '',
                'Segmento': row[5].strip() if row[5] else '',
                'COP': row[6].strip() if row[6] else '',
                'KM_INICIO': row[7].strip() if row[7] else '',
                'KM_FIN': row[8].strip() if row[8] else '',
                'TIPO_PROPIEDAD': row[9].strip() if row[9] else '',
            })

    return rows


def build_excel_lookup(rows):
    """Construye lookup table a partir de datos de Google Sheets."""
    excel_by_nom = {}
    excel_by_id = {}

    for row_data in rows:
        estatus = determinar_estatus(
            row_data.get('ESTATUS_ACTUAL', ''),
            row_data.get('COP', ''),
            row_data.get('TIPO_PROPIEDAD', ''),
            row_data.get('ID', '')
        )

        nom_norm = normalize_nom(row_data.get('NOMENCLATURA', ''))
        id_str = row_data.get('ID', '').strip()

        if nom_norm and nom_norm not in ('N/A', 'S/N', 'NONE', ''):
            if nom_norm not in excel_by_nom:
                excel_by_nom[nom_norm] = []
            excel_by_nom[nom_norm].append((row_data, estatus))

        if id_str and id_str not in ('N/A', 'None', ''):
            if id_str not in excel_by_id:
                excel_by_id[id_str] = []
            excel_by_id[id_str].append((row_data, estatus))

    return excel_by_nom, excel_by_id


def find_estatus_for_feature(gpkg_id, gpkg_nom, gpkg_prop, excel_by_nom, excel_by_id):
    """
    Encuentra el estatus para un feature del GPKG buscando
    coincidencia por nomenclatura e ID.
    """
    if gpkg_nom:
        nom_norm = normalize_nom(gpkg_nom)
        if nom_norm in excel_by_nom:
            return excel_by_nom[nom_norm][0][1], f"nom={gpkg_nom}", True

    if gpkg_id:
        id_str = str(gpkg_id).strip()
        if id_str in excel_by_id:
            return excel_by_id[id_str][0][1], f"id={gpkg_id}", True

    if gpkg_nom:
        nom_upper = gpkg_nom.upper()
        variations = set()
        variations.add(nom_upper.replace('*', '-'))
        variations.add(nom_upper.replace('*', '/'))
        variations.add(nom_upper.replace('-', '/'))
        variations.add(nom_upper.replace('/', '-'))
        variations.add(nom_upper.replace('SVIL', 'VIL'))
        variations.add(nom_upper.replace('VIL', 'SVIL'))
        variations.add(nom_upper.replace('SLN', 'SNL'))
        variations.add(nom_upper.replace('04', '4'))
        variations.add(nom_upper.replace('  ', ' '))
        variations.add(nom_upper.strip())

        for var in variations:
            if var in excel_by_nom:
                return excel_by_nom[var][0][1], f"nom_var={var}", True

    if gpkg_prop:
        prop_upper = gpkg_prop.upper().strip()
        best_match = None
        best_score = 0

        for nom_key, entries in excel_by_nom.items():
            for row_data, est in entries:
                excel_prop = str(row_data.get('PROPIETARIO', '') or '').upper().strip()
                if excel_prop and prop_upper:
                    excel_words = set(re.sub(r'[^A-Z0-9 ]', ' ', excel_prop).split())
                    gpkg_words = set(re.sub(r'[^A-Z0-9 ]', ' ', prop_upper).split())
                    if len(excel_words) > 0 and len(gpkg_words) > 0:
                        common = excel_words & gpkg_words
                        score = len(common) / max(len(excel_words), len(gpkg_words))
                        if score > best_score:
                            best_score = score
                            best_match = est

        if best_score >= 0.3:
            return best_match, f"prop_match={gpkg_prop}", True

    return None, None, False


def generar_estilo_qml():
    """
    Genera un estilo QML para QGIS con los colores categorizados por ESTATUS 1.
    Usa los colores correctos: Verde (L), Rojo (NL), Amarillo (NG), Café (R).
    """
    qml = """<!DOCTYPE qgis PUBLIC 'http://mrcc.com/qgis.dtd' 'SYSTEM'>
<qgis version="3.34.0" styleCategories="Symbology|Labeling">
  <renderer-v2 type="categorizedSymbol" forceraster="0" symbollevels="0" enableorderby="0"
    attr="ESTATUS 1" label="">
    <categories>
"""
    for valor in ['L', 'NL', 'NG', 'R']:
        color = COLORES.get(valor, "#000000")
        etiqueta = ETIQUETAS.get(valor, valor)
        qml += f"""      <category symbol="{valor}" value="{valor}" label="{etiqueta}" render="true"/>
"""

    qml += """    </categories>
    <symbols>
"""
    for valor in ['L', 'NL', 'NG', 'R']:
        color = COLORES.get(valor, "#000000")
        qml += f"""      <symbol name="{valor}" type="fill" alpha="1" force_rhr="0" clip_to_extent="1">
        <data_defined_properties>
          <Option type="Map">
            <Option name="name" type="QString" value=""/>
            <Option name="properties"/>
            <Option name="type" type="QString" value="collection"/>
          </Option>
        </data_defined_properties>
        <layer pass="0" class="SimpleFill" enabled="1" locked="0">
          <Option type="Map">
            <Option name="border_width_map_unit_scale" type="QString" value="3x:0,0,0,0,0,0"/>
            <Option name="color" type="QString" value="{color}"/>
            <Option name="joinstyle" type="QString" value="bevel"/>
            <Option name="offset" type="QString" value="0,0"/>
            <Option name="offset_map_unit_scale" type="QString" value="3x:0,0,0,0,0,0"/>
            <Option name="offset_unit" type="QString" value="MM"/>
            <Option name="outline_color" type="QString" value="0,0,0,255"/>
            <Option name="outline_style" type="QString" value="solid"/>
            <Option name="outline_width" type="QString" value="0.26"/>
            <Option name="outline_width_map_unit_scale" type="QString" value="3x:0,0,0,0,0,0"/>
            <Option name="outline_width_unit" type="QString" value="MM"/>
            <Option name="style" type="QString" value="solid"/>
          </Option>
          <data_defined_properties>
            <Option type="Map">
              <Option name="name" type="QString" value=""/>
              <Option name="properties"/>
              <Option name="type" type="QString" value="collection"/>
            </Option>
          </data_defined_properties>
        </layer>
      </symbol>
"""

    qml += """    </symbols>
    <source-symbol>
      <symbol name="0" type="fill" alpha="1" force_rhr="0" clip_to_extent="1">
        <data_defined_properties>
          <Option type="Map">
            <Option name="name" type="QString" value=""/>
            <Option name="properties"/>
            <Option name="type" type="QString" value="collection"/>
          </Option>
        </data_defined_properties>
        <layer pass="0" class="SimpleFill" enabled="1" locked="0">
          <Option type="Map">
            <Option name="border_width_map_unit_scale" type="QString" value="3x:0,0,0,0,0,0"/>
            <Option name="color" type="QString" value="190,207,80,255"/>
            <Option name="joinstyle" type="QString" value="bevel"/>
            <Option name="offset" type="QString" value="0,0"/>
            <Option name="offset_map_unit_scale" type="QString" value="3x:0,0,0,0,0,0"/>
            <Option name="offset_unit" type="QString" value="MM"/>
            <Option name="outline_color" type="QString" value="35,35,35,255"/>
            <Option name="outline_style" type="QString" value="solid"/>
            <Option name="outline_width" type="QString" value="0.26"/>
            <Option name="outline_width_map_unit_scale" type="QString" value="3x:0,0,0,0,0,0"/>
            <Option name="outline_width_unit" type="QString" value="MM"/>
            <Option name="style" type="QString" value="solid"/>
          </Option>
        </layer>
      </symbol>
    </source-symbol>
    <colorramp name="[source]" type="randomcolors">
      <Option/>
    </colorramp>
  </renderer-v2>
  <labeling type="simple">
    <settings calloutType="simple">
      <text-style fontItalic="0" fontLetterSpacing="0" fontWordSpacing="0"
        isExpression="0" useSubstitutions="0" textOpacity="1"
        fontSizeMapUnitScale="3x:0,0,0,0,0,0" previewBkgrdColor="255,255,255,255"
        fontUnderline="0" textOrientation="horizontal" fontSize="8"
        fontStrikeout="0" multilineHeight="1" fontFamily="Arial"
        fontKerning="1" namedStyle="Normal" fontWeight="50"
        fontSizeUnit="Point" fieldName="NOMENCALTURA"
        fontCapitals="0" blendMode="0" fontHinting="1"
        fontLetterSpacingUnit="Point" fontWordSpacingUnit="Point"
        textColor="0,0,0,255" allowHtml="0">
        <families/>
        <text-buffer bufferSize="1" bufferSizeMapUnitScale="3x:0,0,0,0,0,0"
          bufferColor="255,255,255,255" bufferOpacity="1" bufferSizeUnits="MM"
          bufferBlendMode="0" bufferJoinStyle="128" bufferNoFill="1"
          bufferDraw="1"/>
        <text-mask maskSize="1.5" maskOpacity="1" maskEnabled="0"
          maskSizeMapUnitScale="3x:0,0,0,0,0,0" maskSizeUnits="MM"
          maskJoinStyle="128" maskedSymbolLayers=""/>
        <background shapeOffsetUnit="MM" shapeSizeX="0" shapeSizeY="0"
          shapeBorderWidthUnit="MM" shapeRadiiUnit="MM" shapeJoinStyle="64"
          shapeRadiiMapUnitScale="3x:0,0,0,0,0,0" shapeBorderWidth="0"
          shapeSizeMapUnitScale="3x:0,0,0,0,0,0" shapeRotationType="0"
          shapeBorderColor="128,128,128,255" shapeSizeUnit="MM"
          shapeBlendMode="0" shapeOpacity="1" shapeRadiiY="0"
          shapeOffsetY="0" shapeOffsetX="0" shapeRadiiX="0"
          shapeSVGFile="" shapeOffsetMapUnitScale="3x:0,0,0,0,0,0"
          shapeType="0" shapeFillColor="255,255,255,255"
          shapeBorderWidthMapUnitScale="3x:0,0,0,0,0,0"
          shapeDraw="0" shapeRotation="0"/>
        <shadow shadowOffsetMapUnitScale="3x:0,0,0,0,0,0"
          shadowOffsetGlobal="1" shadowRadiusUnits="MM"
          shadowUnder="0" shadowOffsetDist="1" shadowScale="100"
          shadowRadiusMapUnitScale="3x:0,0,0,0,0,0"
          shadowDraw="0" shadowOffsetAngle="135" shadowRadius="1.5"
          shadowColor="0,0,0,255" shadowBlendMode="6" shadowOpacity="0.69999999999999996"
          shadowOffsetUnit="MM" shadowRadiusAlphaOnly="0"/>
        <dd_properties>
          <Option type="Map">
            <Option name="name" type="QString" value=""/>
            <Option name="properties"/>
            <Option name="type" type="QString" value="collection"/>
          </Option>
        </dd_properties>
        <substitutions/>
      </text-style>
      <text-format placeSymbol="0" multilineAlign="3" autoWrapLength="0"
        wrapChar="" formatNumbers="0" decimals="3" leftDirectionSymbol="<"
        rightDirectionSymbol=">" reverseDirectionSymbol="0" addDirectionSymbol="0"
        useMaxLineLengthForAutoWrap="1"/>
      <placement overrunDistance="0" dist="0" maxCurvedCharAngleIn="25"
        placement="1" quadOffset="4" priority="5" distUnits="MM"
        repeatDistance="0" repeatDistanceMapUnitScale="3x:0,0,0,0,0,0"
        maxCurvedCharAngleOut="-25" geometryGeneratorType="PointGeometry"
        lineAnchorClipping="0" lineAnchorPercent="0.5" polygonPlacementFlags="2"
        rotationUnit="AngleDegrees" preserveRotation="1"
        lineAnchorType="0" offsetType="0" overrunDistanceUnit="MM"
        overrunDistanceMapUnitScale="3x:0,0,0,0,0,0"
        repeatDistanceUnits="MM" distMapUnitScale="3x:0,0,0,0,0,0"
        layerType="PolygonGeometry" labelOffsetMapUnitScale="3x:0,0,0,0,0,0"
        offsetUnits="MM" yOffset="0" xOffset="0" rotationAngle="0"
        centroidWhole="0" predefinedPositionOrder="TR,TL,BR,BL,R,L,TSR,BSR"
        geometryGeneratorEnabled="0" geometryGenerator=""
        fitInPolygonOnly="0" lineAnchorTextPoint="FollowPlacement"
        centroidInside="1" allowDegraded="0"/>
      <rendering fontMaxPixelSize="10000" scaleMax="0" obstacle="1"
        fontLimitPixelSize="0" scaleMin="0" obstacleFactor="1"
        obstacleType="1" labelPerPart="0" maxNumLabels="2000"
        limitNumLabels="0" upsidedownLabels="0" fontMinPixelSize="3"
        mergeLines="0" scaleVisibility="0" unplacedVisibility="0"
        displayAll="0" minFeatureSize="0" zIndex="0" drawLabels="1"/>
      <dd_properties>
        <Option type="Map">
          <Option name="name" type="QString" value=""/>
          <Option name="properties"/>
          <Option name="type" type="QString" value="collection"/>
        </Option>
      </dd_properties>
      <callout type="simple">
        <Option type="Map">
          <Option name="anchorPoint" type="QString" value="pole_of_inaccessibility"/>
          <Option name="blendMode" type="int" value="0"/>
          <Option name="calloutType" type="QString" value="simple"/>
          <Option name="ddProperties" type="Map">
            <Option name="name" type="QString" value=""/>
            <Option name="properties"/>
            <Option name="type" type="QString" value="collection"/>
          </Option>
          <Option name="drawToAllParts" type="bool" value="false"/>
          <Option name="enabled" type="QString" value="0"/>
          <Option name="labelAnchorPoint" type="QString" value="point_on_exterior"/>
          <Option name="lineSymbol" type="QList" value=""/>
          <Option name="minLength" type="double" value="0"/>
          <Option name="minLengthMapUnitScale" type="QString" value="3x:0,0,0,0,0,0"/>
          <Option name="minLengthUnit" type="QString" value="MM"/>
          <Option name="offsetFromAnchor" type="double" value="0"/>
          <Option name="offsetFromAnchorMapUnitScale" type="QString" value="3x:0,0,0,0,0,0"/>
          <Option name="offsetFromAnchorUnit" type="QString" value="MM"/>
          <Option name="offsetFromLabel" type="double" value="0"/>
          <Option name="offsetFromLabelMapUnitScale" type="QString" value="3x:0,0,0,0,0,0"/>
          <Option name="offsetFromLabelUnit" type="QString" value="MM"/>
        </Option>
      </callout>
    </settings>
  </labeling>
</qgis>"""
    return qml


def actualizar_estilo_en_gpkg(conn, cursor, table_name, qml_content):
    """Actualiza el estilo QML en la tabla layer_styles del GPKG."""
    # Verificar si existe la tabla layer_styles
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='layer_styles'")
    if not cursor.fetchone():
        cursor.execute("""
            CREATE TABLE layer_styles (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                f_table_catalog TEXT DEFAULT '',
                f_table_schema TEXT DEFAULT '',
                f_table_name TEXT,
                f_geometry_column TEXT DEFAULT 'geom',
                styleName TEXT,
                styleQML TEXT,
                styleSLD TEXT,
                useAsDefault BOOLEAN DEFAULT 0,
                description TEXT,
                owner TEXT DEFAULT '',
                ui TEXT DEFAULT '',
                update_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        print("  Tabla layer_styles creada")

    # Eliminar estilo anterior si existe
    cursor.execute(f"DELETE FROM layer_styles WHERE f_table_name = '{table_name}'")

    # Insertar nuevo estilo
    cursor.execute("""
        INSERT INTO layer_styles 
        (f_table_catalog, f_table_schema, f_table_name, f_geometry_column, 
         styleName, styleQML, styleSLD, useAsDefault, description, owner, ui)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        '', '', table_name, 'geom',
        'Estatus por colores V7', qml_content, '', 1,
        'V7: L=Verde (#00FF00), NL=Rojo (#FF0000), NG=Amarillo (#FFFF00), R=Café (#A0522D)',
        '', ''
    ))

    conn.commit()
    print(f"  Estilo QML actualizado en layer_styles ({len(qml_content)} bytes)")


def main():
    print("=" * 60)
    print("GENERADOR V7 - GPKG COLOREADO DESDE GOOGLE SHEETS")
    print("=" * 60)
    print("(Solo actualiza columnas existentes - NO crea nuevas)")
    print()

    # 1. Descargar datos de Google Sheets
    print("Descargando Google Sheet...")
    try:
        rows = download_gsheet_data()
        print(f"  Descargadas {len(rows)} filas")
    except Exception as e:
        print(f"ERROR al descargar Google Sheets: {e}")
        sys.exit(1)

    # 2. Construir lookup
    print("\nConstruyendo lookup table...")
    excel_by_nom, excel_by_id = build_excel_lookup(rows)
    print(f"  Nomenclaturas únicas: {len(excel_by_nom)}")
    print(f"  IDs únicos: {len(excel_by_id)}")

    # 3. Mostrar distribución de estatus según reglas
    print("\nDistribución de estatus según Google Sheets:")
    dist = {}
    for row_data in rows:
        est = determinar_estatus(
            row_data.get('ESTATUS_ACTUAL', ''),
            row_data.get('COP', ''),
            row_data.get('TIPO_PROPIEDAD', ''),
            row_data.get('ID', '')
        )
        dist[est] = dist.get(est, 0) + 1
    for est in ['L', 'NL', 'NG', 'R']:
        cnt = dist.get(est, 0)
        color_nombre = {'L': 'Verde', 'NL': 'Rojo', 'NG': 'Amarillo', 'R': 'Café'}.get(est, '?')
        print(f"  {est} ({color_nombre}): {cnt}")

    # 4. Copiar GPKG original
    print(f"\nCopiando GPKG...")
    print(f"  Origen: {GPKG_PATH}")
    print(f"  Destino: {OUTPUT_GPKG}")
    if os.path.exists(OUTPUT_GPKG):
        os.remove(OUTPUT_GPKG)
    shutil.copy2(GPKG_PATH, OUTPUT_GPKG)
    size_mb = os.path.getsize(OUTPUT_GPKG) / (1024 * 1024)
    print(f"  Tamaño: {size_mb:.1f} MB")

    # 5. Conectar al GPKG y actualizar
    print(f"\nActualizando GPKG...")
    conn = sqlite3.connect(OUTPUT_GPKG)
    cursor = conn.cursor()

    # Obtener nombre de la tabla de features
    cursor.execute("SELECT table_name FROM gpkg_contents WHERE data_type='features'")
    table_name = cursor.fetchone()[0]
    print(f"  Tabla: {table_name}")

    # Verificar columnas existentes
    cursor.execute(f'PRAGMA table_info("{table_name}")')
    existing_cols = {col[1] for col in cursor.fetchall()}
    print(f"  Columnas existentes: {sorted(existing_cols)}")

    # Verificar que las columnas necesarias existen
    needed_cols = ['COLOR', 'COLOR_RGBA', 'COLOR_RGB', 'ESTATUS 1']
    for col in needed_cols:
        if col not in existing_cols:
            print(f"  ERROR: La columna '{col}' no existe en el GPKG.")
            print(f"  Este script solo actualiza columnas existentes.")
            print(f"  Ejecuta primero un script que cree las columnas (v4, v5 o v6).")
            sys.exit(1)

    # Desactivar triggers temporalmente
    cursor.execute(f'SELECT name FROM sqlite_master WHERE type="trigger" AND tbl_name="{table_name}"')
    triggers = [t[0] for t in cursor.fetchall()]
    for trig in triggers:
        cursor.execute(f'DROP TRIGGER IF EXISTS "{trig}"')
    if triggers:
        print(f"  Triggers desactivados: {len(triggers)}")

    # Leer todos los features del GPKG
    cursor.execute(f'SELECT fid, ID, NOMENCALTURA, "NOMBRE DE PROPIETARIO", "ESTATUS 1" FROM "{table_name}" ORDER BY fid')
    features = cursor.fetchall()
    print(f"  Total features en GPKG: {len(features)}")

    # Construir set de nomenclaturas e IDs que existen en el GPKG
    gpkg_noms = set()
    gpkg_ids = set()
    for feat in features:
        _, gpkg_id, gpkg_nom, _, _ = feat
        if gpkg_nom:
            gpkg_noms.add(normalize_nom(gpkg_nom))
        if gpkg_id:
            gpkg_ids.add(str(gpkg_id).strip())

    # Detectar filas en Sheets que NO existen en GPKG
    sheets_sin_gpkg = []
    for row_data in rows:
        nom_norm = normalize_nom(row_data.get('NOMENCLATURA', ''))
        id_str = row_data.get('ID', '').strip()
        if nom_norm and nom_norm not in gpkg_noms and id_str and id_str not in gpkg_ids:
            sheets_sin_gpkg.append(row_data)

    # Actualizar cada feature
    actualizados = 0
    cambios_estatus = 0
    no_match = 0
    errores = []
    stats = {'L': 0, 'NL': 0, 'NG': 0, 'R': 0}

    for feat in features:
        fid, gpkg_id, gpkg_nom, gpkg_prop, gpkg_estatus1 = feat

        # Buscar coincidencia en Google Sheets
        estatus, match_info, was_matched = find_estatus_for_feature(
            gpkg_id, gpkg_nom, gpkg_prop, excel_by_nom, excel_by_id
        )

        if was_matched and estatus:
            # Actualizar ESTATUS 1 si cambió
            if estatus != gpkg_estatus1:
                cursor.execute(f'UPDATE "{table_name}" SET "ESTATUS 1" = ? WHERE fid = ?',
                              (estatus, fid))
                cambios_estatus += 1

            # Actualizar colores
            color_hex = COLORES.get(estatus)
            color_rgba = COLORES_RGBA.get(estatus)
            color_rgb = COLORES_RGB.get(estatus)

            cursor.execute(f'UPDATE "{table_name}" SET COLOR = ?, COLOR_RGBA = ?, COLOR_RGB = ? WHERE fid = ?',
                          (color_hex, color_rgba, color_rgb, fid))
            actualizados += 1
            stats[estatus] = stats.get(estatus, 0) + 1
        else:
            no_match += 1
            errores.append((fid, gpkg_nom))

    conn.commit()

    print(f"\n  Features actualizados: {actualizados}")
    print(f"  Cambios en ESTATUS 1: {cambios_estatus}")
    print(f"  Sin match en Sheets: {no_match}")

    # Mostrar distribución final
    print(f"\n  Distribución final de ESTATUS 1:")
    for est in ['L', 'NL', 'NG', 'R']:
        cnt = stats.get(est, 0)
        color_nombre = {'L': 'Verde', 'NL': 'Rojo', 'NG': 'Amarillo', 'R': 'Café'}.get(est, '?')
        print(f"    {est} ({color_nombre}): {cnt}")

    if errores:
        print(f"\n  Features SIN match en Sheets (primeros 10):")
        for fid, nom in errores[:10]:
            print(f"    fid={fid}: [{nom}]")
        if len(errores) > 10:
            print(f"    ... y {len(errores) - 10} más")
        print(f"  → Estos predios existen en el GPKG pero NO en Google Sheets.")
        print(f"  → Si se eliminaron de Sheets, puedes ignorarlos.")
        print(f"  → Si deberían estar en Sheets, revísalos.")

    if sheets_sin_gpkg:
        print(f"\n  Filas en Sheets SIN match en GPKG ({len(sheets_sin_gpkg)}):")
        for row_data in sheets_sin_gpkg[:10]:
            nom = row_data.get('NOMENCLATURA', '')
            idv = row_data.get('ID', '')
            print(f"    ID={idv}, NOM={nom}")
        if len(sheets_sin_gpkg) > 10:
            print(f"    ... y {len(sheets_sin_gpkg) - 10} más")
        print(f"  → Estos predios están en Google Sheets pero NO tienen polígono en el GPKG.")
        print(f"  → Para agregarlos: dibuja el polígono en QGIS y asígnale el mismo ID/Nomenclatura.")
        print(f"  → Luego vuelve a ejecutar este programa para colorearlos.")

    # Verificar
    cursor.execute(f'SELECT fid, ID, NOMENCALTURA, "ESTATUS 1", COLOR, COLOR_RGBA, COLOR_RGB FROM "{table_name}" WHERE COLOR IS NOT NULL LIMIT 10')
    print(f"\n  Muestra de features coloreados:")
    for r in cursor.fetchall():
        print(f"    fid={r[0]}, id={r[1]}, nom={r[2]}, est={r[3]}, color={r[4]}")

    cursor.execute(f'SELECT COUNT(*) FROM "{table_name}" WHERE COLOR IS NULL')
    sin_color = cursor.fetchone()[0]
    if sin_color:
        print(f"\n  Features sin COLOR: {sin_color}")

    # 6. Generar y actualizar estilo QML en el GPKG
    print(f"\nActualizando estilo QML en el GPKG...")
    qml_content = generar_estilo_qml()
    actualizar_estilo_en_gpkg(conn, cursor, table_name, qml_content)

    conn.close()

    # 7. Guardar archivo QML externo
    print(f"\nGuardando archivo QML: {QML_OUTPUT}")
    with open(QML_OUTPUT, 'w', encoding='utf-8') as f:
        f.write(qml_content)
    print(f"  {len(qml_content)} bytes escritos")

    # 8. Resumen final

    print("\n" + "=" * 60)
    print("RESUMEN FINAL")
    print("=" * 60)
    print(f"  GPKG de salida: {OUTPUT_GPKG}")
    print(f"  Features coloreados: {actualizados}")
    print(f"  Cambios en ESTATUS 1: {cambios_estatus}")
    print(f"  Sin match en Sheets: {no_match}")
    print()
    print("  Colores aplicados (formato condicional):")
    print("    L  (Verde)    = Liberado     → C.O.P, A.O.P, Firmado COP/AOT")
    print("    NL (Rojo)     = No Liberado  → Levantamiento, Sin info, etc.")
    print("    NG (Amarillo) = Negociación  → Citado, Federal, Municipal, En negociación, Firma COP")
    print("    R  (Café)     = Revisión     → Posible D.O.T, En revisión para posible DOT")
    print()
    print("  NOTA: Solo se actualizaron columnas existentes (COLOR, COLOR_RGBA, COLOR_RGB, ESTATUS 1)")
    print("  No se crearon nuevas columnas.")
    print("=" * 60)


if __name__ == '__main__':
    main()
