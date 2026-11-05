"""Núcleo cuantitativo puro: sin dependencias de framework (solo pandas/numpy).

Toda la lógica de inversión vive aquí y se prueba de forma aislada. La capa web
(FastAPI) y la de datos (SQLAlchemy / proveedores) dependen de este núcleo, nunca
al revés. Esto permite validar las decisiones de inversión sin levantar servidor
ni base de datos.
"""
