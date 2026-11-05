import os
import sys

# Permite importar `app.*` sin instalar el paquete (ejecución local de pruebas).
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
