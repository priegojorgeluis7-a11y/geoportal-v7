#!/bin/bash
# ============================================================
# ACTUALIZAR PREDIOS V7
# ============================================================
# Este programa actualiza los colores y estatus de los predios
# en el GPKG usando los datos de Google Sheets.
#
# Solo haz doble clic en este archivo para ejecutarlo.
# ============================================================

# Obtener la ruta donde está este script
DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$DIR"

echo "============================================================"
echo "  ACTUALIZAR PREDIOS - V7"
echo "============================================================"
echo ""
echo "Este programa actualiza los predios del GPKG"
echo "usando los datos de Google Sheets."
echo ""

# Verificar que Python está instalado
if ! command -v python3 &> /dev/null; then
    echo "ERROR: Python 3 no está instalado."
    echo ""
    echo "Para instalar Python 3:"
    echo "  1. Abre https://www.python.org/downloads/"
    echo "  2. Descarga la última versión de Python 3"
    echo "  3. Ejecuta el instalador"
    echo "  4. Vuelve a hacer doble clic en este archivo"
    echo ""
    read -p "Presiona Enter para salir..."
    exit 1
fi

# Verificar que requests está instalado
python3 -c "import requests" 2>/dev/null
if [ $? -ne 0 ]; then
    echo "Instalando dependencia: requests..."
    pip3 install requests 2>&1
    if [ $? -ne 0 ]; then
        echo ""
        echo "ERROR: No se pudo instalar la librería requests."
        echo "Intenta ejecutar este comando en Terminal:"
        echo "  pip3 install requests"
        echo ""
        read -p "Presiona Enter para salir..."
        exit 1
    fi
    echo "  Dependencia instalada correctamente."
    echo ""
fi

# Ejecutar el script de actualización
echo "Ejecutando actualización..."
echo ""
python3 generate_colored_gpkg_v7.py

if [ $? -eq 0 ]; then
    echo ""
    echo "============================================================"
    echo "  ACTUALIZACIÓN COMPLETADA EXITOSAMENTE"
    echo "============================================================"
    echo ""
    echo "Archivos generados:"
    echo "  - poligonos_finales_coloreados_v7.gpkg"
    echo "  - poligonos_finales_coloreados_v7.qml"
    echo ""
    echo "Puedes abrir el GPKG en QGIS."
else
    echo ""
    echo "============================================================"
    echo "  ERROR DURANTE LA ACTUALIZACIÓN"
    echo "============================================================"
    echo ""
    echo "Revisa los mensajes de error arriba."
fi

echo ""
read -p "Presiona Enter para salir..."
