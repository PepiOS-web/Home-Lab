# 2026-09-22 - Prueba de restauracion parcial

## Objetivo

Comprobar que el backup no solo existe y supera SHA-256, sino que permite recuperar configuraciones esenciales sin modificar el servidor activo.

## Resultado

- Se extrajeron en un directorio temporal los proyectos Compose, configuracion SSH, UFW, unidades de systemd y scripts administrativos.
- Los scripts Bash y Python superaron sus comprobaciones de sintaxis.
- Las unidades del resumen saneado del portal fueron validadas.
- Todos los proyectos Compose superaron `docker compose config --quiet`.
- La copia recuperada conserva SSH mediante clave publica, sin contrasenas y sin acceso directo de root.
- El directorio temporal se elimino mediante una comprobacion estricta de ruta.
- El backup original permanecio intacto.

No se publican nombres de archivos de backup, rutas temporales, reglas reales de firewall, direcciones ni configuraciones privadas.
