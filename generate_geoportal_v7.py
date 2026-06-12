#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Genera el geoportal V7 (index.html) con datos actualizados desde Google Sheets.
Los datos GeoJSON y de tabla se EMBEBEN directamente en el HTML.
Esto permite publicar en GitHub Pages como sitio estático.

USO:
  python3 generate_geoportal_v7.py

Requiere:
  pip install requests
"""

import requests
import csv
import io
import json
import sqlite3
import os
import re
import sys
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
    """Obtiene timestamp actual formateado."""
    return datetime.now().strftime("%d/%m/%Y %H:%M")


def determinar_estatus(estatus, cop, tipo, id_val):
    """Determina la categoría (L, NL, NG, R) según reglas de formato condicional."""
    e = str(estatus or '').upper().strip()
    c = str(cop or '').upper().strip()
    t = str(tipo or '').upper().strip()
    idv = str(id_val or '').strip()

    # 1. C.O.P → VERDE (L)
    if 'C.O.P' in c:
        return 'L'
    # 2. A.O.P → VERDE (L)
    if 'A.O.P' in c:
        return 'L'
    # 3. Citado a Negociación → AMARILLO (NG)
    if 'CITADO A NEGOCIACIÓN' in e or 'CITADO A NEGOCIACION' in e:
        return 'NG'
    # 4. Sin información de propietario → ROJO (NL)
    if 'SIN INFORMACIÓN DE PROPIETARIO' in c or 'SIN INFORMACION DE PROPIETARIO' in c:
        return 'NL'
    # 5. En Levantamiento → ROJO (NL)
    if 'EN LEVANTAMIENTO' in e:
        return 'NL'
    # 6. En Levantamiento → ROJO (NL)
    if 'EN LEVANTAMIENTO' in c:
        return 'NL'
    # 7. POSIBLE D.O.T → CAFÉ (R)
    if 'POSIBLE D.O.T' in c or 'POSIBLE DOT' in c:
        return 'R'
    # 8. Levantamiento completo → ROJO (NL)
    if 'LEVANTAMIENTO COMPLETO' in e:
        return 'NL'
    # 9. Federal → AMARILLO (NG)
    if 'FEDERAL' in t:
        return 'NG'
    # 10. Municipal → AMARILLO (NG)
    if 'MUNICIPAL' in t:
        return 'NG'
    # 11. En negociación/PU Pactado → AMARILLO (NG)
    if 'EN NEGOCIACIÓN' in e or 'EN NEGOCIACION' in e or 'PU PACTADO' in e:
        return 'NG'
    # 12. En proceso de Acercamiento → ROJO (NL)
    if 'EN PROCESO DE ACERCAMIENTO' in e:
        return 'NL'
    # 13. Sin información de propietario → ROJO (NL)
    if 'SIN INFORMACIÓN DE PROPIETARIO' in e or 'SIN INFORMACION DE PROPIETARIO' in e:
        return 'NL'
    # 14. En proceso de firma COP → AMARILLO (NG)
    if 'EN PROCESO DE FIRMA COP' in e:
        return 'NG'
    # 15. Firmado COP/AOT → VERDE (L)
    if 'FIRMADO COP' in e or 'FIRMADO AOT' in e:
        return 'L'
    # 16. En revisión para posible DOT → CAFÉ (R)
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
    """Encuentra el estatus para un feature del GPKG."""
    if gpkg_nom:
        nom_norm = normalize_nom(gpkg_nom)
        if nom_norm in excel_by_nom:
            return excel_by_nom[nom_norm][0][1], True

    if gpkg_id:
        id_str = str(gpkg_id).strip()
        if id_str in excel_by_id:
            return excel_by_id[id_str][0][1], True

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
                return excel_by_nom[var][0][1], True

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
            return best_match, True

    return None, False


def export_geojson_from_gpkg(gpkg_path, rows, excel_by_nom, excel_by_id):
    """Exporta GeoJSON desde GPKG con estatus actualizados."""
    conn = sqlite3.connect(gpkg_path)
    cursor = conn.cursor()

    cursor.execute("SELECT table_name FROM gpkg_contents WHERE data_type='features'")
    table_name = cursor.fetchone()[0]

    cursor.execute(f'SELECT fid, ID, NOMENCALTURA, "NOMBRE DE PROPIETARIO", "ESTATUS 1", AsGeoJSON(geom) FROM "{table_name}" ORDER BY fid')
    features = cursor.fetchall()
    conn.close()

    geojson_features = []
    for feat in features:
        fid, gpkg_id, gpkg_nom, gpkg_prop, gpkg_estatus1, geom_json = feat
        if not geom_json:
            continue

        estatus, was_matched = find_estatus_for_feature(gpkg_id, gpkg_nom, gpkg_prop, excel_by_nom, excel_by_id)
        if not was_matched:
            estatus = gpkg_estatus1 or 'NL'

        color = COLORES.get(estatus, "#FF0000")
        color_rgba = COLORES_RGBA.get(estatus, "#FF0000FF")
        color_rgb = COLORES_RGB.get(estatus, "255,0,0")

        feature = {
            "type": "Feature",
            "properties": {
                "ID": gpkg_id or '',
                "NOMENCALTURA": gpkg_nom or '',
                "ESTATUS 1": estatus,
                "NOMBRE DE PROPIETARIO": gpkg_prop or '',
                "COLOR": color,
                "COLOR_RGBA": color_rgba,
                "COLOR_RGB": color_rgb,
            },
            "geometry": json.loads(geom_json)
        }
        geojson_features.append(feature)

    return {
        "type": "FeatureCollection",
        "features": geojson_features
    }


def build_table_data(rows):
    """Construye datos de tabla desde Google Sheets con estatus determinado."""
    table_data = []
    for row_data in rows:
        estatus = determinar_estatus(
            row_data.get('ESTATUS_ACTUAL', ''),
            row_data.get('COP', ''),
            row_data.get('TIPO_PROPIEDAD', ''),
            row_data.get('ID', '')
        )

        estatus_label = {
            'L': 'Liberado',
            'NL': 'No Liberado',
            'NG': 'Negociación',
            'R': 'Revisión'
        }.get(estatus, estatus)

        color = COLORES.get(estatus, "#FF0000")

        entry = {
            "PK": row_data.get('PK', ''),
            "ID": row_data.get('ID', ''),
            "NOMENCLATURA": row_data.get('NOMENCLATURA', ''),
            "PROPIETARIO": row_data.get('PROPIETARIO', ''),
            "ESTATUS_ACTUAL": row_data.get('ESTATUS_ACTUAL', ''),
            "Segmento": row_data.get('Segmento', ''),
            "ESTATUS_1": estatus,
            "ESTATUS_LABEL": estatus_label,
            "COLOR": color,
            "TIPO_PROPIEDAD": row_data.get('TIPO_PROPIEDAD', ''),
            "COP": row_data.get('COP', ''),
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
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        html, body {{ height: 100%; font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; }}
        #app {{ display: flex; height: 100vh; width: 100vw; }}
        #map-container {{ flex: 1; position: relative; min-width: 0; }}
        #map {{ width: 100%; height: 100%; }}
        #panel-derecho {{ width: 480px; min-width: 380px; max-width: 600px; display: flex; flex-direction: column; background: #f5f5f5; border-left: 2px solid #ddd; }}
        #panel-header {{ padding: 12px 16px; background: #2c3e50; color: white; display: flex; justify-content: space-between; align-items: center; }}
        #panel-header h2 {{ font-size: 16px; font-weight: 600; }}
        #panel-header .count {{ font-size: 13px; background: rgba(255,255,255,0.2); padding: 2px 10px; border-radius: 12px; }}
        #filtros {{ padding: 10px 16px; background: white; border-bottom: 1px solid #ddd; display: flex; gap: 10px; flex-wrap: wrap; align-items: center; }}
        #filtros label {{ font-size: 12px; font-weight: 600; color: #555; }}
        #filtros select, #filtros input {{ padding: 5px 8px; border: 1px solid #ccc; border-radius: 4px; font-size: 13px; }}
        #filtros select {{ min-width: 120px; }}
        #filtros input {{ flex: 1; min-width: 100px; }}
        .filtro-grupo {{ display: flex; align-items: center; gap: 4px; }}
        #tabla-container {{ flex: 1; overflow-y: auto; overflow-x: hidden; }}
        #tabla {{ width: 100%; border-collapse: collapse; font-size: 12px; }}
        #tabla thead {{ position: sticky; top: 0; z-index: 1; }}
        #tabla th {{ background: #34495e; color: white; padding: 8px 6px; text-align: left; font-weight: 600; font-size: 11px; white-space: nowrap; }}
        #tabla td {{ padding: 6px; border-bottom: 1px solid rgba(0,0,0,0.1); cursor: pointer; transition: background 0.15s; }}
        #tabla tr:hover td {{ filter: brightness(0.95); }}
        #tabla tr.seleccionado td {{ outline: 3px solid #FF5722; outline-offset: -2px; }}
        .estatus-badge {{ display: inline-block; padding: 2px 8px; border-radius: 10px; font-size: 11px; font-weight: 600; color: white; text-shadow: 0 1px 2px rgba(0,0,0,0.3); }}
        #leyenda {{ position: absolute; bottom: 20px; left: 20px; background: white; padding: 10px 14px; border-radius: 6px; box-shadow: 0 2px 8px rgba(0,0,0,0.2); z-index: 1000; font-size: 12px; }}
        #leyenda h4 {{ margin-bottom: 6px; font-size: 13px; color: #333; }}
        .leyenda-item {{ display: flex; align-items: center; gap: 8px; margin: 3px 0; }}
        .leyenda-color {{ width: 16px; height: 16px; border-radius: 3px; border: 1px solid rgba(0,0,0,0.2); }}
        #buscador-mapa {{ position: absolute; top: 10px; left: 10px; z-index: 1000; background: white; padding: 8px 12px; border-radius: 6px; box-shadow: 0 2px 8px rgba(0,0,0,0.2); display: flex; gap: 6px; align-items: center; }}
        #buscador-mapa input {{ padding: 6px 10px; border: 1px solid #ccc; border-radius: 4px; font-size: 13px; width: 200px; }}
        #buscador-mapa button {{ padding: 6px 12px; background: #2c3e50; color: white; border: none; border-radius: 4px; cursor: pointer; font-size: 13px; }}
        #buscador-mapa button:hover {{ background: #34495e; }}
        .custom-tooltip {{ background: white; border: none; box-shadow: 0 2px 8px rgba(0,0,0,0.3); border-radius: 6px; padding: 8px 12px; font-size: 13px; }}
        .custom-tooltip::before {{ border-top-color: white !important; }}
        @media (max-width: 900px) {{ #app {{ flex-direction: column; }} #panel-derecho {{ width: 100%; max-width: 100%; min-width: 0; height: 40vh; border-left: none; border-top: 2px solid #ddd; }} #map-container {{ height: 60vh; }} }}
        #ultima-actualizacion {{ position: absolute; bottom: 20px; right: 20px; background: rgba(255,255,255,0.9); padding: 6px 12px; border-radius: 4px; font-size: 11px; color: #666; z-index: 1000; box-shadow: 0 1px 4px rgba(0,0,0,0.15); }}
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
        // ============================================================
        // DATOS EMBEBIDOS - Generados automaticamente desde Google Sheets
        // ============================================================
        const PREDIOS_GEOJSON = {geojson_json};

        const DATOS_TABLA = {table_json};

        // ============================================================
        // CONFIGURACION
        // ============================================================
        const COLORES = {{ 'L': '#00FF00', 'NL': '#FF0000', 'NG': '#FFFF00', 'R': '#A0522D' }};
        const ETIQUETAS = {{ 'L': 'Liberado', 'NL': 'No Liberado', 'NG': 'Negociaci\u00f3n', 'R': 'Revisi\u00f3n' }};
        const COLORES_FONDO = {{ 'L': '#DFF0D8', 'NL': '#F2DEDE', 'NG': '#FCF8E3', 'R': '#D6C8B0' }};
        const COLORES_TEXTO = {{ 'L': '#3C763D', 'NL': '#A94442', 'NG': '#8A6D3B', 'R': '#5C3A1E' }};

        // ============================================================
        // ESTADO GLOBAL
        // ============================================================
        let map, layerGrupo = null;

        // ============================================================
        // INICIALIZAR MAPA
        // ============================================================
        function initMap() {{
            map = L.map('map', {{ center: [20.72, -100.35], zoom: 10, zoomControl: true }});

            L.tileLayer('https://{{s}}.tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png', {{
                attribution: '&copy; OpenStreetMap contributors', maxZoom: 19
            }}).addTo(map);

            const baseMaps = {{
                'Satelital': L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{{z}}/{{y}}/{{x}}', {{
                    attribution: '&copy; Esri', maxZoom: 19
                }}),
                'Calles': L.tileLayer('https://{{s}}.tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png', {{
                    attribution: '&copy; OpenStreetMap', maxZoom: 19
                }})
            }};
            L.control.layers(baseMaps, null, {{position: 'topright'}}).addTo(map);

            renderizarMapa();
            renderizarTabla();
            llenarFiltros();
        }}

        // ============================================================
        // RENDERIZAR MAPA
        // ============================================================
        function renderizarMapa() {{
            layerGrupo = L.geoJSON(PREDIOS_GEOJSON, {{
                style: function(feature) {{
                    const estatus = feature.properties["ESTATUS 1"] || 'NL';
                    const color = COLORES[estatus] || '#CCCCCC';
                    return {{ fillColor: color, color: '#000000', weight: 1, opacity: 0.8, fillOpacity: 0.4 }};
                }},
                onEachFeature: function(feature, layer) {{
                    const props = feature.properties;
                    const estatus = props["ESTATUS 1"] || 'NL';
                    const label = ETIQUETAS[estatus] || estatus;
                    layer.bindTooltip(
                        '<strong>ID: ' + (props.ID || 'N/A') + '</strong><br><small>' + (props.NOMENCALTURA || '') + '</small><br><span style="color:' + COLORES[estatus] + '">\u25cf</span> ' + label,
                        {{ className: 'custom-tooltip', direction: 'center' }}
                    );
                    layer.on('click', function() {{
                        const id = props.ID || props.NOMENCALTURA || '';
                        seleccionarEnTabla(id);
                        map.fitBounds(layer.getBounds(), {{padding: [30, 30]}});
                    }});
                }}
            }}).addTo(map);

            map.fitBounds(layerGrupo.getBounds(), {{padding: [30, 30]}});
        }}

        // ============================================================
        // RENDERIZAR TABLA (orden = Google Sheets)
        // ============================================================
        function renderizarTabla(filtrados) {{
            const datos = filtrados || DATOS_TABLA;
            const tbody = document.getElementById('tabla-body');

            if (datos.length === 0) {{
                tbody.innerHTML = '<tr><td colspan="5" style="text-align:center;padding:20px;color:#999">Sin resultados</td></tr>';
                document.getElementById('total-count').textContent = '0';
                return;
            }}

            let html = '';
            datos.forEach(function(row) {{
                const estatus = row.ESTATUS_1 || 'NL';
                const colorFondo = COLORES_FONDO[estatus] || '#FFFFFF';
                const colorTexto = COLORES_TEXTO[estatus] || '#333333';
                const colorBadge = COLORES[estatus] || '#CCCCCC';
                html += '<tr style="background:' + colorFondo + ';color:' + colorTexto + '" onclick="seleccionarEnMapa(\\'' + (row.ID || '') + '\\', \\'' + (row.NOMENCLATURA || '') + '\\')">' +
                    '<td>' + (row.PK || '') + '</td>' +
                    '<td><strong>' + (row.ID || '') + '</strong></td>' +
                    '<td>' + (row.NOMENCLATURA || '') + '</td>' +
                    '<td style="max-width:150px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">' + (row.PROPIETARIO || '') + '</td>' +
                    '<td><span class="estatus-badge" style="background:' + colorBadge + '">' + estatus + '</span></td></tr>';
            }});

            tbody.innerHTML = html;
            document.getElementById('total-count').textContent = datos.length;
        }}

        // ============================================================
        // FILTROS
        // ============================================================
        function llenarFiltros() {{
            const segmentos = new Set();
            DATOS_TABLA.forEach(function(row) {{ if (row.Segmento) segmentos.add(row.Segmento); }});
            const select = document.getElementById('filtro-segmento');
            Array.from(segmentos).sort().forEach(function(seg) {{
                const opt = document.createElement('option');
                opt.value = seg; opt.textContent = seg; select.appendChild(opt);
            }});
        }}

        function aplicarFiltros() {{
            const segmento = document.getElementById('filtro-segmento').value;
            const estatus = document.getElementById('filtro-estatus').value;
            const buscar = document.getElementById('filtro-buscar').value.toLowerCase().trim();

            let filtrados = DATOS_TABLA;
            if (segmento) filtrados = filtrados.filter(function(r) {{ return r.Segmento === segmento; }});
            if (estatus) filtrados = filtrados.filter(function(r) {{ return r.ESTATUS_1 === estatus; }});
            if (buscar) filtrados = filtrados.filter(function(r) {{
                return (r.ID && r.ID.toLowerCase().includes(buscar)) ||
                       (r.NOMENCLATURA && r.NOMENCLATURA.toLowerCase().includes(buscar)) ||
                       (r.PROPIETARIO && r.PROPIETARIO.toLowerCase().includes(buscar));
            }});

            renderizarTabla(filtrados);
            filtrarMapa(filtrados);
        }}

        function filtrarMapa(filtrados) {{
            if (!layerGrupo) return;
            const idsFiltrados = new Set();
            const nomsFiltrados = new Set();
            filtrados.forEach(function(row) {{ if (row.ID) idsFiltrados.add(row.ID); if (row.NOMENCLATURA) nomsFiltrados.add(row.NOMENCLATURA); }});

            layerGrupo.eachLayer(function(layer) {{
                const props = layer.feature.properties;
                const id = props.ID || '';
                const nom = props.NOMENCALTURA || '';
                const visible = idsFiltrados.has(id) || nomsFiltrados.has(nom);
                if (visible) {{
                    if (!map.hasLayer(layer)) layer.addTo(map);
                    layer.setStyle({{opacity: 0.8, fillOpacity: 0.4}});
                }} else {{
                    layer.setStyle({{opacity: 0.1, fillOpacity: 0.05}});
                }}
            }});
        }}

        // ============================================================
        // SELECCIONAR EN MAPA
        // ============================================================
        function seleccionarEnMapa(id, nom) {{
            if (!layerGrupo) return;
            let encontrado = false;
            layerGrupo.eachLayer(function(layer) {{
                const props = layer.feature.properties;
                if ((id && props.ID === id) || (nom && props.NOMENCALTURA === nom)) {{
                    layer.setStyle({{ weight: 3, color: '#FF5722', opacity: 1, fillOpacity: 0.6 }});
                    map.fitBounds(layer.getBounds(), {{padding: [30, 30]}});
                    layer.openTooltip();
                    encontrado = true;
                }} else {{
                    const estatus = props.ESTATUS_1 || 'NL';
                    const color = COLORES[estatus] || '#CCCCCC';
                    layer.setStyle({{ fillColor: color, color: '#000000', weight: 1, opacity: 0.8, fillOpacity: 0.4 }});
                }}
            }});
            if (!encontrado) alert('Predio no encontrado en el mapa. Puede que no tenga pol\u00edgono.');
        }}

        // ============================================================
        // SELECCIONAR EN TABLA
        // ============================================================
        function seleccionarEnTabla(id) {{
            document.querySelectorAll('#tabla tr.seleccionado').forEach(function(el) {{ el.classList.remove('seleccionado'); }});
            const filas = document.querySelectorAll('#tabla tbody tr');
            filas.forEach(function(fila) {{
                const celda = fila.cells[1];
                if (celda && celda.textContent.trim() === id) {{
                    fila.classList.add('seleccionado');
                    fila.scrollIntoView({{behavior: 'smooth', block: 'center'}});
                }}
            }});
        }}

        // ============================================================
        // BUSCADOR DEL MAPA
        // ============================================================
        function buscarPredio() {{
            const query = document.getElementById('search-input').value.trim();
            if (!query) return;
            const match = DATOS_TABLA.find(function(row) {{ return row.ID === query || row.NOMENCLATURA ===