#!/usr/bin/env python3
"""Generate geoportal_v7/index.html with embedded GeoJSON and table data."""
import json

# Read data
with open('geoportal_v7/predios.geojson') as f:
    geojson = json.load(f)
with open('geoportal_v7/datos_tabla.json') as f:
    tabla = json.load(f)

# Generate HTML with embedded data
html = '''<!DOCTYPE html>
<html lang="es">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Geoportal V7 - Predios</title>
    <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" />
    <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        html, body { height: 100%; font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; }
        #app { display: flex; height: 100vh; width: 100vw; }
        #map-container { flex: 1; position: relative; min-width: 0; }
        #map { width: 100%; height: 100%; }
        #panel-derecho { width: 480px; min-width: 380px; max-width: 600px; display: flex; flex-direction: column; background: #f5f5f5; border-left: 2px solid #ddd; }
        #panel-header { padding: 12px 16px; background: #2c3e50; color: white; display: flex; justify-content: space-between; align-items: center; }
        #panel-header h2 { font-size: 16px; font-weight: 600; }
        #panel-header .count { font-size: 13px; background: rgba(255,255,255,0.2); padding: 2px 10px; border-radius: 12px; }
        #filtros { padding: 10px 16px; background: white; border-bottom: 1px solid #ddd; display: flex; gap: 10px; flex-wrap: wrap; align-items: center; }
        #filtros label { font-size: 12px; font-weight: 600; color: #555; }
        #filtros select, #filtros input { padding: 5px 8px; border: 1px solid #ccc; border-radius: 4px; font-size: 13px; }
        #filtros select { min-width: 120px; }
        #filtros input { flex: 1; min-width: 100px; }
        .filtro-grupo { display: flex; align-items: center; gap: 4px; }
        #tabla-container { flex: 1; overflow-y: auto; overflow-x: hidden; }
        #tabla { width: 100%; border-collapse: collapse; font-size: 12px; }
        #tabla thead { position: sticky; top: 0; z-index: 1; }
        #tabla th { background: #34495e; color: white; padding: 8px 6px; text-align: left; font-weight: 600; font-size: 11px; white-space: nowrap; }
        #tabla td { padding: 6px; border-bottom: 1px solid rgba(0,0,0,0.1); cursor: pointer; transition: background 0.15s; }
        #tabla tr:hover td { filter: brightness(0.95); }
        #tabla tr.seleccionado td { outline: 3px solid #FF5722; outline-offset: -2px; }
        .estatus-badge { display: inline-block; padding: 2px 8px; border-radius: 10px; font-size: 11px; font-weight: 600; color: white; text-shadow: 0 1px 2px rgba(0,0,0,0.3); }
        #leyenda { position: absolute; bottom: 20px; left: 20px; background: white; padding: 10px 14px; border-radius: 6px; box-shadow: 0 2px 8px rgba(0,0,0,0.2); z-index: 1000; font-size: 12px; }
        #leyenda h4 { margin-bottom: 6px; font-size: 13px; color: #333; }
        .leyenda-item { display: flex; align-items: center; gap: 8px; margin: 3px 0; }
        .leyenda-color { width: 16px; height: 16px; border-radius: 3px; border: 1px solid rgba(0,0,0,0.2); }
        #buscador-mapa { position: absolute; top: 10px; left: 10px; z-index: 1000; background: white; padding: 8px 12px; border-radius: 6px; box-shadow: 0 2px 8px rgba(0,0,0,0.2); display: flex; gap: 6px; align-items: center; }
        #buscador-mapa input { padding: 6px 10px; border: 1px solid #ccc; border-radius: 4px; font-size: 13px; width: 200px; }
        #buscador-mapa button { padding: 6px 12px; background: #2c3e50; color: white; border: none; border-radius: 4px; cursor: pointer; font-size: 13px; }
        #buscador-mapa button:hover { background: #34495e; }
        .custom-tooltip { background: white; border: none; box-shadow: 0 2px 8px rgba(0,0,0,0.3); border-radius: 6px; padding: 8px 12px; font-size: 13px; }
        .custom-tooltip::before { border-top-color: white !important; }
        @media (max-width: 900px) { #app { flex-direction: column; } #panel-derecho { width: 100%; max-width: 100%; min-width: 0; height: 40vh; border-left: none; border-top: 2px solid #ddd; } #map-container { height: 60vh; } }
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
        </div>
        <div id="panel-derecho">
            <div id="panel-header"><h2>\U0001f4cb Predios</h2><span class="count" id="total-count">0</span></div>
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
        // DATOS EMBEBIDOS
        // ============================================================
        const PREDIOS_GEOJSON = ''' + json.dumps(geojson) + ''';

        const DATOS_TABLA = ''' + json.dumps(tabla) + ''';

        // ============================================================
        // CONFIGURACION
        // ============================================================
        const COLORES = { 'L': '#00FF00', 'NL': '#FF0000', 'NG': '#FFFF00', 'R': '#A0522D' };
        const ETIQUETAS = { 'L': 'Liberado', 'NL': 'No Liberado', 'NG': 'Negociaci\u00f3n', 'R': 'Revisi\u00f3n' };
        // Colores de fondo para filas de tabla (más suaves que los colores puros)
        const COLORES_FONDO = { 'L': '#DFF0D8', 'NL': '#F2DEDE', 'NG': '#FCF8E3', 'R': '#D6C8B0' };
        // Colores de texto para filas de tabla (contraste con fondo)
        const COLORES_TEXTO = { 'L': '#3C763D', 'NL': '#A94442', 'NG': '#8A6D3B', 'R': '#5C3A1E' };

        // ============================================================
        // ESTADO GLOBAL
        // ============================================================
        let map, layerGrupo = null;

        // ============================================================
        // INICIALIZAR MAPA
        // ============================================================
        function initMap() {
            map = L.map('map', { center: [20.72, -100.35], zoom: 10, zoomControl: true });

            L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
                attribution: '&copy; OpenStreetMap contributors', maxZoom: 19
            }).addTo(map);

            const baseMaps = {
                'Satelital': L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}', {
                    attribution: '&copy; Esri', maxZoom: 19
                }),
                'Calles': L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
                    attribution: '&copy; OpenStreetMap', maxZoom: 19
                })
            };
            L.control.layers(baseMaps, null, {position: 'topright'}).addTo(map);

            renderizarMapa();
            renderizarTabla();
            llenarFiltros();
        }

        // ============================================================
        // RENDERIZAR MAPA
        // ============================================================
        function renderizarMapa() {
            layerGrupo = L.geoJSON(PREDIOS_GEOJSON, {
                style: function(feature) {
                    const estatus = feature.properties.ESTATUS_1 || 'NL';
                    const color = COLORES[estatus] || '#CCCCCC';
                    return { fillColor: color, color: '#000000', weight: 1, opacity: 0.8, fillOpacity: 0.4 };
                },
                onEachFeature: function(feature, layer) {
                    const props = feature.properties;
                    const estatus = props.ESTATUS_1 || 'NL';
                    const label = ETIQUETAS[estatus] || estatus;
                    layer.bindTooltip(
                        '<strong>ID: ' + (props.ID || 'N/A') + '</strong><br><small>' + (props.NOMENCALTURA || '') + '</small><br><span style="color:' + COLORES[estatus] + '">\u25cf</span> ' + label,
                        { className: 'custom-tooltip', direction: 'center' }
                    );
                    layer.on('click', function() {
                        const id = props.ID || props.NOMENCALTURA || '';
                        seleccionarEnTabla(id);
                        map.fitBounds(layer.getBounds(), {padding: [30, 30]});
                    });
                }
            }).addTo(map);

            map.fitBounds(layerGrupo.getBounds(), {padding: [30, 30]});
        }

        // ============================================================
        // RENDERIZAR TABLA (orden = Google Sheets)
        // ============================================================
        function renderizarTabla(filtrados) {
            const datos = filtrados || DATOS_TABLA;
            const tbody = document.getElementById('tabla-body');

            if (datos.length === 0) {
                tbody.innerHTML = '<tr><td colspan="5" style="text-align:center;padding:20px;color:#999">Sin resultados</td></tr>';
                document.getElementById('total-count').textContent = '0';
                return;
            }

            let html = '';
            datos.forEach(function(row) {
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
            });

            tbody.innerHTML = html;
            document.getElementById('total-count').textContent = datos.length;
        }

        // ============================================================
        // FILTROS
        // ============================================================
        function llenarFiltros() {
            const segmentos = new Set();
            DATOS_TABLA.forEach(function(row) { if (row.Segmento) segmentos.add(row.Segmento); });
            const select = document.getElementById('filtro-segmento');
            Array.from(segmentos).sort().forEach(function(seg) {
                const opt = document.createElement('option');
                opt.value = seg; opt.textContent = seg; select.appendChild(opt);
            });
        }

        function aplicarFiltros() {
            const segmento = document.getElementById('filtro-segmento').value;
            const estatus = document.getElementById('filtro-estatus').value;
            const buscar = document.getElementById('filtro-buscar').value.toLowerCase().trim();

            let filtrados = DATOS_TABLA;
            if (segmento) filtrados = filtrados.filter(function(r) { return r.Segmento === segmento; });
            if (estatus) filtrados = filtrados.filter(function(r) { return r.ESTATUS_1 === estatus; });
            if (buscar) filtrados = filtrados.filter(function(r) {
                return (r.ID && r.ID.toLowerCase().includes(buscar)) ||
                       (r.NOMENCLATURA && r.NOMENCLATURA.toLowerCase().includes(buscar)) ||
                       (r.PROPIETARIO && r.PROPIETARIO.toLowerCase().includes(buscar));
            });

            renderizarTabla(filtrados);
            filtrarMapa(filtrados);
        }

        function filtrarMapa(filtrados) {
            if (!layerGrupo) return;
            const idsFiltrados = new Set();
            const nomsFiltrados = new Set();
            filtrados.forEach(function(row) { if (row.ID) idsFiltrados.add(row.ID); if (row.NOMENCLATURA) nomsFiltrados.add(row.NOMENCLATURA); });

            layerGrupo.eachLayer(function(layer) {
                const props = layer.feature.properties;
                const id = props.ID || '';
                const nom = props.NOMENCALTURA || '';
                const visible = idsFiltrados.has(id) || nomsFiltrados.has(nom);
                if (visible) {
                    if (!map.hasLayer(layer)) layer.addTo(map);
                    layer.setStyle({opacity: 0.8, fillOpacity: 0.4});
                } else {
                    layer.setStyle({opacity: 0.1, fillOpacity: 0.05});
                }
            });
        }

        // ============================================================
        // SELECCIONAR EN MAPA
        // ============================================================
        function seleccionarEnMapa(id, nom) {
            if (!layerGrupo) return;
            let encontrado = false;
            layerGrupo.eachLayer(function(layer) {
                const props = layer.feature.properties;
                if ((id && props.ID === id) || (nom && props.NOMENCALTURA === nom)) {
                    layer.setStyle({ weight: 3, color: '#FF5722', opacity: 1, fillOpacity: 0.6 });
                    map.fitBounds(layer.getBounds(), {padding: [30, 30]});
                    layer.openTooltip();
                    encontrado = true;
                } else {
                    const estatus = props.ESTATUS_1 || 'NL';
                    const color = COLORES[estatus] || '#CCCCCC';
                    layer.setStyle({ fillColor: color, color: '#000000', weight: 1, opacity: 0.8, fillOpacity: 0.4 });
                }
            });
            if (!encontrado) alert('Predio no encontrado en el mapa. Puede que no tenga pol\u00edgono.');
        }

        // ============================================================
        // SELECCIONAR EN TABLA
        // ============================================================
        function seleccionarEnTabla(id) {
            document.querySelectorAll('#tabla tr.seleccionado').forEach(function(el) { el.classList.remove('seleccionado'); });
            const filas = document.querySelectorAll('#tabla tbody tr');
            filas.forEach(function(fila) {
                const celda = fila.cells[1];
                if (celda && celda.textContent.trim() === id) {
                    fila.classList.add('seleccionado');
                    fila.scrollIntoView({behavior: 'smooth', block: 'center'});
                }
            });
        }

        // ============================================================
        // BUSCADOR DEL MAPA
        // ============================================================
        function buscarPredio() {
            const query = document.getElementById('search-input').value.trim();
            if (!query) return;
            const match = DATOS_TABLA.find(function(row) { return row.ID === query || row.NOMENCLATURA === query; });
            if (match) { seleccionarEnMapa(match.ID, match.NOMENCLATURA); seleccionarEnTabla(match.ID); }
            else {
                const parcial = DATOS_TABLA.find(function(row) {
                    return (row.ID && row.ID.toLowerCase().includes(query.toLowerCase())) ||
                           (row.NOMENCLATURA && row.NOMENCLATURA.toLowerCase().includes(query.toLowerCase()));
                });
                if (parcial) { seleccionarEnMapa(parcial.ID, parcial.NOMENCLATURA); seleccionarEnTabla(parcial.ID); }
                else alert('No se encontr\u00f3 ning\u00fan predio con ese ID o Nomenclatura');
            }
        }

        document.addEventListener('DOMContentLoaded', function() {
            document.getElementById('search-input').addEventListener('keypress', function(e) { if (e.key === 'Enter') buscarPredio(); });
        });

        // ============================================================
        // INICIAR
        // ============================================================
        initMap();
    </script>
</body>
</html>'''

with open('geoportal_v7/index.html', 'w', encoding='utf-8') as f:
    f.write(html)

print(f'HTML generado con {len(geojson["features"])} features y {len(tabla)} registros embebidos')
print(f'Tamaño: {len(html)} bytes')
