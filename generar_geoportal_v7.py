#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Genera los archivos para el Geoportal V7.
Convierte el GPKG a GeoJSON (WGS84) y genera datos de tabla
con los estatus calculados DESDE GOOGLE SHEETS (no del GPKG).
"""

import json
import os
import sys
import subprocess
import requests
import csv
import io
import re
import sqlite3

# ============================================================
# CONFIGURACION
# ============================================================
SHEET_ID = '1WY24BYmehH2pjcYyjwNfkdwgKD-4eV41fiDfUyAXyL4'
GID = '1831931870'
GPKG_PATH = 'poligonos_finales_coloreados_v7.gpkg'
OUTPUT_DIR = 'geoportal_v7'
OUTPUT_GEOJSON = os.path.join(OUTPUT_DIR, 'predios.geojson')
OUTPUT_TABLA = os.path.join(OUTPUT_DIR, 'datos_tabla.json')

COLOR_MAP = {'L': '#00FF00', 'NL': '#FF0000', 'NG': '#FFFF00', 'R': '#A0522D'}
LABEL_MAP = {'L': 'Liberado', 'NL': 'No Liberado', 'NG': 'Negociación', 'R': 'Revisión'}


def determinar_estatus(estatus, cop, tipo, id_val):
    """
    Determina la categoría (L, NL, NG, R) según las reglas
    del formato condicional de la tabla de Google Sheets.
    """
    e = str(estatus or '').upper().strip()
    c = str(cop or '').upper().strip()
    t = str(tipo or '').upper().strip()
    idv = str(id_val or '').strip()

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
    resp = requests.get(url, timeout=60)
    resp.raise_for_status()

    reader = csv.reader(io.StringIO(resp.text))
    header = next(reader)
    print(f"  Header: {header}")

    rows = []
    for row in reader:
        if len(row) >= 10:
            est = determinar_estatus(
                row[4].strip() if row[4] else '',
                row[6].strip() if row[6] else '',
                row[9].strip() if row[9] else '',
                row[1].strip() if row[1] else ''
            )
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
                'ESTATUS_1': est,
                'ESTATUS_LABEL': LABEL_MAP.get(est, est),
                'COLOR': COLOR_MAP.get(est, '#CCCCCC'),
            })

    return rows


def build_lookup(rows):
    """Construye lookup por nomenclatura e ID."""
    by_nom = {}
    by_id = {}
    for row_data in rows:
        nom_norm = normalize_nom(row_data.get('NOMENCLATURA', ''))
        id_str = row_data.get('ID', '').strip()
        if nom_norm and nom_norm not in ('N/A', 'S/N', 'NONE', ''):
            by_nom[nom_norm] = row_data
        if id_str and id_str not in ('N/A', 'None', ''):
            by_id[id_str] = row_data
    return by_nom, by_id


def find_sheet_row(gpkg_id, gpkg_nom, gpkg_prop, by_nom, by_id):
    """Busca la fila de Sheets que corresponde a un feature del GPKG."""
    if gpkg_nom:
        nom_norm = normalize_nom(gpkg_nom)
        if nom_norm in by_nom:
            return by_nom[nom_norm]

    if gpkg_id:
        id_str = str(gpkg_id).strip()
        if id_str in by_id:
            return by_id[id_str]

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
            if var in by_nom:
                return by_nom[var]

    if gpkg_prop:
        prop_upper = gpkg_prop.upper().strip()
        best_match = None
        best_score = 0
        for nom_key, row_data in by_nom.items():
            excel_prop = str(row_data.get('PROPIETARIO', '') or '').upper().strip()
            if excel_prop and prop_upper:
                excel_words = set(re.sub(r'[^A-Z0-9 ]', ' ', excel_prop).split())
                gpkg_words = set(re.sub(r'[^A-Z0-9 ]', ' ', prop_upper).split())
                if len(excel_words) > 0 and len(gpkg_words) > 0:
                    common = excel_words & gpkg_words
                    score = len(common) / max(len(excel_words), len(gpkg_words))
                    if score > best_score:
                        best_score = score
                        best_match = row_data
        if best_score >= 0.3:
            return best_match

    return None


def gpkg_to_geojson():
    """Convierte GPKG a GeoJSON usando ogr2ogr."""
    print(f"\n1. Convirtiendo GPKG a GeoJSON...")

    if not os.path.exists(GPKG_PATH):
        print(f"  ERROR: No se encuentra {GPKG_PATH}")
        print(f"  Ejecuta primero: python3 generate_colored_gpkg_v7.py")
        return False

    # Obtener nombre de la tabla de features
    conn = sqlite3.connect(GPKG_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT table_name FROM gpkg_contents WHERE data_type='features'")
    table_name = cursor.fetchone()[0]
    conn.close()

    print(f"  Tabla: {table_name}")

    # Convertir con ogr2ogr
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    cmd = [
        'ogr2ogr', '-f', 'GeoJSON',
        '-t_srs', 'EPSG:4326',
        OUTPUT_GEOJSON,
        GPKG_PATH,
        table_name,
        '-lco', 'COORDINATE_PRECISION=6'
    ]

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"  ERROR en ogr2ogr: {result.stderr}")
        return False

    # Verificar
    with open(OUTPUT_GEOJSON) as f:
        geojson = json.load(f)
    print(f"  {len(geojson['features'])} features convertidos")
    print(f"  Guardado en: {OUTPUT_GEOJSON}")
    return True


def generar_datos_tabla(gsheet_rows, by_nom, by_id):
    """
    Genera datos de tabla usando los estatus de Google Sheets.
    El GeoJSON se usa solo para obtener los polígonos y datos base.
    Los estatus vienen de Google Sheets.
    """
    print(f"\n2. Generando datos de tabla desde Google Sheets...")

    if not os.path.exists(OUTPUT_GEOJSON):
        print(f"  ERROR: No se encuentra {OUTPUT_GEOJSON}")
        return False

    with open(OUTPUT_GEOJSON) as f:
        geojson = json.load(f)

    # Para cada feature del GeoJSON, buscar su estatus en Google Sheets
    datos = []
    stats = {'L': 0, 'NL': 0, 'NG': 0, 'R': 0}
    sin_match = 0

    for feat in geojson['features']:
        props = feat['properties']
        gpkg_id = str(props.get('ID', '') or '')
        gpkg_nom = str(props.get('NOMENCALTURA', '') or '')
        gpkg_prop = str(props.get('NOMBRE DE PROPIETARIO', '') or '')

        # Buscar en Google Sheets
        sheet_row = find_sheet_row(gpkg_id, gpkg_nom, gpkg_prop, by_nom, by_id)

        if sheet_row:
            est = sheet_row['ESTATUS_1']
            estatus_actual = sheet_row.get('ESTATUS_ACTUAL', '')
            segmento = sheet_row.get('Segmento', '')
            tipo_prop = sheet_row.get('TIPO_PROPIEDAD', '')
            cop = sheet_row.get('COP', '')
            pk = sheet_row.get('PK', '')
            propietario = sheet_row.get('PROPIETARIO', '')
            stats[est] = stats.get(est, 0) + 1
        else:
            # Si no hay match en Sheets, usar NL por defecto
            est = 'NL'
            estatus_actual = ''
            segmento = ''
            tipo_prop = ''
            cop = ''
            pk = ''
            propietario = gpkg_prop
            sin_match += 1
            stats['NL'] = stats.get('NL', 0) + 1

        datos.append({
            'PK': pk,
            'ID': gpkg_id,
            'NOMENCLATURA': gpkg_nom,
            'PROPIETARIO': propietario,
            'ESTATUS_ACTUAL': estatus_actual,
            'Segmento': segmento,
            'ESTATUS_1': est,
            'ESTATUS_LABEL': LABEL_MAP.get(est, est),
            'COLOR': COLOR_MAP.get(est, '#CCCCCC'),
            'TIPO_PROPIEDAD': tipo_prop,
            'COP': cop,
        })

    with open(OUTPUT_TABLA, 'w', encoding='utf-8') as f:
        json.dump(datos, f, ensure_ascii=False, indent=2)

    print(f"  {len(datos)} registros generados")
    print(f"  Guardado en: {OUTPUT_TABLA}")
    print(f"  Distribución de estatus (desde Google Sheets):")
    for est in ['L', 'NL', 'NG', 'R']:
        cnt = stats.get(est, 0)
        color_nombre = {'L': 'Verde', 'NL': 'Rojo', 'NG': 'Amarillo', 'R': 'Café'}.get(est, '?')
        print(f"    {est} ({color_nombre}): {cnt}")
    if sin_match:
        print(f"  Sin match en Sheets (usando NL): {sin_match}")
    return True


def actualizar_geojson_con_sheets(gsheet_rows, by_nom, by_id):
    """
    Actualiza las propiedades del GeoJSON con los estatus de Google Sheets.
    Esto asegura que los polígonos se pinten con los colores correctos.
    """
    print(f"\n3. Actualizando GeoJSON con estatus de Google Sheets...")

    if not os.path.exists(OUTPUT_GEOJSON):
        print(f"  ERROR: No se encuentra {OUTPUT_GEOJSON}")
        return False

    with open(OUTPUT_GEOJSON) as f:
        geojson = json.load(f)

    cambios = 0
    sin_match = 0

    for feat in geojson['features']:
        props = feat['properties']
        gpkg_id = str(props.get('ID', '') or '')
        gpkg_nom = str(props.get('NOMENCALTURA', '') or '')
        gpkg_prop = str(props.get('NOMBRE DE PROPIETARIO', '') or '')

        sheet_row = find_sheet_row(gpkg_id, gpkg_nom, gpkg_prop, by_nom, by_id)

        if sheet_row:
            est = sheet_row['ESTATUS_1']
            color = COLOR_MAP.get(est, '#CCCCCC')
            # Actualizar propiedades del GeoJSON
            props['ESTATUS 1'] = est
            props['COLOR'] = color
            props['COLOR_RGBA'] = color + 'FF'
            props['COLOR_RGB'] = {
                'L': '0,255,0',
                'NL': '255,0,0',
                'NG': '255,255,0',
                'R': '160,82,45'
            }.get(est, '0,0,0')
            cambios += 1
        else:
            # Si no hay match, dejar como NL
            props['ESTATUS 1'] = 'NL'
            props['COLOR'] = '#FF0000'
            props['COLOR_RGBA'] = '#FF0000FF'
            props['COLOR_RGB'] = '255,0,0'
            sin_match += 1

    # Guardar GeoJSON actualizado
    with open(OUTPUT_GEOJSON, 'w', encoding='utf-8') as f:
        json.dump(geojson, f, ensure_ascii=False)

    print(f"  Features actualizados: {cambios}")
    print(f"  Sin match (NL default): {sin_match}")
    print(f"  Guardado en: {OUTPUT_GEOJSON}")
    return True


def main():
    print("=" * 60)
    print("GENERAR GEOPORTAL V7")
    print("=" * 60)

    # 1. Descargar datos de Google Sheets
    print("\n0. Descargando Google Sheets...")
    try:
        gsheet_rows = download_gsheet_data()
        print(f"  Descargadas {len(gsheet_rows)} filas")
    except Exception as e:
        print(f"  ERROR al descargar Google Sheets: {e}")
        sys.exit(1)

    # 2. Construir lookup
    print("\n  Construyendo lookup table...")
    by_nom, by_id = build_lookup(gsheet_rows)
    print(f"  Nomenclaturas únicas: {len(by_nom)}")
    print(f"  IDs únicos: {len(by_id)}")

    # 3. Mostrar distribución de estatus según Sheets
    print("\n  Distribución de estatus según Google Sheets:")
    dist = {}
    for row_data in gsheet_rows:
        est = row_data['ESTATUS_1']
        dist[est] = dist.get(est, 0) + 1
    for est in ['L', 'NL', 'NG', 'R']:
        cnt = dist.get(est, 0)
        color_nombre = {'L': 'Verde', 'NL': 'Rojo', 'NG': 'Amarillo', 'R': 'Café'}.get(est, '?')
        print(f"    {est} ({color_nombre}): {cnt}")

    # 4. Convertir GPKG a GeoJSON
    ok = gpkg_to_geojson()
    if not ok:
        sys.exit(1)

    # 5. Actualizar GeoJSON con estatus de Sheets
    ok = actualizar_geojson_con_sheets(gsheet_rows, by_nom, by_id)
    if not ok:
        sys.exit(1)

    # 6. Generar datos de tabla
    ok = generar_datos_tabla(gsheet_rows, by_nom, by_id)
    if not ok:
        sys.exit(1)

    print("\n" + "=" * 60)
    print("COMPLETADO")
    print("=" * 60)
    print(f"  Abre el geoportal: open {OUTPUT_DIR}/index.html")
    print("=" * 60)


if __name__ == '__main__':
    main()
