#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Genera geoportal_v7/index.html con datos actualizados desde Google Sheets.
Versión para CI/CD (GitHub Actions).

FLUJO:
  1. Descarga datos de Google Sheets
  2. Determina estatus (L/NL/NG/R) según reglas de formato condicional
  3. Lee el GPKG y exporta a GeoJSON usando ogr2ogr
  4. Asigna estatus a cada feature del GeoJSON
  5. Genera HTML con mapa Leaflet y tabla interactiva

REQUISITOS:
  - ogr2ogr (GDAL) instalado
  - Python con requests

USO:
  python3 generate_geoportal_v7_ci.py
"""

import requests
import csv
import io
import json
import sqlite3
import os
import re
import sys
import subprocess
import tempfile
from datetime import datetime

# ============================================================
# CONFIGURACION
# ============================================================
SHEET_ID = '1WY24BYmehH2pjcYyjwNfkdwgKD-4eV41fiDfUyAXyL4'
GID = '1831931870'
GPKG_PATH = 'poligonos finales 16 y 17.gpkg'
OUTPUT_HTML = 'geoportal_v7/index.html'

# ============================================================
# COLORES POR CATEGORIA
# ============================================================
COLORES = {
    "L":  "#00FF00",
    "NL": "#FF0000",
    "NG": "#FFFF00",
    "R":  "#A0522D",
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


def get_timestamp():
    return datetime.now().strftime("%d/%m/%Y %H:%M")


def determinar_estatus(estatus, cop, tipo, id_val):
    """Determina la categoría (L, NL, NG, R) según reglas de formato condicional."""
    e = str(estatus or '').upper().strip()
    c = str(cop or '').upper().strip()
    t = str(tipo or '').upper().strip()
    idv = str(id_val or '').strip()

    if 'C.O.P' in c: return 'L'
    if 'A.O.P' in c: return 'L'
    if 'CITADO A NEGOCIACIÓN' in e or 'CITADO A NEGOCIACION' in e: return 'NG'
    if 'SIN INFORMACIÓN DE PROPIETARIO' in c or 'SIN INFORMACION DE PROPIETARIO' in c: return 'NL'
    if 'EN LEVANTAMIENTO' in e: return 'NL'
    if 'EN LEVANTAMIENTO' in c: return 'NL'
    if 'POSIBLE D.O.T' in c or 'POSIBLE DOT' in c: return 'R'
    if 'LEVANTAMIENTO COMPLETO' in e: return 'NL'
    if 'FEDERAL' in t: return 'NG'
    if 'MUNICIPAL' in t: return 'NG'
    if 'EN NEGOCIACIÓN' in e or 'EN NEGOCIACION' in e or 'PU PACTADO' in e: return 'NG'
    if 'EN PROCESO DE ACERCAMIENTO' in e: return 'NL'
    if 'SIN INFORMACIÓN DE PROPIETARIO' in e or 'SIN INFORMACION DE PROPIETARIO' in e: return 'NL'
    if 'EN PROCESO DE FIRMA COP' in e: return 'NG'
    if 'FIRMADO COP' in e or 'FIRMADO AOT' in e: return 'L'
    if 'EN REVISION PARA POSIBLE DOT' in e or 'EN REVISIÓN PARA POSIBLE DOT' in e: return 'R'
    if not idv or idv == '' or idv.upper() == 'N/A' or idv == 'None': return 'NG'
    return 'NL'


def normalize_nom(nom):
    if nom is None: return None
    nom = str(nom).strip().upper()
    nom = nom.replace('\n', ' ').replace('\r', ' ')
    nom = re.sub(r'\s+', ' ', nom)
    return nom.strip()


def download_gsheet_data():
    """Descarga datos de Google Sheets."""
    url = f'https://docs.google.com/spreadsheets/d/{SHEET_ID}/export?format=csv&gid={GID}'
    print(f"  Descargando Google Sheets...")
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
    """Construye lookup table por nomenclatura e ID."""
    excel_by_nom = {}
    excel_by_id = {}
    for row_data in rows:
        estatus = determinar_estatus(row_data.get('ESTATUS_ACTUAL',''), row_data.get('COP',''), row_data.get('TIPO_PROPIEDAD',''), row_data.get('ID',''))
        nom_norm = normalize_nom(row_data.get('NOMENCLATURA',''))
        id_str = row_data.get('ID','').strip()
        if nom_norm and nom_norm not in ('N/A','S/N','NONE',''):
            if nom_norm not in excel_by_nom: excel_by_nom[nom_norm] = []
            excel_by_nom[nom_norm].append((row_data, estatus))
        if id_str and id_str not in ('N/A','None',''):
            if id_str not in excel_by_id: excel_by_id[id_str] = []
            excel_by_id[id_str].append((row_data, estatus))
    return excel_by_nom, excel_by_id


def find_estatus_for_feature(gpkg_id, gpkg_nom, gpkg_prop, excel_by_nom, excel_by_id):
    """Encuentra el estatus para un feature del GPKG."""
    if gpkg_nom:
        nom_norm = normalize_nom(gpkg_nom)
        if nom_norm in excel_by_nom: return excel_by_nom[nom_norm][0][1], True
    if gpkg_id:
        id_str = str(gpkg_id).strip()
        if id_str in excel_by_id: return excel_by_id[id_str][0][1], True
    if gpkg_nom:
        nom_upper = gpkg_nom.upper()
        variations = set()
        for a,b in [('*','-'),('*','/'),('-','/'),('/','-'),('SVIL','VIL'),('VIL','SVIL'),('SLN','SNL'),('04','4')]:
            variations.add(nom_upper.replace(a,b))
        variations.add(nom_upper.replace('  ',' '))
        variations.add(nom_upper.strip())
        for var in variations:
            if var in excel_by_nom: return excel_by_nom[var][0][1], True
    if gpkg_prop:
        prop_upper = gpkg_prop.upper().strip()
        best_match = None; best_score = 0
        for nom_key, entries in excel_by_nom.items():
            for row_data, est in entries:
                excel_prop = str(row_data.get('PROPIETARIO','') or '').upper().strip()
                if excel_prop and prop_upper:
                    excel_words = set(re.sub(r'[^A-Z0-9 ]',' ',excel_prop).split())
                    gpkg_words = set(re.sub(r'[^A-Z0-9 ]',' ',prop_upper).split())
                    if len(excel_words)>0 and len(gpkg_words)>0:
                        common = excel_words & gpkg_words
                        score = len(common)/max(len(excel_words),len(gpkg_words))
                        if score>best_score: best_score=score; best_match=est
        if best_score>=0.3: return best_match, True
    return None, False


def export_geojson_via_sqlite(gpkg_path):
    """Exporta GeoJSON desde GPKG usando sqlite3 (sin dependencia de ogr2ogr)."""
    print(f"  Exportando GeoJSON con sqlite3...")
    
    conn = sqlite3.connect(gpkg_path)
    cursor = conn.cursor()
    
    # Obtener nombre de la tabla de features
    cursor.execute("SELECT table_name FROM gpkg_contents WHERE data_type='features'")
    table_name = cursor.fetchone()[0]
    
    # Obtener nombre de la columna de geometría
    cursor.execute("SELECT column_name FROM gpkg_geometry_columns WHERE table_name=?", (table_name,))
    geom_col = cursor.fetchone()[0]
    
    # Obtener SRID
    cursor.execute("SELECT srs_id FROM gpkg_geometry_columns WHERE table_name=?", (table_name,))
    srs_id = cursor.fetchone()[0]
    
    # Obtener nombres de columnas (excluyendo geometría)
    cursor.execute(f"PRAGMA table_info(\"{table_name}\")")
    columns = [row[1] for row in cursor.fetchall() if row[1] != geom_col]
    
    # Obtener todas las filas
    col_names = ', '.join(f'"{c}"' for c in columns)
    cursor.execute(f'SELECT {col_names}, "{geom_col}" FROM "{table_name}"')
    
    features = []
    for row in cursor.fetchall():
        props = {}
        for i, col in enumerate(columns):
            val = row[i]
            if val is None:
                props[col] = ''
            elif isinstance(val, str):
                props[col] = val.strip()
            else:
                props[col] = str(val)
        
        geom_blob = row[-1]
        if geom_blob:
            geojson_geom = blob_to_geojson(geom_blob, srs_id)
            if geojson_geom:
                features.append({
                    "type": "Feature",
                    "properties": props,
                    "geometry": geojson_geom
                })
    
    conn.close()
    
    geojson = {
        "type": "FeatureCollection",
        "features": features
    }
    
    print(f"  Features exportados: {len(features)}")
    return geojson


def blob_to_geojson(blob, srs_id):
    """Convierte un blob GeoPackage en geometría GeoJSON."""
    import struct
    
    try:
        # GPKG Geometry Encoding: https://www.geopackage.org/spec/#gpb_format
        # Bytes 0-1: Magic 'GP'
        if blob[0:2] != b'GP':
            return None
        
        # Byte 3: Flags
        flags = blob[3]
        
        # Bits 0-1: Geometry type
        # Bit 2: Empty geometry
        # Bit 3: Empty flag
        # Bits 4-5: Envelope type (0=none, 1=xy, 2=xyz, 3=xym, 4=xyzm)
        envelope_type = (flags >> 1) & 0x07
        has_srid = bool(flags & 0x08)
        
        offset = 8  # Skip GP header (8 bytes)
        
        if has_srid:
            srid = struct.unpack_from('<I', blob, offset)[0]
            offset += 4
        
        # Skip envelope
        env_sizes = {0: 0, 1: 32, 2: 48, 3: 48, 4: 64}
        env_size = env_sizes.get(envelope_type, 0)
        offset += env_size
        
        # Now we have WKB geometry
        wkb = blob[offset:]
        
        # Parse WKB
        return wkb_to_geojson(wkb)
    
    except Exception as e:
        print(f"  Error convirtiendo blob: {e}")
        return None


def wkb_to_geojson(wkb):
    """Convierte WKB a geometría GeoJSON."""
    import struct
    
    if len(wkb) < 5:
        return None
    
    byte_order = wkb[0]
    endian = '<' if byte_order == 1 else '>'
    
    geom_type = struct.unpack_from(endian + 'I', wkb, 1)[0]
    base_type = geom_type & 0xFFFF
    
    offset = 5
    
    if base_type == 1:  # Point
        x, y = struct.unpack_from(endian + 'dd', wkb, offset)
        return {"type": "Point", "coordinates": [round(x, 6), round(y, 6)]}
    
    elif base_type == 2:  # LineString
        num_points = struct.unpack_from(endian + 'I', wkb, offset)[0]
        offset += 4
        coords = []
        for _ in range(num_points):
            x, y = struct.unpack_from(endian + 'dd', wkb, offset)
            coords.append([round(x, 6), round(y, 6)])
            offset += 16
        return {"type": "LineString", "coordinates": coords}
    
    elif base_type == 3:  # Polygon
        num_rings = struct.unpack_from(endian + 'I', wkb, offset)[0]
        offset += 4
        rings = []
        for _ in range(num_rings):
            num_points = struct.unpack_from(endian + 'I', wkb, offset)[0]
            offset += 4
            ring = []
            for _ in range(num_points):
                x, y = struct.unpack_from(endian + 'dd', wkb, offset)
                ring.append([round(x, 6), round(y, 6)])
                offset += 16
            rings.append(ring)
        return {"type": "Polygon", "coordinates": rings}
    
    elif base_type == 4:  # MultiPoint
        num_geoms = struct.unpack_from(endian + 'I', wkb, offset)[0]
        offset += 4
        points = []
        for _ in range(num_geoms):
            pt = wkb_to_geojson(wkb[offset:])
            if pt and pt['type'] == 'Point':
                points.append(pt['coordinates'])
            offset += _get_wkb_length(wkb[offset:])
        return {"type": "MultiPoint", "coordinates": points}
    
    elif base_type == 5:  # MultiLineString
        num_geoms = struct.unpack_from(endian + 'I', wkb, offset)[0]
        offset += 4
        lines = []
        for _ in range(num_geoms):
            line = wkb_to_geojson(wkb[offset:])
            if line and line['type'] == 'LineString':
                lines.append(line['coordinates'])
            offset += _get_wkb_length(wkb[offset:])
        return {"type": "MultiLineString", "coordinates": lines}
    
    elif base_type == 6:  # MultiPolygon
        num_geoms = struct.unpack_from(endian + 'I', wkb, offset)[0]
        offset += 4
        polys = []
        for _ in range(num_geoms):
            poly = wkb_to_geojson(wkb[offset:])
            if poly and poly['type'] == 'Polygon':
                polys.append(poly['coordinates'])
            offset += _get_wkb_length(wkb[offset:])
        return {"type": "MultiPolygon", "coordinates": polys}
    
    return None


def _get_wkb_length(wkb):
    """Estima la longitud de un WKB geometry."""
    import struct
    
    if len(wkb) < 5:
        return len(wkb)
    
    byte_order = wkb[0]
    endian = '<' if byte_order == 1 else '>'
    geom_type = struct.unpack_from(endian + 'I', wkb, 1)[0]
    base_type = geom_type & 0xFFFF
    offset = 5
    
    if base_type == 1:  # Point
        return offset + 16
    
    elif base_type in (2, 3):  # LineString or Polygon
        num = struct.unpack_from(endian + 'I', wkb, offset)[0]
        offset += 4
        if base_type == 2:  # LineString
            return offset + num * 16
        else:  # Polygon
            for _ in range(num):
                npts = struct.unpack_from(endian + 'I', wkb, offset)[0]
                offset += 4 + npts * 16
            return offset
    
    elif base_type in (4, 5, 6):  # Multi geometries
        num = struct.unpack_from(endian + 'I', wkb, offset)[0]
        offset += 4
        for _ in range(num):
            sub_len = _get_wkb_length(wkb[offset:])
            offset += sub_len
        return offset
    
    return len(wkb)


def assign_estatus_to_geojson(geojson_data, excel_by_nom, excel_by_id):
    """Asigna estatus a cada feature del GeoJSON."""
    for feature in geojson_data.get('features', []):
        props = feature.get('properties', {})
        gpkg_id = props.get('ID', '')
        gpkg_nom = props.get('NOMENCALTURA', '')
        gpkg_prop = props.get('NOMBRE DE PROPIETARIO', '')
        gpkg_estatus1 = props.get('ESTATUS 1', '')
        
        estatus, was_matched = find_estatus_for_feature(gpkg_id, gpkg_nom, gpkg_prop, excel_by_nom, excel_by_id)
        if not was_matched:
            estatus = gpkg_estatus1 or 'NL'
        
        props['ESTATUS 1'] = estatus
        props['COLOR'] = COLORES.get(estatus, "#FF0000")
        props['COLOR_RGBA'] = COLORES_RGBA.get(estatus, "#FF0000FF")
        props['COLOR_RGB'] = COLORES_RGB.get(estatus, "255,0,0")
    
    return geojson_data


def build_table_data(rows):
    """Construye datos de tabla desde Google Sheets con estatus determinado."""
    table_data = []
    for row_data in rows:
        estatus = determinar_estatus(row_data.get('ESTATUS_ACTUAL',''), row_data.get('COP',''), row_data.get('TIPO_PROPIEDAD',''), row_data.get('ID',''))
        estatus_label = {'L':'Liberado','NL':'No Liberado','NG':'Negociación','R':'Revisión'}.get(estatus, estatus)
        color = COLORES.get(estatus, "#FF0000")
        entry = {
            "PK": row_data.get('PK',''), "ID": row_data.get('ID',''),
            "NOMENCLATURA": row_data.get('NOMENCLATURA',''), "PROPIETARIO": row_data.get('PROPIETARIO',''),
            "ESTATUS_ACTUAL": row_data.get('ESTATUS_ACTUAL',''), "Segmento": row_data.get('Segmento',''),
            "ESTATUS_1": estatus, "ESTATUS_LABEL": estatus_label, "COLOR": color,
            "TIPO_PROPIEDAD": row_data.get('TIPO_PROPIEDAD',''), "COP": row_data.get('COP',''),
        }
        table_data.append(entry)
    return table_data


def generate_html(geojson_data, table_data):
    """Genera el HTML completo con datos embebidos."""
    geojson_json = json.dumps(geojson_data, ensure_ascii=False)
    table_json = json.dumps(table_data, ensure_ascii=False)
    timestamp = get_timestamp()

    html = f'''<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Geoportal V7 - Predios</title>
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" />
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<style>
*{{margin:0;padding:0;box-sizing:border-box}}
html,body{{height:100%;font-family:'Segoe UI',Tahoma,Geneva,Verdana,sans-serif}}
#app{{display:flex;height:100vh;width:100vw}}
#map-container{{flex:1;position:relative;min-width:0}}
#map{{width:100%;height:100%}}
#panel-derecho{{width:480px;min-width:380px;max-width:600px;display:flex;flex-direction:column;background:#f5f5f5;border-left:2px solid #ddd}}
#panel-header{{padding:12px 16px;background:#2c3e50;color:white;display:flex;justify-content:space-between;align-items:center}}
#panel-header h2{{font-size:16px;font-weight:600}}
#panel-header .count{{font-size:13px;background:rgba(255,255,255,0.2);padding:2px 10px;border-radius:12px}}
#filtros{{padding:10px 16px;background:white;border-bottom:1px solid #ddd;display:flex;gap:10px;flex-wrap:wrap;align-items:center}}
#filtros label{{font-size:12px;font-weight:600;color:#555}}
#filtros select,#filtros input{{padding:5px 8px;border:1px solid #ccc;border-radius:4px;font-size:13px}}
#filtros select{{min-width:120px}}
#filtros input{{flex:1;min-width:100px}}
.filtro-grupo{{display:flex;align-items:center;gap:4px}}
#tabla-container{{flex:1;overflow-y:auto;overflow-x:hidden}}
#tabla{{width:100%;border-collapse:collapse;font-size:12px}}
#tabla thead{{position:sticky;top:0;z-index:1}}
#tabla th{{background:#34495e;color:white;padding:8px 6px;text-align:left;font-weight:600;font-size:11px;white-space:nowrap}}
#tabla td{{padding:6px;border-bottom:1px solid rgba(0,0,0,0.1);cursor:pointer;transition:background 0.15s}}
#tabla tr:hover td{{filter:brightness(0.95)}}
#tabla tr.seleccionado td{{outline:3px solid #FF5722;outline-offset:-2px}}
.estatus-badge{{display:inline-block;padding:2px 8px;border-radius:10px;font-size:11px;font-weight:600;color:white;text-shadow:0 1px 2px rgba(0,0,0,0.3)}}
#leyenda{{position:absolute;bottom:20px;left:20px;background:white;padding:10px 14px;border-radius:6px;box-shadow:0 2px 8px rgba(0,0,0,0.2);z-index:1000;font-size:12px}}
#leyenda h4{{margin-bottom:6px;font-size:13px;color:#333}}
.leyenda-item{{display:flex;align-items:center;gap:8px;margin:3px 0}}
.leyenda-color{{width:16px;height:16px;border-radius:3px;border:1px solid rgba(0,0,0,0.2)}}
#buscador-mapa{{position:absolute;top:10px;left:10px;z-index:1000;background:white;padding:8px 12px;border-radius:6px;box-shadow:0 2px 8px rgba(0,0,0,0.2);display:flex;gap:6px;align-items:center}}
#buscador-mapa input{{padding:6px 10px;border:1px solid #ccc;border-radius:4px;font-size:13px;width:200px}}
#buscador-mapa button{{padding:6px 12px;background:#2c3e50;color:white;border:none;border-radius:4px;cursor:pointer;font-size:13px}}
#buscador-mapa button:hover{{background:#34495e}}
.custom-tooltip{{background:white;border:none;box-shadow:0 2px 8px rgba(0,0,0,0.3);border-radius:6px;padding:8px 12px;font-size:13px}}
.custom-tooltip::before{{border-top-color:white!important}}
@media(max-width:900px){{#app{{flex-direction:column}}#panel-derecho{{width:100%;max-width:100%;min-width:0;height:40vh;border-left:none;border-top:2px solid #ddd}}#map-container{{height:60vh}}}}
#ultima-actualizacion{{position:absolute;bottom:20px;right:20px;background:rgba(255,255,255,0.9);padding:6px 12px;border-radius:4px;font-size:11px;color:#666;z-index:1000;box-shadow:0 1px 4px rgba(0,0,0,0.15)}}
</style>
</head>
<body>
<div id="app">
<div id="map-container">
<div id="map"></div>
<div id="buscador-mapa">
<input type="text" id="search-input" placeholder="Buscar por ID o Nomenclatura..." />
<button onclick="buscarPredio()">🔍</button>
</div>
<div id="leyenda">
<h4>Estatus</h4>
<div class="leyenda-item"><div class="leyenda-color" style="background:#00FF00"></div><span>L - Liberado</span></div>
<div class="leyenda-item"><div class="leyenda-color" style="background:#FF0000"></div><span>NL - No Liberado</span></div>
<div class="leyenda-item"><div class="leyenda-color" style="background:#FFFF00"></div><span>NG - Negociaci\u00f3n</span></div>
<div class="leyenda-item"><div class="leyenda-color" style="background:#A0522D"></div><span>R - Revisi\u00f3n</span></div>
</div>
<div id="ultima-actualizacion">🔄 Actualizado: {timestamp}</div>
</div>
<div id="panel-derecho">
<div id="panel-header"><h2>📋 Predios</h2><span class="count" id="total-count">0</span></div>
<div id="filtros">
<div class="filtro-grupo"><label>Segmento:</label><select id="filtro-segmento" onchange="aplicarFiltros()"><option value="">Todos</option></select></div>
<div class="filtro-grupo"><label>Estatus:</label><select id="filtro-estatus" onchange="aplicarFiltros()"><option value="">Todos</option><option value="L">L - Liberado</option><option value="NL">NL - No Liberado</option><option value="NG">NG - Negociaci\u00f3n</option><option value="R">R - Revisi\u00f3n</option></select></div>
<div class="filtro-grupo" style="flex:1"><label>Buscar:</label><input type="text" id="filtro-buscar" placeholder="ID o Nomenclatura..." oninput="aplicarFiltros()" /></div>
</div>
<div id="tabla-container">
<table id="tabla"><thead><tr><th>PK</th><th>ID</th><th>NOMENCLATURA</th><th>PROPIETARIO</th><th>ESTATUS</th></tr></thead><tbody id="tabla-body"></tbody></table>
</div>
</div>
</div>
<script>
const PREDIOS_GEOJSON = {geojson_json};
const DATOS_TABLA = {table_json};
const COLORES = {{'L':'#00FF00','NL':'#FF0000','NG':'#FFFF00','R':'#A0522D'}};
const ETIQUETAS = {{'L':'Liberado','NL':'No Liberado','NG':'Negociaci\u00f3n','R':'Revisi\u00f3n'}};
const COLORES_FONDO = {{'L':'#DFF0D8','NL':'#F2DEDE','NG':'#FCF8E3','R':'#D6C8B0'}};
const COLORES_TEXTO = {{'L':'#3C763D','NL':'#A94442','NG':'#8A6D3B','R':'#5C3A1E'}};
let map,layerGrupo=null;
function initMap(){{
map=L.map('map',{{center:[20.72,-100.35],zoom:10,zoomControl:true}});
L.tileLayer('https://{{s}}.tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png',{{attribution:'&copy; OpenStreetMap contributors',maxZoom:19}}).addTo(map);
const baseMaps={{'Satelital':L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{{z}}/{{y}}/{{x}}',{{attribution:'&copy; Esri',maxZoom:19}}),'Calles':L.tileLayer('https://{{s}}.tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png',{{attribution:'&copy; OpenStreetMap',maxZoom:19}})}};
L.control.layers(baseMaps,null,{{position:'topright'}}).addTo(map);
renderizarMapa();renderizarTabla();llenarFiltros();
}}
function renderizarMapa(){{
layerGrupo=L.geoJSON(PREDIOS_GEOJSON,{{
style:function(feature){{const e=feature.properties["ESTATUS 1"]||'NL';return{{fillColor:COLORES[e]||'#CCCCCC',color:'#000000',weight:1,opacity:0.8,fillOpacity:0.4}}}},
onEachFeature:function(feature,layer){{
const p=feature.properties;const e=p["ESTATUS 1"]||'NL';
layer.bindTooltip('<strong>ID: '+(p.ID||'N/A')+'</strong><br><small>'+(p.NOMENCALTURA||'')+'</small><br><span style="color:'+COLORES[e]+'">\u25cf</span> '+ETIQUETAS[e],{{className:'custom-tooltip',direction:'center'}});
layer.on('click',function(){{seleccionarEnTabla(p.ID||p.NOMENCALTURA||'');map.fitBounds(layer.getBounds(),{{padding:[30,30]}})}});
}}}}).addTo(map);
map.fitBounds(layerGrupo.getBounds(),{{padding:[30,30]}});
}}
function renderizarTabla(filtrados){{
const datos=filtrados||DATOS_TABLA;const tbody=document.getElementById('tabla-body');
if(datos.length===0){{tbody.innerHTML='<tr><td colspan="5" style="text-align:center;padding:20px;color:#999">Sin resultados</td></tr>';document.getElementById('total-count').textContent='0';return;}}
let html='';
datos.forEach(function(row){{
const e=row.ESTATUS_1||'NL';const cf=COLORES_FONDO[e]||'#FFFFFF';const ct=COLORES_TEXTO[e]||'#333333';const cb=COLORES[e]||'#CCCCCC';
html+='<tr style="background:'+cf+';color:'+ct+'" onclick="seleccionarEnMapa(\\''+(row.ID||'')+'\\',\\''+(row.NOMENCLATURA||'')+'\\')"><td>'+(row.PK||'')+'</td><td><strong>'+(row.ID||'')+'</strong></td><td>'+(row.NOMENCLATURA||'')+'</td><td style="max-width:150px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">'+(row.PROPIETARIO||'')+'</td><td><span class="estatus-badge" style="background:'+cb+'">'+e+'</span></td></tr>';
}});
tbody.innerHTML=html;document.getElementById('total-count').textContent=datos.length;
}}
function llenarFiltros(){{
const s=new Set();DATOS_TABLA.forEach(function(r){{if(r.Segmento)s.add(r.Segmento)}});
const sel=document.getElementById('filtro-segmento');Array.from(s).sort().forEach(function(seg){{const o=document.createElement('option');o.value=seg;o.textContent=seg;sel.appendChild(o)}});
}}
function aplicarFiltros(){{
const seg=document.getElementById('filtro-segmento').value;
const est=document.getElementById('filtro-estatus').value;
const bus=document.getElementById('filtro-buscar').value.toLowerCase().trim();
let f=DATOS_TABLA;if(seg)f=f.filter(function(r){{return r.Segmento===seg}});if(est)f=f.filter(function(r){{return r.ESTATUS_1===est}});if(bus)f=f.filter(function(r){{return(r.ID&&r.ID.toLowerCase().includes(bus))||(r.NOMENCLATURA&&r.NOMENCLATURA.toLowerCase().includes(bus))||(r.PROPIETARIO&&r.PROPIETARIO.toLowerCase().includes(bus))}});
renderizarTabla(f);filtrarMapa(f);
}}
function filtrarMapa(filtrados){{
if(!layerGrupo)return;const ids=new Set(),noms=new Set();
filtrados.forEach(function(r){{if(r.ID)ids.add(r.ID);if(r.NOMENCLATURA)noms.add(r.NOMENCLATURA)}});
layerGrupo.eachLayer(function(layer){{const p=layer.feature.properties;const id=p.ID||'',nom=p.NOMENCALTURA||'';const v=ids.has(id)||noms.has(nom);if(v){{if(!map.hasLayer(layer))layer.addTo(map);layer.setStyle({{opacity:0.8,fillOpacity:0.4}})}}else{{layer.setStyle({{opacity:0.1,fillOpacity:0.05}})}}}});
}}
function seleccionarEnMapa(id,nom){{
if(!layerGrupo)return;let encontrado=false;
layerGrupo.eachLayer(function(layer){{
const p=layer.feature.properties;
if((id&&p.ID===id)||(nom&&p.NOMENCALTURA===nom)){{layer.setStyle({{weight:3,color:'#FF5722',opacity:1,fillOpacity:0.6}});map.fitBounds(layer.getBounds(),{{padding:[30,30]}});layer.openTooltip();encontrado=true}}
else{{const e=p["ESTATUS 1"]||'NL';layer.setStyle({{fillColor:COLORES[e]||'#CCCCCC',color:'#000000',weight:1,opacity:0.8,fillOpacity:0.4}})}}
}});
if(!encontrado)alert('Predio no encontrado en el mapa. Puede que no tenga pol\u00edgono.');
}}
function seleccionarEnTabla(id){{
document.querySelectorAll('#tabla tr.seleccionado').forEach(function(el){{el.classList.remove('seleccionado')}});
const filas=document.querySelectorAll('#tabla tbody tr');
filas.forEach(function(fila){{const c=fila.cells[1];if(c&&c.textContent.trim()===id){{fila.classList.add('seleccionado');fila.scrollIntoView({{behavior:'smooth',block:'center'}})}}}});
}}
function buscarPredio(){{
const q=document.getElementById('search-input').value.trim();if(!q)return;
const m=DATOS_TABLA.find(function(row){{return row.ID===q||row.NOMENCLATURA===q}});
if(m){{seleccionarEnMapa(m.ID,m.NOMENCLATURA);seleccionarEnTabla(m.ID)}}
else{{const p=DATOS_TABLA.find(function(row){{return(row.ID&&row.ID.toLowerCase().includes(q.toLowerCase()))||(row.NOMENCLATURA&&row.NOMENCLATURA.toLowerCase().includes(q.toLowerCase()))}});if(p){{seleccionarEnMapa(p.ID,p.NOMENCLATURA);seleccionarEnTabla(p.ID)}}else alert('No se encontr\u00f3 ning\u00fan predio con ese ID o Nomenclatura')}}
}}
document.addEventListener('DOMContentLoaded',function(){{document.getElementById('search-input').addEventListener('keypress',function(e){{if(e.key==='Enter')buscarPredio()}})}});
initMap();
</script>
</body>
</html>'''

    return html


def main():
    print("=" * 60)
    print("GENERADOR GEOPORTAL V7 - CI/CD")
    print("=" * 60)
    print()

    if not os.path.exists(GPKG_PATH):
        print(f"ERROR: No se encuentra {GPKG_PATH}")
        sys.exit(1)

    size_mb = os.path.getsize(GPKG_PATH) / (1024 * 1024)
    print(f"GPKG encontrado: {size_mb:.1f} MB")

    print("\nDescargando Google Sheets...")
    try:
        rows = download_gsheet_data()
        print(f"  Descargadas {len(rows)} filas")
    except Exception as e:
        print(f"ERROR al descargar Google Sheets: {e}")
        sys.exit(1)

    print("\nConstruyendo lookup table...")
    excel_by_nom, excel_by_id = build_excel_lookup(rows)
    print(f"  Nomenclaturas: {len(excel_by_nom)}, IDs: {len(excel_by_id)}")

    print("\nExportando GeoJSON desde GPKG...")
    try:
        geojson_data = export_geojson_via_sqlite(GPKG_PATH)
    except Exception as e:
        print(f"ERROR al exportar GeoJSON: {e}")
        sys.exit(1)

    print("\nAsignando estatus a features...")
    geojson_data = assign_estatus_to_geojson(geojson_data, excel_by_nom, excel_by_id)
    
    # Contar distribución
    dist = {}
    for feat in geojson_data.get('features', []):
        e = feat['properties'].get('ESTATUS 1', 'NL')
        dist[e] = dist.get(e, 0) + 1
    print(f"  Distribución: {dist}")

    print("\nConstruyendo datos de tabla...")
    table_data = build_table_data(rows)
    print(f"  Filas: {len(table_data)}")

    print("\nGenerando HTML...")
    html = generate_html(geojson_data, table_data)

    os.makedirs(os.path.dirname(OUTPUT_HTML), exist_ok=True)
    with open(OUTPUT_HTML, 'w', encoding='utf-8') as f:
        f.write(html)
    print(f"  HTML generado: {OUTPUT_HTML} ({len(html)} bytes)")

    print("\n" + "=" * 60)
    print("COMPLETADO")
    print("=" * 60)


if __name__ == '__main__':
    main()
